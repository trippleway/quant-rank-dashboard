"""Walk-forward backtest of the daily ranking (PLAN §5).

On every signal date ``t`` (first session of each week / month) the *same* ``rank_asof``
used for the daily Top 50 ranks the universe from the stored point-in-time features; the
equal-weight Top N is traded at the close of ``t + 1`` and held (drifting) until the next
trade. Benchmarks: SPY buy-and-hold, 60/40 SPY/AGG rebalanced monthly, equal-weight
eligible universe and random N-ticker portfolios (Monte Carlo "luck" benchmark), all with
the same cost model and timing. ``tests/test_backtest_lookahead.py`` checks that daily
returns up to any cutoff are unchanged when everything after the cutoff is removed.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from qrd.backtest.costs import CostModel
from qrd.backtest.engine import SimResult, segment_returns, simulate
from qrd.backtest.metrics import (
    YEAR,
    decile_returns,
    deflated_sharpe,
    information_coefficients,
    perf_metrics,
    t_stat,
)
from qrd.features.factors import BENCHMARK, price_for_returns
from qrd.features.regime import NEUTRAL, REGIMES
from qrd.scoring.config import GROUPS, PenaltyConfig, ScoringConfig
from qrd.scoring.rank import rank_asof
from qrd.scoring.select import daily_returns_wide
from qrd.universe import LiquidityPanel

WEEKLY = "weekly"
MONTHLY = "monthly"
FREQUENCIES = (WEEKLY, MONTHLY)
PERIODS_PER_YEAR = MappingProxyType({WEEKLY: 52, MONTHLY: 12})
BOND_BENCHMARK = "AGG"
STRATEGY = "strategy"
SPY = "spy"
SIXTY_FORTY = "sixty_forty"
EQUAL_WEIGHT = "equal_weight"
RANDOM_MEDIAN = "random_median"


def _backtest_scoring() -> ScoringConfig:
    return ScoringConfig(exclude_short_history=True)


@dataclass(frozen=True)
class BacktestConfig:
    years: float = 5.0  # requested length; shortened (and flagged) if history is too short
    min_years: float = 1.0
    start: pd.Timestamp | None = None  # explicit window (overrides ``years``)
    end: pd.Timestamp | None = None
    primary: str = MONTHLY  # frequency used for robustness checks (chosen a priori, ADR 0005)
    n_random: int = 1000
    seed: int = 42
    in_sample_years: float = 3.0
    min_eligible: int = 50  # first usable signal date needs this many backtest-eligible tickers
    rolling_window: int = YEAR
    capacity_participation: float = 0.01  # share of a ticker's ADV one rebalance may trade
    robustness: bool = True
    scoring: ScoringConfig = field(default_factory=_backtest_scoring)
    costs: CostModel = field(default_factory=CostModel)


# --- market data prepared once --------------------------------------------------------


@dataclass
class Market:
    factors: pd.DataFrame
    regime: pd.DataFrame  # columns date, regime, ...
    prices: pd.DataFrame
    calendar: pd.DatetimeIndex  # SPY sessions
    returns: pd.DataFrame  # calendar x ticker simple returns (NaN before the first bar)
    corr_returns: pd.DataFrame  # daily_returns_wide(prices), as used by the daily ranking
    liquidity: LiquidityPanel
    rf: pd.Series  # daily risk-free return on calendar (3m T-bill known at the prior close)
    rf_source: str
    meta: pd.DataFrame  # ticker -> asset_class, category, leverage
    _screens: dict[pd.Timestamp, pd.DataFrame] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        factors: pd.DataFrame,
        regime: pd.DataFrame,
        prices: pd.DataFrame,
        panel: pd.DataFrame | None = None,
    ) -> Market:
        regime = regime.reset_index() if "date" not in regime.columns else regime
        ref = prices.loc[prices["ticker"] == BENCHMARK, "date"]
        calendar = pd.DatetimeIndex(sorted((ref if not ref.empty else prices["date"]).unique()))
        bars = prices.sort_values(["ticker", "date"])
        px = bars.assign(px=price_for_returns(bars)).pivot_table(
            index="date", columns="ticker", values="px", aggfunc="last"
        )
        # forward-fill over missing bars (incl. after a ticker stops trading: held at its
        # last price), then sample on the calendar; returns between calendar sessions
        union = calendar.union(pd.DatetimeIndex(px.index))
        px = px.sort_index().ffill().reindex(union).ffill().reindex(calendar)
        returns = px / px.shift(1) - 1
        rf_source = "ust_3m"
        if panel is not None and "ust_3m" in panel.columns:
            p = panel.set_index("date") if "date" in panel.columns else panel
            rate = p["ust_3m"].astype(float).reindex(calendar).ffill()
            rf = (rate / 100 / YEAR).shift(1).fillna(0.0)
        else:
            rf, rf_source = pd.Series(0.0, index=calendar), "none (0%)"
        meta = (
            factors.sort_values("date")
            .groupby("ticker")[["asset_class", "category", "leverage"]]
            .last()
        )
        return cls(
            factors=factors,
            regime=regime,
            prices=prices,
            calendar=calendar,
            returns=returns,
            corr_returns=daily_returns_wide(prices),
            liquidity=LiquidityPanel.build(prices),
            rf=rf,
            rf_source=rf_source,
            meta=meta,
        )

    def screen(self, day: pd.Timestamp) -> pd.DataFrame:
        if day not in self._screens:
            self._screens[day] = self.liquidity.on(day)
        return self._screens[day]

    def regime_labels(self) -> pd.Series:
        """Regime label known at the close *before* each session (what a trader could act on)."""
        lab = self.regime.set_index("date")["regime"].reindex(self.calendar)
        return lab.shift(1).fillna("unknown").astype(str)


# --- schedule -------------------------------------------------------------------------


def signal_dates(
    calendar: pd.DatetimeIndex, freq: str, start: pd.Timestamp, end: pd.Timestamp
) -> list[pd.Timestamp]:
    """First session of ``start``'s window and of every later week / month, up to ``end``.

    "First session of a period" is decided by comparing with the *previous* session, so it
    is knowable on the day itself (unlike "last session of the month"). Only dates whose
    trade session (the next one) is ``<= end`` are kept.
    """
    rule = {WEEKLY: "W-SUN", MONTHLY: "M"}[freq]
    periods = calendar.to_period(rule)
    new_period = np.r_[True, periods[1:] != periods[:-1]]
    pos = np.flatnonzero((calendar >= start) & (calendar <= end))
    if len(pos) == 0:
        return []
    keep = [int(pos[0])] + [int(i) for i in pos[1:] if new_period[i]]
    return [
        pd.Timestamp(calendar[i]) for i in keep if i + 1 < len(calendar) and calendar[i + 1] <= end
    ]


def backtest_window(
    market: Market, cfg: BacktestConfig
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, bool]:
    """(start, end, requested_start, shortened)."""
    end = pd.Timestamp(cfg.end) if cfg.end is not None else market.calendar[-1]
    requested = (
        pd.Timestamp(cfg.start)
        if cfg.start is not None
        else end - pd.DateOffset(months=round(cfg.years * 12))
    )
    f = market.factors
    usable = f[f["date"] <= end]
    if cfg.scoring.exclude_short_history:
        usable = usable[~usable["short_history"].fillna(True).astype(bool)]
    counts = usable.groupby("date")["ticker"].nunique()
    ok = counts.index[counts >= cfg.min_eligible]
    if len(ok) == 0:
        raise ValueError(f"no date with >= {cfg.min_eligible} backtest-eligible tickers")
    start = max(requested, pd.Timestamp(ok[0]))
    start = pd.Timestamp(market.calendar[int(market.calendar.searchsorted(start))])
    if (end - start).days < cfg.min_years * 365.25 - 7:
        raise ValueError(
            f"backtest window {start.date()}..{end.date()} is shorter than {cfg.min_years} years"
        )
    return start, end, requested, bool(start > requested + pd.Timedelta(days=7))


# --- ranking on signal dates -----------------------------------------------------------


@dataclass
class RankStep:
    signal: pd.Timestamp
    selected: list[str]  # Top N in rank order
    scores: pd.Series  # ticker -> score for every backtest-eligible ticker
    adv: pd.Series  # ticker -> 60-session ADV (screen) for costs and capacity
    regime: str


def rank_steps(market: Market, dates: list[pd.Timestamp], cfg: ScoringConfig) -> list[RankStep]:
    steps = []
    for day in dates:
        screen = market.screen(day)
        res = rank_asof(
            market.factors,
            market.regime,
            market.prices,
            asof=day,
            cfg=cfg,
            screen=screen,
            returns=market.corr_returns,
        )
        scored = res.scored.dropna(subset=["score"])
        steps.append(
            RankStep(
                signal=day,
                selected=res.top["ticker"].astype(str).tolist(),
                scores=scored.set_index("ticker")["score"].astype(float),
                adv=screen.set_index("ticker")["adv_usd"].astype(float),
                regime=str(res.regime["label"]),
            )
        )
    return steps


# --- simulation helpers -----------------------------------------------------------------


@dataclass
class Book:
    """Column layout + per-trade cost rates shared by all portfolios of one schedule."""

    tickers: list[str]
    col: dict[str, int]
    returns: np.ndarray  # (D, N)

    @classmethod
    def of(cls, market: Market) -> Book:
        tickers = [str(t) for t in market.returns.columns]
        return cls(tickers, {t: i for i, t in enumerate(tickers)}, market.returns.to_numpy())

    def weights(self, names: list[str] | pd.Index) -> np.ndarray:
        w = np.zeros((1, len(self.tickers)))
        idx = [self.col[n] for n in names if n in self.col]
        if idx:
            w[0, idx] = 1.0 / len(idx)
        return w

    def cost_rates(self, market: Market, adv: pd.Series, costs: CostModel) -> np.ndarray:
        meta = market.meta.reindex(self.tickers)
        bps = costs.bps(
            adv.reindex(self.tickers), meta["leverage"].fillna(1.0), meta["asset_class"].fillna("")
        )
        return bps.to_numpy() / 1e4


def _series(market: Market, sim: SimResult, row: int = 0) -> pd.Series:
    return pd.Series(sim.daily[row], index=market.calendar)


@dataclass
class PortfolioRun:
    daily: pd.Series  # NaN before the first trade
    turnover: np.ndarray  # one-way per trade (first entry = initial build from cash)
    cost: np.ndarray
    trade_idx: list[int]

    def period_returns(self) -> pd.Series:
        eq = (1 + self.daily.fillna(0.0)).cumprod()
        marks = eq.iloc[np.array([*self.trade_idx, len(eq) - 1])]
        out: pd.Series = (marks / marks.shift(1) - 1).iloc[1:]
        return out


def _run(
    market: Market,
    book: Book,
    trade_idx: list[int],
    targets: Callable[[int], np.ndarray],
    rates: Callable[[int], np.ndarray],
) -> PortfolioRun:
    sim = simulate(book.returns, trade_idx, targets, rates)
    return PortfolioRun(_series(market, sim), sim.turnover[0], sim.cost[0], trade_idx)


def strategy_run(
    market: Market, book: Book, steps: list[RankStep], trade_idx: list[int], costs: CostModel
) -> PortfolioRun:
    return _run(
        market,
        book,
        trade_idx,
        lambda k: book.weights(steps[k].selected),
        lambda k: book.cost_rates(market, steps[k].adv, costs),
    )


@dataclass
class RandomSummary:
    n: int
    seed: int
    cagr: np.ndarray
    sharpe: np.ndarray
    max_drawdown: np.ndarray
    equity_quantiles: pd.DataFrame  # p05, p50, p95 equity curves from the first trade
    median_daily: pd.Series  # daily returns of the median-CAGR simulation


def random_run(
    market: Market,
    *,
    book: Book,
    steps: list[RankStep],
    trade_idx: list[int],
    costs: CostModel,
    n: int,
    seed: int,
) -> RandomSummary:
    """``n`` portfolios picking as many tickers as the strategy, uniformly from the eligible."""
    rng = np.random.default_rng(seed)

    def targets(k: int) -> np.ndarray:
        elig = np.array([book.col[t] for t in steps[k].scores.index if t in book.col])
        m = min(len(steps[k].selected), len(elig))
        w = np.zeros((n, len(book.tickers)))
        if m == 0:
            return w
        picks = np.argsort(rng.random((n, len(elig))), axis=1)[:, :m]
        np.put_along_axis(w, elig[picks], 1.0 / m, axis=1)
        return w

    sim = simulate(
        book.returns, trade_idx, targets, lambda k: book.cost_rates(market, steps[k].adv, costs)
    )
    t0 = trade_idx[0]
    daily = sim.daily[:, t0:]
    rf = market.rf.to_numpy()[t0:]
    eq = np.cumprod(1 + daily, axis=1)
    n_days = daily.shape[1]
    cagr = eq[:, -1] ** (YEAR / n_days) - 1
    ex = daily - rf[None, :]
    sd = ex.std(axis=1, ddof=1)
    sharpe = np.where(sd > 0, ex.mean(axis=1) / np.where(sd > 0, sd, 1) * math.sqrt(YEAR), np.nan)
    mdd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    idx = market.calendar[t0:]
    quant = pd.DataFrame(
        np.quantile(eq, [0.05, 0.5, 0.95], axis=0).T, index=idx, columns=["p05", "p50", "p95"]
    )
    med = int(np.argsort(cagr)[len(cagr) // 2])
    median_daily = pd.Series(np.r_[np.full(t0, np.nan), daily[med]], index=market.calendar)
    return RandomSummary(n, seed, cagr, sharpe, mdd, quant, median_daily)


# --- one frequency ----------------------------------------------------------------------


@dataclass
class FrequencyResult:
    freq: str
    steps: list[RankStep]
    trade_idx: list[int]
    runs: dict[str, PortfolioRun]  # strategy, spy, sixty_forty, equal_weight
    random: RandomSummary | None
    ic: pd.DataFrame  # signal, ic, rank_ic, n
    deciles: pd.DataFrame  # one row per complete period, columns 1..10
    capacity: dict[str, float | None]


def _trade_index(market: Market, dates: list[pd.Timestamp]) -> list[int]:
    return [int(market.calendar.searchsorted(d)) + 1 for d in dates]


def run_frequency(
    market: Market,
    *,
    book: Book,
    freq: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cfg: BacktestConfig,
    steps: list[RankStep] | None = None,
) -> FrequencyResult:
    dates = signal_dates(market.calendar, freq, start, end)
    dates = [d for d in dates if (market.factors["date"] == d).any()]
    if len(dates) < 2:  # noqa: PLR2004
        raise ValueError(f"fewer than 2 {freq} signal dates in {start.date()}..{end.date()}")
    steps = steps if steps is not None else rank_steps(market, dates, cfg.scoring)
    trade_idx = _trade_index(market, dates)
    rates = lambda k: book.cost_rates(market, steps[k].adv, cfg.costs)  # noqa: E731
    runs = {STRATEGY: strategy_run(market, book, steps, trade_idx, cfg.costs)}
    runs[EQUAL_WEIGHT] = _run(
        market, book, trade_idx, lambda k: book.weights(steps[k].scores.index), rates
    )
    if BENCHMARK in book.col:
        runs[SPY] = _run(market, book, trade_idx[:1], lambda k: book.weights([BENCHMARK]), rates)
        if BOND_BENCHMARK in book.col:
            monthly = signal_dates(market.calendar, MONTHLY, start, end)
            m_idx = _trade_index(market, monthly)
            w6040 = np.zeros((1, len(book.tickers)))
            w6040[0, book.col[BENCHMARK]], w6040[0, book.col[BOND_BENCHMARK]] = 0.6, 0.4

            def rates_6040(k: int) -> np.ndarray:
                adv = market.screen(monthly[k]).set_index("ticker")["adv_usd"].astype(float)
                return book.cost_rates(market, adv, cfg.costs)

            runs[SIXTY_FORTY] = _run(market, book, m_idx, lambda k: w6040, rates_6040)
    random = (
        random_run(
            market,
            book=book,
            steps=steps,
            trade_idx=trade_idx,
            costs=cfg.costs,
            n=cfg.n_random,
            seed=cfg.seed,
        )
        if cfg.n_random > 0
        else None
    )
    ic_rows, dec_rows = [], []
    fwd_all = segment_returns(book.returns, trade_idx)
    for k in range(len(trade_idx) - 1):
        fwd = pd.Series(fwd_all[k], index=book.tickers)
        sc = steps[k].scores
        ic, ric = information_coefficients(sc, fwd.reindex(sc.index))
        ic_rows.append((steps[k].signal, ic, ric, len(sc)))
        dec = decile_returns(sc, fwd.reindex(sc.index))
        if dec is not None:
            dec_rows.append(dec.rename(steps[k].signal))
    ic_df = pd.DataFrame(ic_rows, columns=["signal", "ic", "rank_ic", "n"])
    deciles = pd.DataFrame(dec_rows)
    caps, advs = [], []
    for s in steps:
        if s.selected:
            a = s.adv.reindex(s.selected)
            caps.append(float(a.min()) * cfg.capacity_participation * len(s.selected))
            advs.append(float(a.median()))
    capacity = {
        "participation": cfg.capacity_participation,
        "median_aum_usd": float(np.median(caps)) if caps else None,
        "min_aum_usd": float(np.min(caps)) if caps else None,
        "median_holding_adv_usd": float(np.median(advs)) if advs else None,
    }
    return FrequencyResult(freq, steps, trade_idx, runs, random, ic_df, deciles, capacity)


# --- robustness -------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    name: str
    kind: str  # "sensitivity" | "ablation"
    label: str
    scoring: ScoringConfig | None  # None: reuse the base ranking (cost-only variants)
    costs: CostModel | None = None


def _zero_group(cfg: ScoringConfig, group: str) -> ScoringConfig:
    weights = MappingProxyType(
        {
            reg: MappingProxyType({g: (0.0 if g == group else w[g]) for g in GROUPS})
            for reg, w in cfg.regime_weights.items()
        }
    )
    return replace(cfg, regime_weights=weights)


def default_variants(base: ScoringConfig, costs: CostModel) -> list[Variant]:
    sel, norm, pen = base.selection, base.normalization, base.penalties
    neutral = base.regime_weights[NEUTRAL]
    out = [
        Variant(
            "top_n_30", "sensitivity", "Top 30", replace(base, selection=replace(sel, top_n=30))
        ),
        Variant(
            "conc_0",
            "sensitivity",
            "無集中度懲罰",
            replace(base, selection=replace(sel, concentration_penalty=0.0)),
        ),
        Variant(
            "conc_0.08",
            "sensitivity",
            "集中度懲罰 ×2",
            replace(base, selection=replace(sel, concentration_penalty=0.08)),
        ),
        Variant(
            "corr_0.90",
            "sensitivity",
            "相關性去重門檻 0.90",
            replace(base, selection=replace(sel, max_correlation=0.90)),
        ),
        Variant(
            "blend_pooled",
            "sensitivity",
            "只用全體 z-score",
            replace(base, normalization=replace(norm, group_blend=0.0)),
        ),
        Variant(
            "blend_within",
            "sensitivity",
            "只用類別內 z-score",
            replace(base, normalization=replace(norm, group_blend=1.0)),
        ),
        Variant(
            "winsor_1_99",
            "sensitivity",
            "Winsorize 1%/99%",
            replace(base, normalization=replace(norm, lower_pct=0.01, upper_pct=0.99)),
        ),
        Variant(
            "penalty_x2",
            "sensitivity",
            "風險懲罰 ×2",
            replace(
                base,
                penalties=PenaltyConfig(
                    per_extra_leverage=pen.per_extra_leverage * 2,
                    inverse=pen.inverse * 2,
                    volatility_etp=pen.volatility_etp * 2,
                    high_vol_threshold=pen.high_vol_threshold,
                    high_vol_slope=pen.high_vol_slope * 2,
                    high_vol_cap=pen.high_vol_cap * 2,
                    short_history=pen.short_history * 2,
                ),
            ),
        ),
        Variant("cost_x0.5", "sensitivity", "成本 ×0.5", None, replace(costs, multiplier=0.5)),
        Variant("cost_x2", "sensitivity", "成本 ×2", None, replace(costs, multiplier=2.0)),
        Variant(
            "no_regime",
            "ablation",
            "不分 regime（固定 neutral 權重）",
            replace(
                base, regime_weights=MappingProxyType({r: neutral for r in base.regime_weights})
            ),
        ),
        *[Variant(f"no_{g}", "ablation", f"移除 {g} 群組", _zero_group(base, g)) for g in GROUPS],
        Variant(
            "no_risk_penalty",
            "ablation",
            "移除風險懲罰",
            replace(
                base,
                penalties=PenaltyConfig(
                    per_extra_leverage=0.0,
                    inverse=0.0,
                    volatility_etp=0.0,
                    high_vol_slope=0.0,
                    high_vol_cap=0.0,
                    short_history=0.0,
                ),
            ),
        ),
    ]
    return out


@dataclass
class VariantResult:
    variant: Variant
    run: PortfolioRun


@dataclass
class BacktestResult:
    cfg: BacktestConfig
    market: Market
    start: pd.Timestamp
    end: pd.Timestamp
    requested_start: pd.Timestamp
    shortened: bool
    in_sample_end: pd.Timestamp
    results: dict[str, FrequencyResult]
    variants: list[VariantResult]
    regime_labels: pd.Series = field(repr=False, default_factory=pd.Series)


def in_sample_end(start: pd.Timestamp, end: pd.Timestamp, cfg: BacktestConfig) -> pd.Timestamp:
    """First ``in_sample_years`` are in-sample; if that leaves < 1 year, split at 60%."""
    split = start + pd.DateOffset(months=round(cfg.in_sample_years * 12))
    if (end - split).days < 365:  # noqa: PLR2004
        split = start + (end - start) * 0.6
    return pd.Timestamp(split)


def run_backtest(market: Market, cfg: BacktestConfig | None = None) -> BacktestResult:
    c = cfg or BacktestConfig()
    if c.primary not in FREQUENCIES:
        raise ValueError(f"primary must be one of {FREQUENCIES}")
    start, end, requested, shortened = backtest_window(market, c)
    book = Book.of(market)
    results = {
        f: run_frequency(market, book=book, freq=f, start=start, end=end, cfg=c)
        for f in FREQUENCIES
    }
    variants: list[VariantResult] = []
    if c.robustness:
        prim = results[c.primary]
        for v in default_variants(c.scoring, c.costs):
            costs = v.costs or c.costs
            steps = (
                prim.steps
                if v.scoring is None
                else rank_steps(market, [s.signal for s in prim.steps], v.scoring)
            )
            variants.append(
                VariantResult(v, strategy_run(market, book, steps, prim.trade_idx, costs))
            )
    return BacktestResult(
        cfg=c,
        market=market,
        start=start,
        end=end,
        requested_start=requested,
        shortened=shortened,
        in_sample_end=in_sample_end(start, end, c),
        results=results,
        variants=variants,
        regime_labels=market.regime_labels(),
    )


# --- summaries used by the report ---------------------------------------------------------


def metrics_table(res: BacktestResult, fr: FrequencyResult) -> dict[str, dict[str, float | None]]:
    rf = res.market.rf
    out = {}
    for name, run in fr.runs.items():
        m = perf_metrics(run.daily, rf, run.period_returns())
        if len(run.turnover) > 1:
            years = run.daily.notna().sum() / YEAR
            m["turnover_annual"] = float(run.turnover[1:].sum() / years)
            m["cost_drag_annual"] = float(run.cost.sum() / years)
        else:
            m["turnover_annual"] = 0.0
            m["cost_drag_annual"] = float(run.cost.sum())
        out[name] = m
    if fr.random is not None:
        out[RANDOM_MEDIAN] = perf_metrics(fr.random.median_daily, rf)
    return out


def split_metrics(
    res: BacktestResult, fr: FrequencyResult
) -> dict[str, dict[str, dict[str, float | None]]]:
    rf, cut = res.market.rf, res.in_sample_end
    out: dict[str, dict[str, dict[str, float | None]]] = {"in_sample": {}, "out_of_sample": {}}
    for name, run in fr.runs.items():
        d = run.daily.dropna()
        out["in_sample"][name] = perf_metrics(d[d.index < cut], rf)
        out["out_of_sample"][name] = perf_metrics(d[d.index >= cut], rf)
    return out


def regime_table(res: BacktestResult, fr: FrequencyResult) -> dict[str, dict[str, object]]:
    labels, rf = res.regime_labels, res.market.rf
    out: dict[str, dict[str, object]] = {}
    for reg in REGIMES:
        days = labels.index[labels == reg]
        row: dict[str, object] = {}
        for name, run in fr.runs.items():
            d = run.daily.reindex(days).dropna()
            if len(d) < 2:  # noqa: PLR2004
                continue
            ex = d - rf.reindex(d.index)
            sd = float(ex.std(ddof=1))
            row[name] = {
                "ann_return": float(d.mean() * YEAR),
                "ann_vol": float(d.std(ddof=1) * math.sqrt(YEAR)),
                "sharpe": float(ex.mean() / sd * math.sqrt(YEAR)) if sd > 0 else None,
            }
        if row:
            n = int(fr.runs[STRATEGY].daily.reindex(days).notna().sum())
            out[reg] = {"days": n, **row}
    return out


def ic_summary(fr: FrequencyResult) -> dict[str, object]:
    ic, ric = fr.ic["ic"].astype(float), fr.ic["rank_ic"].astype(float)
    ppy = PERIODS_PER_YEAR[fr.freq]
    dec = fr.deciles
    out: dict[str, object] = {
        "periods": int(ic.notna().sum()),
        "mean_ic": float(ic.mean()) if ic.notna().any() else None,
        "mean_rank_ic": float(ric.mean()) if ric.notna().any() else None,
        "rank_ic_std": float(ric.std(ddof=1)) if ric.notna().sum() > 1 else None,
        "rank_ic_t": t_stat(ric),
        "rank_ic_ir_annual": (
            float(ric.mean() / ric.std(ddof=1) * math.sqrt(ppy))
            if ric.notna().sum() > 1 and ric.std(ddof=1) > 0
            else None
        ),
        "rank_ic_hit_rate": float((ric > 0).mean()) if ric.notna().any() else None,
    }
    if not dec.empty:
        spread = dec[dec.columns.max()] - dec[dec.columns.min()]
        out["deciles"] = {
            "mean_period_return": {str(k): float(v) for k, v in dec.mean().items()},
            "ann_return": {str(k): float((1 + v) ** ppy - 1) for k, v in dec.mean().items()},
            "top_minus_bottom_mean_period": float(spread.mean()),
            "top_minus_bottom_t": t_stat(spread),
        }
    return out


def variant_table(res: BacktestResult) -> list[dict[str, Any]]:
    rf, cut = res.market.rf, res.in_sample_end
    prim = res.results[res.cfg.primary].runs[STRATEGY]
    rows = [("base", "base", "預設參數", prim)]
    rows += [(v.variant.name, v.variant.kind, v.variant.label, v.run) for v in res.variants]
    out = []
    for name, kind, label, run in rows:
        d = run.daily.dropna()
        full = perf_metrics(d, rf)
        years = len(d) / YEAR
        out.append(
            {
                "name": name,
                "kind": kind,
                "label": label,
                "cagr": full["cagr"],
                "sharpe": full["sharpe"],
                "max_drawdown": full["max_drawdown"],
                "turnover_annual": float(run.turnover[1:].sum() / years) if years else None,
                "sharpe_in_sample": perf_metrics(d[d.index < cut], rf)["sharpe"],
                "sharpe_out_of_sample": perf_metrics(d[d.index >= cut], rf)["sharpe"],
            }
        )
    return out


def deflated(res: BacktestResult) -> dict[str, float | None]:
    rf = res.market.rf
    runs = [res.results[res.cfg.primary].runs[STRATEGY]] + [v.run for v in res.variants]
    excess = [(r.daily - rf).dropna() for r in runs]
    trials = [float(x.mean() / x.std(ddof=1)) for x in excess if x.std(ddof=1) > 0]
    return deflated_sharpe(excess[0], trials)

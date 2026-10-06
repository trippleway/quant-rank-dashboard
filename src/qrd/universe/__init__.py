"""Universe construction and liquidity filtering.

The candidate list is a static, versioned seed file (``seeds.csv``) so runs are
reproducible. It is a *current* snapshot, which introduces survivorship bias in
backtests — disclosed in docs/adr/0002-data-sources-and-storage.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import pandas as pd

ASSET_CLASSES = frozenset(
    {"equity", "equity_etf", "bond_etf", "commodity_etf", "currency_etf", "volatility_etp"}
)
INSTRUMENTS = frozenset({"stock", "etf", "etn"})
UNIVERSE_COLUMNS = ["ticker", "asset_class", "category", "leverage", "instrument"]


def load_universe() -> pd.DataFrame:
    """Load and validate the packaged seed universe."""
    with resources.files("qrd.universe").joinpath("seeds.csv").open("r", encoding="utf-8") as fh:
        df = pd.read_csv(fh, comment="#")
    validate_universe(df)
    df["leveraged_or_inverse"] = df["leverage"] != 1
    return df.reset_index(drop=True)


def validate_universe(df: pd.DataFrame) -> None:
    missing = set(UNIVERSE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"universe missing columns: {sorted(missing)}")
    dups = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
    if dups:
        raise ValueError(f"duplicate tickers in universe: {dups}")
    bad_cls = set(df["asset_class"]) - ASSET_CLASSES
    if bad_cls:
        raise ValueError(f"unknown asset classes: {sorted(bad_cls)}")
    bad_inst = set(df["instrument"]) - INSTRUMENTS
    if bad_inst:
        raise ValueError(f"unknown instruments: {sorted(bad_inst)}")
    if (df["leverage"] == 0).any():
        raise ValueError("leverage must be non-zero")
    stocks_with_leverage = df[(df["instrument"] == "stock") & (df["leverage"] != 1)]
    if not stocks_with_leverage.empty:
        raise ValueError("single stocks cannot carry a leverage factor")


@dataclass(frozen=True)
class LiquidityRules:
    adv_window: int = 60  # sessions for average daily dollar volume
    min_adv_usd: float = 5_000_000.0
    min_price: float = 5.0
    min_history_sessions: int = 60  # enough for the ADV window; longer history is a confidence flag


def _exclusion_reason(sessions: int, last_close: float, adv: float, r: LiquidityRules) -> str:
    reasons = []
    if sessions < r.min_history_sessions:
        reasons.append(f"history {sessions} < {r.min_history_sessions} sessions")
    if not last_close >= r.min_price:
        reasons.append(f"price {last_close:.2f} < {r.min_price:.2f}")
    if not adv >= r.min_adv_usd:
        reasons.append(f"ADV ${adv:,.0f} < ${r.min_adv_usd:,.0f}")
    return "; ".join(reasons)


LIQUIDITY_COLUMNS = ["ticker", "sessions", "last_close", "adv_usd", "eligible", "reason"]


def liquidity_filter(
    prices: pd.DataFrame, asof: pd.Timestamp, rules: LiquidityRules | None = None
) -> pd.DataFrame:
    """Evaluate the liquidity screen for each ticker using only bars dated ``<= asof``.

    ``prices`` is long-format canonical bars. Returns one row per ticker with the screen
    inputs, ``eligible`` and a human-readable ``reason`` for exclusions.
    """
    r = rules or LiquidityRules()
    hist = prices[prices["date"] <= asof]  # no look-ahead: nothing after asof is visible
    if hist.empty:
        return pd.DataFrame(columns=LIQUIDITY_COLUMNS)
    rows = []
    for ticker, group in hist.sort_values("date").groupby("ticker", sort=True):
        g = group.dropna(subset=["close"])
        sessions = len(g)
        last_close = float(g["close"].iloc[-1]) if sessions else float("nan")
        tail = g.tail(r.adv_window)
        adv = float((tail["close"] * tail["volume"]).mean()) if sessions else float("nan")
        reason = _exclusion_reason(sessions, last_close, adv, r)
        rows.append((ticker, sessions, last_close, adv, not reason, reason))
    return pd.DataFrame(rows, columns=LIQUIDITY_COLUMNS)


@dataclass
class LiquidityPanel:
    """Screen inputs for every date at once (for backtests that rank many dates).

    ``on(asof)`` returns the same table as ``liquidity_filter(prices, asof)`` — each value
    still uses only bars dated ``<= asof`` (trailing counts / rolling means, forward-filled
    over days without a bar), it is just computed once instead of per date.
    """

    sessions: pd.DataFrame  # date x ticker
    last_close: pd.DataFrame
    adv_usd: pd.DataFrame
    rules: LiquidityRules

    @classmethod
    def build(cls, prices: pd.DataFrame, rules: LiquidityRules | None = None) -> LiquidityPanel:
        r = rules or LiquidityRules()
        g = prices.dropna(subset=["close"]).sort_values(["ticker", "date"], kind="stable")
        by = g.groupby("ticker", sort=False)
        stats = pd.DataFrame(
            {
                "date": g["date"].to_numpy(),
                "ticker": g["ticker"].to_numpy(),
                "sessions": (by.cumcount() + 1).to_numpy(dtype=float),
                "last_close": g["close"].to_numpy(dtype=float),
                "adv_usd": (g["close"] * g["volume"])
                .groupby(g["ticker"], sort=False)
                .transform(lambda s: s.rolling(r.adv_window, min_periods=1).mean())
                .to_numpy(dtype=float),
            }
        )
        dates = pd.DatetimeIndex(sorted(prices["date"].unique()))

        def wide(col: str) -> pd.DataFrame:
            w = stats.pivot_table(index="date", columns="ticker", values=col, aggfunc="last")
            return w.reindex(dates).ffill()

        return cls(wide("sessions"), wide("last_close"), wide("adv_usd"), r)

    def on(self, asof: pd.Timestamp) -> pd.DataFrame:
        pos = int(self.sessions.index.searchsorted(asof, side="right")) - 1
        if pos < 0:
            return pd.DataFrame(columns=LIQUIDITY_COLUMNS)
        sessions = self.sessions.iloc[pos]
        closes, advs = self.last_close.iloc[pos], self.adv_usd.iloc[pos]
        rows = []
        for ticker in sorted(sessions.index[sessions.notna()]):
            n = int(sessions[ticker])
            last_close, adv = float(closes[ticker]), float(advs[ticker])
            reason = _exclusion_reason(n, last_close, adv, self.rules)
            rows.append((ticker, n, last_close, adv, not reason, reason))
        return pd.DataFrame(rows, columns=LIQUIDITY_COLUMNS)

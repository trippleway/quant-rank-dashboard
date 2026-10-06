"""Per-ticker daily price factors (point-in-time).

Every factor on date ``t`` is a function of bars dated ``<= t`` only: all windows are
trailing (``shift`` with positive lags, ``rolling`` without ``center``). The value on
``t`` uses the close of ``t`` and is meant for trading on ``t+1`` (PLAN.md §5).
Look-ahead tests: ``tests/test_lookahead.py``.

Missing history yields NaN, never 0 — scoring (M3) down-weights missing factors instead
of treating them as neutral values.

Factors (windows in sessions):

* ``mom_12_1`` — return from t-252 to t-21 (skip the most recent month)
* ``mom_6m`` / ``mom_3m`` — 126 / 63 session return
* ``trend_200`` — price / 200-session SMA − 1
* ``vol_63`` — annualised realised volatility of daily returns
* ``downside_63`` — annualised downside deviation (returns below 0)
* ``max_dd_252`` — worst peak-to-trough drawdown inside the trailing 252 sessions (≤ 0)
* ``beta_252`` — beta of daily returns vs the benchmark (SPY), min 126 observations
* ``adv_usd_60`` — average daily dollar volume (unadjusted close × volume)
* ``amihud_60`` — Amihud illiquidity: mean(|return| / dollar volume) × 1e6
* ``trailing_yield_252`` — trailing 12-month distribution yield proxy:
  total return (adj_close) over price return (close) − 1. Only dividends paid inside the
  window affect the ratio, so retroactive Yahoo adjustments do not leak future data.
* ``history_sessions`` / ``short_history`` — bars so far; short = fewer than 252

Bond-specific ``rate_duration`` (empirical duration vs the 10y yield) needs macro data
and is computed by :func:`compute_rate_duration`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

TRADING_DAYS = 252
BENCHMARK = "SPY"

FACTOR_COLUMNS = [
    "mom_12_1",
    "mom_6m",
    "mom_3m",
    "trend_200",
    "vol_63",
    "downside_63",
    "max_dd_252",
    "beta_252",
    "adv_usd_60",
    "amihud_60",
    "trailing_yield_252",
    "history_sessions",
    "short_history",
]


@dataclass(frozen=True)
class FactorConfig:
    mom_long: int = 252
    mom_skip: int = 21
    mom_mid: int = 126
    mom_short: int = 63
    trend_window: int = 200
    vol_window: int = 63
    vol_min_periods: int = 50
    dd_window: int = 252
    beta_window: int = 252
    beta_min_periods: int = 126
    liq_window: int = 60
    liq_min_periods: int = 40
    yield_window: int = 252
    short_history_sessions: int = 252


def price_for_returns(bars: pd.DataFrame) -> pd.Series:
    """Dividend-adjusted close, falling back to the split-adjusted close where missing."""
    return bars["adj_close"].where(bars["adj_close"].notna(), bars["close"]).astype(float)


def rolling_max_drawdown(px: pd.Series, window: int) -> pd.Series:
    """Exact max drawdown using only peaks inside each trailing window (NaN until full)."""
    values = px.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) >= window:
        win = sliding_window_view(values, window)
        peaks = np.fmax.accumulate(win, axis=1)
        out[window - 1 :] = np.nanmin(win / peaks - 1.0, axis=1)
    return pd.Series(out, index=px.index)


def _ticker_factors(g: pd.DataFrame, bench_px: pd.Series | None, cfg: FactorConfig) -> pd.DataFrame:
    px = price_for_returns(g)
    ret = px.pct_change(fill_method=None)
    ann = math.sqrt(TRADING_DAYS)
    out = pd.DataFrame({"date": g["date"], "ticker": g["ticker"]}, index=g.index)
    out["mom_12_1"] = px.shift(cfg.mom_skip) / px.shift(cfg.mom_long) - 1
    out["mom_6m"] = px / px.shift(cfg.mom_mid) - 1
    out["mom_3m"] = px / px.shift(cfg.mom_short) - 1
    out["trend_200"] = px / px.rolling(cfg.trend_window).mean() - 1
    out["vol_63"] = ret.rolling(cfg.vol_window, min_periods=cfg.vol_min_periods).std() * ann
    downside_sq = ret.clip(upper=0.0) ** 2
    out["downside_63"] = (
        np.sqrt(downside_sq.rolling(cfg.vol_window, min_periods=cfg.vol_min_periods).mean()) * ann
    )
    out["max_dd_252"] = rolling_max_drawdown(px, cfg.dd_window)
    if bench_px is not None:
        # Benchmark on the ticker's own sessions so both returns span the same interval.
        b = bench_px.reindex(g["date"]).to_numpy()
        bret = pd.Series(b, index=g.index).pct_change(fill_method=None)
        cov = ret.rolling(cfg.beta_window, min_periods=cfg.beta_min_periods).cov(bret)
        var = bret.rolling(cfg.beta_window, min_periods=cfg.beta_min_periods).var()
        out["beta_252"] = cov / var.where(var > 0)
    else:
        out["beta_252"] = np.nan
    dollar_vol = (g["close"] * g["volume"]).astype(float)
    out["adv_usd_60"] = dollar_vol.rolling(cfg.liq_window, min_periods=cfg.liq_min_periods).mean()
    illiq = ret.abs() / dollar_vol.where(dollar_vol > 0)
    out["amihud_60"] = illiq.rolling(cfg.liq_window, min_periods=cfg.liq_min_periods).mean() * 1e6
    adj = g["adj_close"].astype(float)
    close = g["close"].astype(float)
    total = adj / adj.shift(cfg.yield_window)
    price_only = close / close.shift(cfg.yield_window)
    out["trailing_yield_252"] = total / price_only - 1
    out["history_sessions"] = px.notna().cumsum().astype("int64")
    out["short_history"] = out["history_sessions"] < cfg.short_history_sessions
    return out


def compute_price_factors(
    prices: pd.DataFrame, benchmark: str = BENCHMARK, cfg: FactorConfig | None = None
) -> pd.DataFrame:
    """Long-format factors (``date``, ``ticker``, :data:`FACTOR_COLUMNS`) for every bar."""
    c = cfg or FactorConfig()
    cols = ["date", "ticker", *FACTOR_COLUMNS]
    if prices.empty:
        return pd.DataFrame(columns=cols)
    data = prices.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")
    bench = data[data["ticker"] == benchmark]
    bench_px = (
        pd.Series(price_for_returns(bench).to_numpy(), index=bench["date"])
        if not bench.empty
        else None
    )
    frames = [
        _ticker_factors(g.reset_index(drop=True), bench_px, c)
        for _, g in data.groupby("ticker", sort=True)
    ]
    return pd.concat(frames, ignore_index=True)[cols]


def _duration_estimates(
    ret: pd.Series, rows: pd.DataFrame, window: int, min_periods: int
) -> pd.Series:
    """Rolling duration estimate per pair date, from one vintage of yield observations.

    A value at pair date ``d`` depends only on pairs dated ``<= d`` (prefix property).
    """
    y = (
        rows.sort_values(["obs_date", "available_date"], kind="mergesort")
        .drop_duplicates("obs_date", keep="last")
        .set_index("obs_date")["value"]
    )
    dy = y.diff()
    pairs = pd.DataFrame({"ret": ret, "dy": dy.reindex(ret.index)}).dropna()
    cov = pairs["ret"].rolling(window, min_periods=min_periods).cov(pairs["dy"])
    var = pairs["dy"].rolling(window, min_periods=min_periods).var()
    return (-100 * cov / var.where(var > 0)).dropna()


def _lookup(est: pd.Series, bound: np.ndarray) -> np.ndarray:
    """Latest estimate dated ``<= bound`` (NaN where none or bound is NaT)."""
    pos = np.searchsorted(est.index.to_numpy(), bound, side="right") - 1
    vals = est.to_numpy()
    ok = (pos >= 0) & ~np.isnat(bound)
    return np.where(ok, vals[np.clip(pos, 0, None)] if len(vals) else np.nan, np.nan)


def compute_rate_duration(
    bars: pd.DataFrame,
    yields: pd.DataFrame,
    window: int = TRADING_DAYS,
    min_periods: int = 126,
) -> pd.DataFrame:
    """Empirical rate duration of one ticker vs a yield series (``rate_duration`` in years).

    ``duration = -100 × cov(r, Δy) / var(Δy)`` with Δy in percentage points, estimated on
    sessions where both the return and the yield change are observed.

    Point-in-time rule: the value on ``t`` is the latest estimate computed from the
    *vintage* of yields published by ``t`` (``available_date <= t``), using pairs up to
    the latest observation published by ``t``. It is therefore identical to recomputing
    from inputs truncated at ``t``, even when publication dates are not monotone in
    ``obs_date`` (an old observation published late, ADR 0003).

    Fast path: when every observation up to that latest one is already published, the
    vintage equals the full history on that prefix, so the full-history rolling estimate
    is reused. Only dates with an unpublished gap recompute on their own vintage.
    """
    rows = (
        yields.dropna(subset=["obs_date", "available_date", "value"])
        .astype({"obs_date": "datetime64[ns]", "available_date": "datetime64[ns]"})
        .astype({"value": float})[["obs_date", "available_date", "value"]]
        .sort_values(["available_date", "obs_date"], kind="mergesort")
        .reset_index(drop=True)
    )
    g = bars.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    dates = g["date"].to_numpy(dtype="datetime64[ns]")
    ret = pd.Series(price_for_returns(g).pct_change(fill_method=None).to_numpy(), index=dates)
    out = np.full(len(dates), np.nan)

    if not rows.empty and len(dates):
        # n_pub[i]: rows published by dates[i]; latest[i]: newest obs_date among them.
        n_pub = np.searchsorted(rows["available_date"].to_numpy(), dates, side="right")
        latest_by_pub = np.maximum.accumulate(rows["obs_date"].to_numpy())
        latest = np.where(
            n_pub > 0, latest_by_pub[np.clip(n_pub - 1, 0, None)], np.datetime64("NaT", "ns")
        )
        # complete_by(o): last publication date among observations dated <= o.
        by_obs = rows.sort_values("obs_date", kind="mergesort")
        obs_sorted = by_obs["obs_date"].to_numpy()
        complete = np.maximum.accumulate(by_obs["available_date"].to_numpy())
        idx = np.searchsorted(obs_sorted, latest, side="right") - 1
        has = n_pub > 0
        gap = has & (complete[np.clip(idx, 0, None)] > dates)
        bound = np.where(has, np.minimum(latest, dates), np.datetime64("NaT", "ns"))

        fast = has & ~gap
        if fast.any():
            est = _duration_estimates(ret, rows, window, min_periods)
            out[fast] = _lookup(est, bound[fast])
        for k in np.unique(n_pub[gap]):
            sel = gap & (n_pub == k)
            est = _duration_estimates(ret, rows.iloc[:k], window, min_periods)
            out[sel] = _lookup(est, bound[sel])

    return pd.DataFrame({"date": dates, "ticker": g["ticker"].to_numpy(), "rate_duration": out})

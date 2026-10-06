"""Rule-based macro regime: risk-on / neutral / risk-off (point-in-time).

Each component is a proxy for one aspect of the macro / market environment (VIX, credit,
curve, dollar, oil, gold, SPY trend, GDELT tone). It is turned into a stress score in
[-1, 1] by its percentile within its own *trailing* history (``rolling(...).rank``), so
no future observation can move today's score. The composite stress is the weighted mean
of the available components, smoothed with a causal EWM; thresholds map it to a label.

"International situation" signals (oil, gold, dollar, GDELT tone) are proxies, not a
measurement of geopolitics itself — see docs/adr/0003-features-and-regime.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qrd.features.factors import price_for_returns

RISK_ON = "risk_on"
NEUTRAL = "neutral"
RISK_OFF = "risk_off"
UNKNOWN = "unknown"
REGIMES = (RISK_ON, NEUTRAL, RISK_OFF, UNKNOWN)

MOMENTUM_WINDOW = 63
TREND_WINDOW = 200


@dataclass(frozen=True)
class RegimeComponent:
    name: str
    direction: int  # +1: higher input = more stress; -1: lower input = more stress
    weight: float
    min_periods: int = 252
    description: str = ""


DEFAULT_COMPONENTS: tuple[RegimeComponent, ...] = (
    RegimeComponent("vix", +1, 1.0, description="VIX level"),
    RegimeComponent("hy_oas", +1, 1.0, description="High-yield OAS level (FRED, ~3y only)"),
    RegimeComponent("credit_proxy", -1, 1.0, description="HYG vs IEF 63-session log return"),
    RegimeComponent("spy_trend", -1, 1.0, description="SPY vs 200-session SMA"),
    RegimeComponent("curve", -1, 0.5, description="10y−2y Treasury spread"),
    RegimeComponent("usd_mom", +1, 0.5, description="Broad USD 63-session log change"),
    RegimeComponent("oil_mom", +1, 0.5, description="WTI 63-session log change (oil shock)"),
    RegimeComponent("gold_mom", +1, 0.5, description="Gold 63-session log change (haven bid)"),
    RegimeComponent("gdelt_economy", -1, 0.25, min_periods=60, description="GDELT economy tone"),
    RegimeComponent(
        "gdelt_geopolitics", -1, 0.25, min_periods=60, description="GDELT geopolitics tone"
    ),
)


@dataclass(frozen=True)
class RegimeConfig:
    components: tuple[RegimeComponent, ...] = field(default=DEFAULT_COMPONENTS)
    pct_window: int = 756  # ~3 years of sessions
    smooth_span: int = 5
    risk_off_threshold: float = 0.25
    risk_on_threshold: float = -0.25
    min_components: int = 3


def _log_change(s: pd.Series, window: int) -> pd.Series:
    logged = pd.Series(np.log(s.where(s > 0)), index=s.index)
    return logged - logged.shift(window)


def _calendar_px(prices: pd.DataFrame, ticker: str, calendar: pd.DatetimeIndex) -> pd.Series:
    bars = prices[prices["ticker"] == ticker].sort_values("date")
    if bars.empty:
        return pd.Series(np.nan, index=calendar)
    px = pd.Series(price_for_returns(bars).to_numpy(), index=bars["date"])
    px = px[~px.index.duplicated(keep="last")]
    return px.reindex(calendar).ffill(limit=3)  # bridge a few missing sessions, not more


def regime_inputs(panel: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Raw component inputs on the panel's calendar (each value uses data <= its date)."""
    cal = pd.DatetimeIndex(panel.index)

    def col(name: str) -> pd.Series:
        return panel[name] if name in panel else pd.Series(np.nan, index=cal)

    spy = _calendar_px(prices, "SPY", cal)
    hyg = _calendar_px(prices, "HYG", cal)
    ief = _calendar_px(prices, "IEF", cal)
    out = pd.DataFrame(index=cal)
    out["vix"] = col("vix")
    out["hy_oas"] = col("hy_oas")
    out["credit_proxy"] = _log_change(hyg, MOMENTUM_WINDOW) - _log_change(ief, MOMENTUM_WINDOW)
    out["spy_trend"] = spy / spy.rolling(TREND_WINDOW).mean() - 1
    out["curve"] = col("curve_10y2y")
    out["usd_mom"] = _log_change(col("usd_broad"), MOMENTUM_WINDOW)
    out["oil_mom"] = _log_change(col("wti"), MOMENTUM_WINDOW)
    out["gold_mom"] = _log_change(col("gold"), MOMENTUM_WINDOW)
    out["gdelt_economy"] = col("gdelt_tone_economy")
    out["gdelt_geopolitics"] = col("gdelt_tone_geopolitics")
    out.index.name = "date"
    return out.astype(np.float64)


def trailing_percentile(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Percentile rank of each value within its trailing window (NaN until min_periods)."""
    valid = s.dropna()
    pct = valid.rolling(window, min_periods=min_periods).rank(pct=True)
    return pct.reindex(s.index)


def classify_regime(inputs: pd.DataFrame, cfg: RegimeConfig | None = None) -> pd.DataFrame:
    """Per-date ``stress_score``, ``regime`` label, component count and contributions.

    ``contrib_<name>`` columns sum to ``stress_raw``; ``stress_score`` is its causal EWM.
    """
    c = cfg or RegimeConfig()
    scores = {}
    for comp in c.components:
        raw = inputs[comp.name] if comp.name in inputs else pd.Series(np.nan, index=inputs.index)
        pct = trailing_percentile(raw, c.pct_window, comp.min_periods)
        scores[comp.name] = comp.direction * (2 * pct - 1)
    score = pd.DataFrame(scores, index=inputs.index)
    weights = pd.Series({comp.name: comp.weight for comp in c.components})
    available = score.notna()
    weight_sum = available.mul(weights, axis=1).sum(axis=1)
    weighted = score.mul(weights, axis=1)
    n_components = available.sum(axis=1).astype("int64")
    ok = n_components >= c.min_components

    out = pd.DataFrame(index=inputs.index)
    contrib = weighted.div(weight_sum.where(ok), axis=0)
    out["stress_raw"] = contrib.sum(axis=1, min_count=1).where(ok)
    out["stress_score"] = out["stress_raw"].ewm(span=c.smooth_span, ignore_na=True).mean()
    out.loc[~ok, "stress_score"] = np.nan
    out["n_components"] = n_components
    labels = np.where(
        out["stress_score"] >= c.risk_off_threshold,
        RISK_OFF,
        np.where(out["stress_score"] <= c.risk_on_threshold, RISK_ON, NEUTRAL),
    )
    out["regime"] = pd.Series(labels, index=out.index).where(ok, UNKNOWN).astype(str)
    for name in score.columns:
        out[f"contrib_{name}"] = contrib[name]
    out.index.name = "date"
    return out

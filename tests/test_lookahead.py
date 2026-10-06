"""Look-ahead tests for the whole feature stage (SYNTHETIC FIXTURE data only).

Property: for any cutoff ``t``, features built from point-in-time inputs (bars dated
``<= t``, macro *available* ``<= t``) equal the full-history features on every date
``<= t``. A second test replaces all future data with garbage. Canary tests show the
checker really fails on a leaky implementation, so the property tests are not vacuous.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qrd.features.build import FeatureSet, build_features, point_in_time
from qrd.features.factors import compute_price_factors
from qrd.features.macro import macro_panel
from qrd.features.regime import RegimeComponent, RegimeConfig
from tests.helpers import make_bars

N = 700
START = "2022-01-03"
TICKERS = {
    "SPY": ("equity_etf", "broad_market", 1),
    "HYG": ("bond_etf", "corporate_hy", 1),
    "IEF": ("bond_etf", "treasury_intermediate", 1),
    "TLT": ("bond_etf", "treasury_long", 1),
    "AAA": ("equity", "information_technology", 1),
    "SSO": ("equity_etf", "leveraged_equity", 2),
}
# lags in business days, mirroring MACRO_SPECS; gdelt mimics next-day availability
MACRO = {
    "vix": 1,
    "hy_oas": 1,
    "curve_10y2y": 1,
    "ust_10y": 1,
    "usd_broad": 7,
    "wti": 7,
    "gold": 0,
    "gdelt_tone_economy": 1,
}
# Short warm-ups so the 700-session fixture exercises every component.
REGIME_CFG = RegimeConfig(
    components=tuple(
        RegimeComponent(name, d, 1.0, min_periods=40)
        for name, d in [
            ("vix", 1),
            ("hy_oas", 1),
            ("credit_proxy", -1),
            ("spy_trend", -1),
            ("curve", -1),
            ("usd_mom", 1),
            ("oil_mom", 1),
            ("gold_mom", 1),
            ("gdelt_economy", -1),
        ]
    ),
    pct_window=250,
)
CUTOFF_POSITIONS = [260, 420, 555, N - 2]
# ust_10y observation 380 is published at session 470: cutoff 420 sits inside the gap.
LATE_OBS, LATE_OBS_PUBLISHED = 380, 470


def _universe() -> pd.DataFrame:
    rows = [(t, *meta, "etf") for t, meta in TICKERS.items()]
    return pd.DataFrame(
        rows, columns=["ticker", "asset_class", "category", "leverage", "instrument"]
    )


def _prices() -> pd.DataFrame:
    frames = []
    for i, t in enumerate(TICKERS):
        df = make_bars(t, start=START, periods=N, seed=i + 10)
        if t == "AAA":  # late listing + a missing session
            df = df.iloc[150:].drop(df.index[300])
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _observations() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    frames = []
    for series, lag in MACRO.items():
        dates = pd.bdate_range(START, periods=N + 10)
        if series in {"usd_broad", "wti"}:
            dates = dates[dates.dayofweek == 4]  # weekly
        values = 50 + np.cumsum(rng.normal(0, 1, len(dates)))
        if series == "hy_oas":  # history starts late (FRED license window)
            dates, values = dates[300:], values[300:]
        available = pd.Series(dates + pd.offsets.BDay(lag))
        if series == "ust_10y":  # non-monotone publication: an old print released late
            available[LATE_OBS] = dates[LATE_OBS_PUBLISHED]
        frames.append(
            pd.DataFrame(
                {
                    "obs_date": dates,
                    "available_date": available.to_numpy(),
                    "series": series,
                    "value": values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _build(prices: pd.DataFrame, obs: pd.DataFrame) -> FeatureSet:
    return build_features(prices, obs, _universe(), regime_cfg=REGIME_CFG)


def _upto(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    if "date" in df.columns:
        return df[df["date"] <= t].sort_values(["date", "ticker"]).reset_index(drop=True)
    return df.loc[:t]


def _assert_same_until(full: FeatureSet, part: FeatureSet, t: pd.Timestamp) -> None:
    pd.testing.assert_frame_equal(_upto(full.factors, t), _upto(part.factors, t))
    pd.testing.assert_frame_equal(_upto(full.panel, t), _upto(part.panel, t))
    pd.testing.assert_frame_equal(_upto(full.regime, t), _upto(part.regime, t))


@pytest.fixture(scope="module")
def full() -> FeatureSet:
    return _build(_prices(), _observations())


def _cutoffs() -> list[pd.Timestamp]:
    cal = pd.bdate_range(START, periods=N)
    return [cal[i] for i in CUTOFF_POSITIONS]


def test_fixture_exercises_features(full: FeatureSet) -> None:
    """Guard against a vacuous test: late cutoffs must have real values everywhere."""
    t = _cutoffs()[-1]
    snap = full.factors[full.factors["date"] == t]
    cols = ["mom_12_1", "trend_200", "max_dd_252", "beta_252", "rate_duration"]
    assert snap[cols].notna().all().all()
    reg = full.regime.loc[t]
    assert reg["regime"] != "unknown"
    assert reg["n_components"] == 9
    assert full.regime.loc[: _cutoffs()[0], "contrib_hy_oas"].isna().all()


@pytest.mark.parametrize("pos", CUTOFF_POSITIONS)
def test_truncating_future_data_does_not_change_past(full: FeatureSet, pos: int) -> None:
    t = pd.bdate_range(START, periods=N)[pos]
    prices, obs = point_in_time(_prices(), _observations(), t)
    _assert_same_until(full, _build(prices, obs), t)


@pytest.mark.parametrize("pos", CUTOFF_POSITIONS[:2])
def test_corrupting_future_data_does_not_change_past(full: FeatureSet, pos: int) -> None:
    t = pd.bdate_range(START, periods=N)[pos]
    rng = np.random.default_rng(1)
    prices = _prices()
    future = prices["date"] > t
    for col in ("open", "high", "low", "close", "adj_close"):
        prices.loc[future, col] *= rng.uniform(0.2, 5.0, future.sum())
    prices.loc[future, "volume"] = 0.0
    obs = _observations()
    late = obs["available_date"] > t  # includes obs dated <= t but published after t
    obs.loc[late, "value"] = 1e6
    _assert_same_until(full, _build(prices, obs), t)


# --- canaries: the checker must catch real leaks -----------------------------------------


def test_canary_obs_date_join_is_detected() -> None:
    t = pd.bdate_range(START, periods=N)[400]
    obs = _observations()
    cal = pd.bdate_range(START, periods=N)
    leaky = obs.assign(available_date=obs["obs_date"])  # joining on obs_date = look-ahead
    _, pit = point_in_time(_prices(), obs, t)
    full_panel = macro_panel(leaky, cal).loc[:t]
    pit_panel = macro_panel(pit.assign(available_date=pit["obs_date"]), cal).loc[:t]
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(full_panel, pit_panel)


def test_canary_centered_window_is_detected() -> None:
    t = pd.bdate_range(START, periods=N)[400]
    prices = _prices()

    def leaky(p: pd.DataFrame) -> pd.DataFrame:
        f = compute_price_factors(p)
        f["trend_200"] = f.groupby("ticker")["mom_3m"].transform(
            lambda s: s.rolling(21, center=True).mean()
        )
        return f

    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(
            _upto(leaky(prices), t), _upto(leaky(prices[prices["date"] <= t]), t)
        )

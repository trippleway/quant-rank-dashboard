"""Unit tests for per-ticker price factors (SYNTHETIC FIXTURE data only)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from qrd.features.factors import (
    FACTOR_COLUMNS,
    compute_price_factors,
    compute_rate_duration,
    rolling_max_drawdown,
)
from tests.helpers import make_bars


def _bars_from_close(ticker: str, close: np.ndarray, start: str = "2020-01-01") -> pd.DataFrame:
    df = make_bars(ticker, start=start, periods=len(close))
    df["close"] = close
    df["adj_close"] = close
    df["open"] = close
    df["high"] = close
    df["low"] = close
    return df


def _last(factors: pd.DataFrame, ticker: str) -> pd.Series:
    return factors[factors["ticker"] == ticker].iloc[-1]


def test_momentum_and_trend_exact_on_geometric_path() -> None:
    g = 0.001
    close = 100 * np.exp(g * np.arange(300))
    f = compute_price_factors(_bars_from_close("SPY", close))
    last = _last(f, "SPY")
    assert last["mom_3m"] == pytest.approx(math.exp(g * 63) - 1)
    assert last["mom_6m"] == pytest.approx(math.exp(g * 126) - 1)
    # 12-1: from t-252 to t-21
    assert last["mom_12_1"] == pytest.approx(math.exp(g * (252 - 21)) - 1)
    sma = close[-200:].mean()
    assert last["trend_200"] == pytest.approx(close[-1] / sma - 1)
    # constant log growth → zero volatility / no downside / no drawdown
    assert last["vol_63"] == pytest.approx(0.0, abs=1e-9)
    assert last["downside_63"] == pytest.approx(0.0, abs=1e-12)
    assert last["max_dd_252"] == pytest.approx(0.0, abs=1e-12)


def test_insufficient_history_is_nan_not_zero() -> None:
    f = compute_price_factors(make_bars("SPY", periods=100))
    last = _last(f, "SPY")
    for col in ("mom_12_1", "mom_6m", "trend_200", "max_dd_252", "beta_252"):
        assert math.isnan(last[col]), col
    assert not math.isnan(last["mom_3m"])
    assert last["history_sessions"] == 100
    assert bool(last["short_history"])


def test_beta_recovers_leverage_against_benchmark() -> None:
    spy = make_bars("SPY", periods=400, seed=1)
    ret = spy["adj_close"].pct_change().fillna(0.0).to_numpy()
    lev_close = 50 * np.cumprod(1 + 2 * ret)
    lev = _bars_from_close("SSO", lev_close, start="2024-01-02")
    lev["date"] = spy["date"].to_numpy()
    f = compute_price_factors(pd.concat([spy, lev]))
    assert _last(f, "SSO")["beta_252"] == pytest.approx(2.0, rel=1e-9)
    assert _last(f, "SPY")["beta_252"] == pytest.approx(1.0, rel=1e-9)


def test_rolling_max_drawdown_only_counts_peaks_inside_window() -> None:
    # peak 100 → trough 50 early; later recovers to 80 and slides to 60.
    px = np.r_[np.full(5, 100.0), np.full(5, 50.0), np.full(5, 80.0), np.full(5, 60.0)]
    dd = rolling_max_drawdown(pd.Series(px), window=10)
    assert dd.iloc[9] == pytest.approx(-0.5)  # window [0, 9] contains the 100 → 50 fall
    # window [10, 19]: peak 80 → 60 only; the old 100 peak is outside the window
    assert dd.iloc[19] == pytest.approx(60 / 80 - 1)
    assert dd.iloc[:9].isna().all()


def test_liquidity_and_trailing_yield() -> None:
    bars = make_bars("XYZ", periods=300, price=20.0, volume=500_000.0)
    # Simulate a 3% dividend inside the trailing year: adj_close history before the
    # ex-date is scaled down by the dividend factor (Yahoo convention).
    bars["close"] = 20.0
    bars["adj_close"] = 20.0
    bars.loc[: 200 - 1, "adj_close"] = 20.0 * 0.97
    bars["open"] = bars["high"] = bars["low"] = 20.0
    f = compute_price_factors(bars)
    last = _last(f, "XYZ")
    assert last["adv_usd_60"] == pytest.approx(20.0 * 500_000.0)
    assert last["trailing_yield_252"] == pytest.approx(1 / 0.97 - 1)
    assert last["amihud_60"] == pytest.approx(0.0, abs=1e-15)


def test_adj_close_missing_falls_back_to_close() -> None:
    bars = make_bars("ABC", periods=100)
    bars["adj_close"] = np.nan
    last = _last(compute_price_factors(bars), "ABC")
    expected = bars["close"].iloc[-1] / bars["close"].iloc[-1 - 63] - 1
    assert last["mom_3m"] == pytest.approx(expected)
    assert math.isnan(last["trailing_yield_252"])  # no dividend information


def test_output_schema() -> None:
    f = compute_price_factors(pd.concat([make_bars("SPY"), make_bars("AAA", seed=3)]))
    assert list(f.columns) == ["date", "ticker", *FACTOR_COLUMNS]
    assert set(f["ticker"]) == {"SPY", "AAA"}
    assert not f.duplicated(["date", "ticker"]).any()


def _yield_obs(dates: pd.DatetimeIndex, values: np.ndarray, lag: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "obs_date": dates,
            "available_date": dates + pd.offsets.BDay(lag),
            "series": "ust_10y",
            "value": values,
        }
    )


def test_rate_duration_recovers_known_duration() -> None:
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2023-01-02", periods=400)
    dy = rng.normal(0, 0.05, len(dates))  # pp
    y = 4 + np.cumsum(dy)
    ret = -7.0 * np.r_[0.0, np.diff(y)] / 100
    bars = _bars_from_close("IEF", 100 * np.cumprod(1 + ret), start="2023-01-02")
    dur = compute_rate_duration(bars, _yield_obs(dates, y))
    assert dur.iloc[-1]["rate_duration"] == pytest.approx(7.0, rel=1e-6)


def test_rate_duration_respects_available_date() -> None:
    rng = np.random.default_rng(8)
    dates = pd.bdate_range("2023-01-02", periods=300)
    y = 4 + np.cumsum(rng.normal(0, 0.05, len(dates)))
    bars = make_bars("IEF", start="2023-01-02", periods=300)
    lag5 = compute_rate_duration(bars, _yield_obs(dates, y, lag=5)).set_index("date")
    lag1 = compute_rate_duration(bars, _yield_obs(dates, y, lag=1)).set_index("date")
    # The value usable on day t with a 5-day publication lag equals the 1-day-lag value
    # from 4 sessions earlier: the estimate only advances when the yield is published.
    t = dates[-1]
    assert lag5.loc[t, "rate_duration"] == pytest.approx(lag1.loc[dates[-5], "rate_duration"])


def _pit_duration(bars: pd.DataFrame, obs: pd.DataFrame, t: pd.Timestamp) -> float:
    pit = compute_rate_duration(bars[bars["date"] <= t], obs[obs["available_date"] <= t])
    return float(pit.loc[pit["date"] == t, "rate_duration"].to_numpy()[-1])


def test_rate_duration_non_monotone_publication_has_no_lookahead() -> None:
    """An old observation published late must not leak into estimates before it is out."""
    rng = np.random.default_rng(9)
    dates = pd.bdate_range("2023-01-02", periods=280)
    y = 4 + np.cumsum(rng.normal(0, 0.05, len(dates)))
    ret = -7.0 * np.r_[0.0, np.diff(y)] / 100
    bars = _bars_from_close("IEF", 100 * np.cumprod(1 + ret), start="2023-01-02")
    obs = _yield_obs(dates, y)
    obs.loc[150, "available_date"] = dates[260]  # obs 151 published ~5 months late
    obs.loc[150, "value"] = y[150] + 3.0  # and it is a large move (outlier)
    full = compute_rate_duration(bars, obs).set_index("date")["rate_duration"]
    for i in [150, 151, 152, 200, 221, 259, 260, 261, 279]:
        t = dates[i]
        assert full.loc[t] == _pit_duration(bars, obs, t), f"leak at session {i}"
    # Before publication, the outlier is invisible; after, it moves the estimate.
    assert full.loc[dates[221]] == pytest.approx(7.0, rel=0.05)
    assert full.loc[dates[261]] != pytest.approx(7.0, rel=0.05)


def test_rate_duration_matches_point_in_time_on_every_date() -> None:
    rng = np.random.default_rng(10)
    dates = pd.bdate_range("2023-01-02", periods=220)
    y = 4 + np.cumsum(rng.normal(0, 0.05, len(dates)))
    bars = make_bars("TLT", start="2023-01-02", periods=220)
    obs = _yield_obs(dates, y)
    obs["available_date"] += pd.to_timedelta(rng.integers(0, 4, len(obs)) * 7, unit="D")
    full = compute_rate_duration(bars, obs, min_periods=60).set_index("date")["rate_duration"]
    for t in dates[60::4]:
        pit = compute_rate_duration(
            bars[bars["date"] <= t], obs[obs["available_date"] <= t], min_periods=60
        )
        expected = pit.set_index("date").loc[t, "rate_duration"]
        assert full.loc[t] == expected or (pd.isna(full.loc[t]) and pd.isna(expected))
    assert full.loc[dates[100:]].notna().all()

"""Macro panel and regime tests (SYNTHETIC FIXTURE data only)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qrd.features.macro import macro_panel
from qrd.features.regime import (
    NEUTRAL,
    RISK_OFF,
    RISK_ON,
    UNKNOWN,
    RegimeComponent,
    RegimeConfig,
    classify_regime,
    trailing_percentile,
)


def _obs(series: str, obs: list[str], values: list[float], lag: int) -> pd.DataFrame:
    d = pd.DatetimeIndex(obs)
    return pd.DataFrame(
        {
            "obs_date": d,
            "available_date": d + pd.offsets.BDay(lag),
            "series": series,
            "value": values,
        }
    )


def test_panel_uses_available_date_not_obs_date() -> None:
    cal = pd.bdate_range("2024-01-01", periods=6)  # Mon..Mon
    obs = _obs("vix", ["2024-01-01", "2024-01-02", "2024-01-03"], [10.0, 20.0, 30.0], lag=1)
    panel = macro_panel(obs, cal)
    assert np.isnan(panel.loc["2024-01-01", "vix"])  # Monday's value is published Tuesday
    assert panel.loc["2024-01-02", "vix"] == 10.0
    assert panel.loc["2024-01-03", "vix"] == 20.0
    assert panel.loc["2024-01-04", "vix"] == 30.0
    assert panel.loc["2024-01-08", "vix"] == 30.0  # carried while fresh


def test_panel_weekly_series_with_long_lag() -> None:
    cal = pd.bdate_range("2024-01-01", periods=15)
    obs = _obs("usd_broad", ["2024-01-05"], [120.0], lag=7)  # available 2024-01-16
    panel = macro_panel(obs, cal)
    assert panel.loc[:"2024-01-15", "usd_broad"].isna().all()
    assert panel.loc["2024-01-16", "usd_broad"] == 120.0


def test_panel_drops_stale_observations() -> None:
    cal = pd.bdate_range("2024-01-01", periods=30)
    obs = _obs("vix", ["2024-01-01"], [15.0], lag=1)
    panel = macro_panel(obs, cal, max_age_days=14)
    assert panel.loc["2024-01-15", "vix"] == 15.0
    assert np.isnan(panel.loc["2024-01-16", "vix"])  # source died: NaN, not frozen


def test_panel_ignores_missing_values_and_late_revisions_of_old_obs() -> None:
    cal = pd.bdate_range("2024-01-01", periods=5)
    obs = pd.concat(
        [
            _obs("vix", ["2024-01-02"], [np.nan], lag=1),  # FRED "." holiday
            _obs("vix", ["2024-01-01"], [11.0], lag=1),
            # an old observation that only becomes available later must not replace newer data
            _obs("vix", ["2024-01-03", "2024-01-01"], [13.0, 99.0], lag=1).assign(
                available_date=pd.to_datetime(["2024-01-04", "2024-01-05"])
            ),
        ]
    )
    panel = macro_panel(obs, cal)
    assert panel.loc["2024-01-03", "vix"] == 11.0
    assert panel.loc["2024-01-05", "vix"] == 13.0


def test_trailing_percentile_is_backward_only() -> None:
    s = pd.Series([1.0, 2.0, 3.0, np.nan, 0.5])
    pct = trailing_percentile(s, window=10, min_periods=2)
    assert np.isnan(pct.iloc[0])
    assert pct.iloc[2] == pytest.approx(1.0)  # max so far
    assert np.isnan(pct.iloc[3])
    assert pct.iloc[4] == pytest.approx(0.25)  # lowest of 4 valid values


CFG = RegimeConfig(
    components=(
        RegimeComponent("vix", +1, 1.0, min_periods=50),
        RegimeComponent("spy_trend", -1, 1.0, min_periods=50),
        RegimeComponent("credit_proxy", -1, 1.0, min_periods=50),
        RegimeComponent("hy_oas", +1, 1.0, min_periods=50),
    ),
    pct_window=200,
    smooth_span=1,
    min_components=3,
)


def _inputs(n: int, shock: float) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2022-01-03", periods=n, name="date")
    base = pd.DataFrame(
        {
            "vix": 18 + rng.normal(0, 1, n),
            "spy_trend": 0.02 + rng.normal(0, 0.01, n),
            "credit_proxy": rng.normal(0, 0.01, n),
            "hy_oas": np.nan,  # pre-2023: not available from FRED
        },
        index=idx,
    )
    base.iloc[-5:, 0] += 15 * shock
    base.iloc[-5:, 1] -= 0.10 * shock
    base.iloc[-5:, 2] -= 0.05 * shock
    return base


def test_stress_shock_is_risk_off_and_calm_drop_is_risk_on() -> None:
    off = classify_regime(_inputs(300, shock=1.0), CFG)
    assert off["regime"].iloc[-1] == RISK_OFF
    assert off["n_components"].iloc[-1] == 3  # hy_oas missing → others reweighted
    on = classify_regime(_inputs(300, shock=-1.0), CFG)
    assert on["regime"].iloc[-1] == RISK_ON
    mid = classify_regime(_inputs(300, shock=0.0), CFG)
    assert mid["regime"].iloc[-1] in {NEUTRAL, RISK_ON, RISK_OFF}
    assert -1.0 <= mid["stress_score"].iloc[-1] <= 1.0


def test_contributions_sum_to_raw_stress() -> None:
    reg = classify_regime(_inputs(300, shock=1.0), CFG)
    contrib = reg.filter(like="contrib_").sum(axis=1, min_count=1)
    valid = reg["stress_raw"].notna()
    assert valid.any()
    np.testing.assert_allclose(contrib[valid], reg.loc[valid, "stress_raw"])
    assert np.isnan(reg["contrib_hy_oas"]).all()


def test_too_few_components_is_unknown() -> None:
    inputs = _inputs(300, shock=1.0)
    inputs["credit_proxy"] = np.nan
    reg = classify_regime(inputs, CFG)
    assert (reg["regime"] == UNKNOWN).all()
    assert reg["stress_score"].isna().all()


def test_warmup_is_unknown() -> None:
    reg = classify_regime(_inputs(300, shock=0.0), CFG)
    assert (reg["regime"].iloc[:49] == UNKNOWN).all()
    assert (reg["regime"].iloc[60:] != UNKNOWN).all()

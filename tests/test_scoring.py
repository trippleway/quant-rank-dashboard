"""Cross-sectional scoring: normalisation, regime weights, missing data, penalties, explanations.

All inputs are SYNTHETIC FIXTURE snapshots built in this file.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from qrd.scoring.composite import normalize, score_cross_section, winsorized_z
from qrd.scoring.config import (
    DURATION,
    GROUPS,
    MOMENTUM,
    NormalizationConfig,
    ScoringConfig,
)
from qrd.scoring.explain import main_risks, top_reasons

FACTORS = {
    "mom_12_1": 0.10,
    "mom_6m": 0.05,
    "mom_3m": 0.02,
    "trend_200": 0.03,
    "vol_63": 0.20,
    "downside_63": 0.14,
    "max_dd_252": -0.12,
    "beta_252": 1.0,
    "adv_usd_60": 5e8,
    "amihud_60": 0.001,
    "trailing_yield_252": 0.015,
    "rate_duration": 0.5,
    "history_sessions": 1000,
    "short_history": False,
}


def snapshot(
    n: int = 30, seed: int = 0, overrides: dict[str, dict[str, Any]] | None = None
) -> pd.DataFrame:
    """FIXTURE cross-section: ``n`` equities with random factor values, plus overrides."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        row: dict[str, object] = {
            "ticker": f"T{i:02d}",
            "asset_class": "equity",
            "category": "information_technology",
            "leverage": 1.0,
        }
        for k, v in FACTORS.items():
            row[k] = v * (1 + rng.normal(0, 0.5)) if isinstance(v, float) else v
        rows.append(row)
    df = pd.DataFrame(rows)
    for ticker, values in (overrides or {}).items():
        mask = df["ticker"] == ticker
        if not mask.any():
            df = pd.concat([df, pd.DataFrame([{**df.iloc[0].to_dict(), "ticker": ticker}])])
            mask = df["ticker"] == ticker
        for k, v in values.items():
            df.loc[mask, k] = v
    return df.reset_index(drop=True)


def val(df: pd.DataFrame, ticker: str, column: str) -> float:
    return float(df[column].loc[ticker])


# --- normalisation -----------------------------------------------------------------------


def test_winsorized_z_clips_outliers_and_keeps_nan() -> None:
    v = pd.Series([*np.arange(1.0, 40.0), 1000.0, np.nan])
    z = winsorized_z(v, 0.05, 0.95)
    assert np.isnan(z.iloc[-1])
    assert z.dropna().mean() == pytest.approx(0.0, abs=1e-12)
    assert z.dropna().std(ddof=0) == pytest.approx(1.0)
    # the outlier is clipped to the 95th percentile, so it is not 3 sigma away
    assert z.iloc[-2] < 2.0
    assert z.iloc[-2] == pytest.approx(z.iloc[-3])  # 1000 and 39 both clipped to p95


def test_winsorized_z_degenerate_inputs() -> None:
    assert winsorized_z(pd.Series([5.0, 5.0, np.nan]), 0.05, 0.95).tolist()[:2] == [0.0, 0.0]
    single = winsorized_z(pd.Series([np.nan, 3.0]), 0.05, 0.95)
    assert np.isnan(single.iloc[0])
    assert single.iloc[1] == 0.0


def test_normalize_blends_within_class_and_pooled() -> None:
    # bonds have low values, equities high: within-class z ranks inside each class
    values = pd.Series([1.0, 2, 3, 4, 5, 10, 11, 12, 13, 14])
    groups = pd.Series(["bond"] * 5 + ["equity"] * 5)
    cfg = NormalizationConfig(lower_pct=0.0, upper_pct=1.0, group_blend=1.0)
    within = normalize(values, groups, cfg)
    assert within.iloc[4] == pytest.approx(within.iloc[9])  # best of each class equal
    pooled = normalize(values, groups, NormalizationConfig(0.0, 1.0, group_blend=0.0))
    assert pooled.iloc[4] < pooled.iloc[5]
    half = normalize(values, groups, NormalizationConfig(0.0, 1.0, group_blend=0.5))
    np.testing.assert_allclose(half, 0.5 * within + 0.5 * pooled)


def test_normalize_small_class_falls_back_to_pooled() -> None:
    values = pd.Series([1.0, 2, 3, 4, 5, 6, 100.0, 101.0])
    groups = pd.Series(["equity"] * 6 + ["vix"] * 2)
    cfg = NormalizationConfig(lower_pct=0.0, upper_pct=1.0, min_group_size=5, group_blend=1.0)
    z = normalize(values, groups, cfg)
    pooled = winsorized_z(values, 0.0, 1.0)
    assert z.iloc[6] == pytest.approx(pooled.iloc[6])  # 2-member class: pooled only
    assert z.iloc[6] != pytest.approx(-z.iloc[7])  # would be ±1 if normalised within


# --- composite ---------------------------------------------------------------------------


def test_contributions_sum_to_composite() -> None:
    out = score_cross_section(snapshot(), "neutral")
    contrib = out[[c for c in out.columns if c.startswith("contrib_")]].sum(axis=1)
    np.testing.assert_allclose(contrib, out["composite"], atol=1e-12)
    np.testing.assert_allclose(out["score"], out["composite"] - out["risk_penalty"])


def test_better_momentum_ranks_higher_all_else_equal() -> None:
    snap = snapshot()
    base = snap.iloc[0].to_dict()
    strong = {**base, "ticker": "STRONG", "mom_12_1": 0.6, "mom_6m": 0.3, "mom_3m": 0.15}
    weak = {**base, "ticker": "WEAK", "mom_12_1": -0.3, "mom_6m": -0.2, "mom_3m": -0.1}
    snap = pd.concat([snap, pd.DataFrame([strong, weak])], ignore_index=True)
    out = score_cross_section(snap, "neutral").set_index("ticker")
    assert val(out, "STRONG", "score") > val(out, "WEAK", "score")
    assert val(out, "STRONG", "contrib_mom_12_1") > 0 > val(out, "WEAK", "contrib_mom_12_1")


def test_regime_changes_weights_and_ordering() -> None:
    """Momentum-heavy risk-on vs defensive risk-off must reorder a high-mom/high-vol pair."""
    snap = snapshot(n=40)
    base = snap.iloc[0].to_dict()
    racer = {
        **base,
        "ticker": "RACER",
        "mom_12_1": 0.8,
        "mom_6m": 0.4,
        "mom_3m": 0.2,
        "trend_200": 0.15,
        "vol_63": 0.38,
        "downside_63": 0.28,
        "max_dd_252": -0.30,
        "beta_252": 1.6,
    }
    steady = {
        **base,
        "ticker": "STEADY",
        "mom_12_1": 0.12,
        "mom_6m": 0.06,
        "mom_3m": 0.03,
        "trend_200": 0.03,
        "vol_63": 0.10,
        "downside_63": 0.06,
        "max_dd_252": -0.05,
        "beta_252": 0.4,
    }
    snap = pd.concat([snap, pd.DataFrame([racer, steady])], ignore_index=True)
    on = score_cross_section(snap, "risk_on").set_index("ticker")
    off = score_cross_section(snap, "risk_off").set_index("ticker")
    assert val(on, "RACER", "score") > val(on, "STEADY", "score")
    assert val(off, "RACER", "score") < val(off, "STEADY", "score")
    cfg = ScoringConfig()
    assert cfg.weights_for("risk_on")[MOMENTUM] > cfg.weights_for("risk_off")[MOMENTUM]


def test_unknown_regime_uses_neutral_weights() -> None:
    snap = snapshot()
    pd.testing.assert_frame_equal(
        score_cross_section(snap, "unknown"), score_cross_section(snap, "neutral")
    )


def test_missing_factors_are_downweighted_not_zero() -> None:
    """A missing group drops out and the rest is renormalised (no implicit 0 / median)."""
    snap = snapshot(n=40)
    no_mom = {"mom_12_1": np.nan, "mom_6m": np.nan, "mom_3m": np.nan, "trend_200": np.nan}
    snap.loc[snap["ticker"] == "T00", list(no_mom)] = np.nan
    out = score_cross_section(snap, "neutral").set_index("ticker")
    row = out.loc["T00"]
    w = ScoringConfig().weights_for("neutral")
    assert np.isnan(row["grp_momentum"])
    assert row["coverage"] == pytest.approx(1 - w[MOMENTUM] / sum(abs(v) for v in w.values()))
    assert row["contrib_mom_12_1"] == 0.0
    # renormalised: the composite equals the weighted mean of the remaining groups
    rest = [g for g in GROUPS if g not in (MOMENTUM, DURATION) and w[g]]
    expected = sum(w[g] * row[f"grp_{g}"] for g in rest) / sum(w[g] for g in rest)
    assert row["composite"] == pytest.approx(expected)
    # a single missing factor inside a group: the group mean uses the others
    snap2 = snapshot(n=40)
    snap2.loc[snap2["ticker"] == "T01", "beta_252"] = np.nan
    r2 = score_cross_section(snap2, "neutral").set_index("ticker").loc["T01"]
    z = [r2["z_vol_63"], r2["z_downside_63"], r2["z_max_dd_252"]]
    assert r2["grp_low_risk"] == pytest.approx(np.mean(z))
    assert r2["coverage"] == 1.0


def test_duration_tilt_only_for_bonds_and_sign_follows_regime() -> None:
    bonds = {
        f"B{i}": {"asset_class": "bond_etf", "category": "treasury", "rate_duration": d}
        for i, d in enumerate([1.0, 3.0, 6.0, 8.0, 12.0, 17.0])
    }
    snap = snapshot(n=20, overrides=bonds)
    on = score_cross_section(snap, "risk_on").set_index("ticker")
    off = score_cross_section(snap, "risk_off").set_index("ticker")
    neutral = score_cross_section(snap, "neutral").set_index("ticker")
    equities = [str(t) for t in on.index if str(t).startswith("T")]
    assert (on.loc[equities, "contrib_rate_duration"] == 0).all()
    assert val(on, "B5", "contrib_rate_duration") < 0 < val(off, "B5", "contrib_rate_duration")
    assert val(on, "B0", "contrib_rate_duration") > 0 > val(off, "B0", "contrib_rate_duration")
    assert (neutral["contrib_rate_duration"] == 0).all()
    # equity rows have no duration in their applicable weight → full coverage
    assert val(on, "T00", "coverage") == 1.0


def test_risk_penalties() -> None:
    snap = snapshot(
        overrides={
            "LEV3": {"asset_class": "equity_etf", "category": "broad_us", "leverage": 3.0},
            "INV1": {"asset_class": "equity_etf", "category": "broad_us", "leverage": -1.0},
            "VIXY": {"asset_class": "volatility_etp", "category": "vix_futures", "vol_63": 0.8},
            "NEW": {"short_history": True},
        }
    )
    out = score_cross_section(snap, "neutral").set_index("ticker")
    assert val(out, "LEV3", "pen_leverage") == pytest.approx(0.5)
    assert val(out, "INV1", "pen_leverage") == 0.0
    assert val(out, "INV1", "pen_inverse") == pytest.approx(0.25)
    assert val(out, "VIXY", "pen_volatility_etp") == pytest.approx(0.5)
    assert val(out, "VIXY", "pen_high_vol") == pytest.approx(0.5)  # 0.5 × (0.8/0.4 − 1)
    assert val(out, "NEW", "pen_short_history") == pytest.approx(0.25)
    assert val(out, "T05", "risk_penalty") == 0.0
    assert val(out, "LEV3", "score") == pytest.approx(
        val(out, "LEV3", "composite") - val(out, "LEV3", "risk_penalty")
    )


# --- explanations -----------------------------------------------------------------------


def test_top_reasons_are_largest_positive_contributions() -> None:
    out = score_cross_section(snapshot(), "neutral")
    row = out.sort_values("composite", ascending=False).iloc[0]
    reasons = top_reasons(row, ScoringConfig().factors)
    assert 1 <= len(reasons) <= 3
    contribs = [r["contribution"] for r in reasons]
    assert contribs == sorted(contribs, reverse=True)
    best = max((row[c], c) for c in out.columns if c.startswith("contrib_"))
    assert reasons[0]["factor"] == best[1].removeprefix("contrib_")
    assert all(c > 0 for c in contribs)


def test_main_risks_flags_leverage_with_holding_warning() -> None:
    row = pd.Series(
        {
            "asset_class": "equity_etf",
            "leverage": 3.0,
            "vol_63": 0.55,
            "max_dd_252": -0.45,
            "beta_252": 3.0,
            "adv_usd_60": 1e9,
            "short_history": False,
        }
    )
    risks = main_risks(row)
    assert risks[0]["code"] == "leveraged_inverse"
    assert "持有期限" in risks[0]["label"]
    assert len(risks) == 3
    plain = pd.Series(
        {
            "asset_class": "equity",
            "leverage": 1.0,
            "vol_63": 0.2,
            "max_dd_252": -0.1,
            "beta_252": 1.0,
            "adv_usd_60": 1e9,
            "short_history": False,
        }
    )
    assert [r["code"] for r in main_risks(plain)] == ["systematic"]
    inverse = plain.copy()
    inverse["leverage"] = -1.0
    assert main_risks(inverse)[0]["code"] == "leveraged_inverse"

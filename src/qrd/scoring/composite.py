"""Cross-sectional scoring for one date: normalise factors, weight by regime, penalise risk.

Input is the factor snapshot of a single date ``t`` (every value already point-in-time,
ADR 0003), so nothing here can look ahead: the cross-section is the only data used.

* Each factor is transformed and sign-adjusted (higher = better), winsorized and
  z-scored within its asset class *and* across the pooled universe; the two are blended
  (``NormalizationConfig.group_blend``). Small classes use the pooled z-score only.
* A group score is the mean z of the group's *available* factors; missing factors stay
  NaN (never 0). The composite is the weighted mean over groups with data, weights
  renormalised over them — so missing data lowers a factor's weight instead of
  pretending it is neutral. ``coverage`` records how much weight had data.
* ``contrib_<factor>`` columns sum exactly to ``composite`` (score decomposition).
* Risk penalties (leverage, inverse, volatility ETPs, high vol, short history) are
  subtracted to give ``score``. Concentration penalties are applied during selection.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qrd.scoring.config import GROUPS, FactorSpec, NormalizationConfig, PenaltyConfig, ScoringConfig

PENALTY_COLUMNS = [
    "pen_leverage",
    "pen_inverse",
    "pen_volatility_etp",
    "pen_high_vol",
    "pen_short_history",
]


def winsorized_z(values: pd.Series, lower: float, upper: float) -> pd.Series:
    """Clip to the [lower, upper] quantiles, then z-score. NaN stays NaN.

    Degenerate inputs (fewer than 2 values or zero dispersion) carry no cross-sectional
    information and map to 0 for the non-missing entries.
    """
    v = values.astype(float)
    present = v.dropna()
    if len(present) < 2:  # noqa: PLR2004
        return v.where(v.isna(), 0.0)
    lo, hi = float(present.quantile(lower)), float(present.quantile(upper))
    clipped = v.clip(lo, hi)
    std = float(clipped.std(ddof=0))
    if not np.isfinite(std) or std == 0:
        return v.where(v.isna(), 0.0)
    z: pd.Series = (clipped - clipped.mean()) / std
    return z


def normalize(values: pd.Series, groups: pd.Series, cfg: NormalizationConfig) -> pd.Series:
    """Blend of within-group and pooled winsorized z-scores (same index as ``values``)."""
    pooled = winsorized_z(values, cfg.lower_pct, cfg.upper_pct)
    within = pooled.copy()
    for _, idx in values.groupby(groups, sort=True).groups.items():
        member = values.loc[idx]
        if member.notna().sum() >= cfg.min_group_size:
            within.loc[idx] = winsorized_z(member, cfg.lower_pct, cfg.upper_pct)
    return cfg.group_blend * within + (1 - cfg.group_blend) * pooled


def _transform(spec: FactorSpec, raw: pd.Series) -> pd.Series:
    x = raw.astype(float)
    if spec.transform == "abs":
        x = x.abs()
    elif spec.transform == "log":
        x = pd.Series(np.log(x.where(x > 0)), index=x.index)
    elif spec.transform == "log1p":
        x = pd.Series(np.log1p(x.where(x >= 0)), index=x.index)
    return spec.sign * x


def _applicable(spec: FactorSpec, asset_class: pd.Series) -> pd.Series:
    if spec.asset_classes is None:
        return pd.Series(True, index=asset_class.index)
    return asset_class.isin(spec.asset_classes)


def risk_penalties(snap: pd.DataFrame, cfg: PenaltyConfig) -> pd.DataFrame:
    lev = snap["leverage"].astype(float)
    vol = snap["vol_63"].astype(float)
    excess_vol = (vol / cfg.high_vol_threshold - 1).clip(lower=0)
    out = pd.DataFrame(
        {
            "pen_leverage": cfg.per_extra_leverage * (lev.abs() - 1).clip(lower=0),
            "pen_inverse": np.where(lev < 0, cfg.inverse, 0.0),
            "pen_volatility_etp": np.where(
                snap["asset_class"] == "volatility_etp", cfg.volatility_etp, 0.0
            ),
            "pen_high_vol": (cfg.high_vol_slope * excess_vol)
            .clip(upper=cfg.high_vol_cap)
            .fillna(0.0),
            "pen_short_history": np.where(
                snap["short_history"].fillna(True).astype(bool), cfg.short_history, 0.0
            ),
        },
        index=snap.index,
    )
    return out[PENALTY_COLUMNS]


def score_cross_section(
    snap: pd.DataFrame, regime: str, cfg: ScoringConfig | None = None
) -> pd.DataFrame:
    """Score one date's candidates. ``snap`` has one row per ticker (factors + meta).

    Returns ``snap``'s identifying columns plus ``z_*``, ``grp_*``, ``contrib_*``,
    ``composite``, ``coverage``, penalty columns, ``risk_penalty`` and ``score``.
    Normalisation uses every row of ``snap`` — pass only the eligible universe.
    """
    c = cfg or ScoringConfig()
    weights = c.weights_for(regime)
    snap = snap.reset_index(drop=True)
    cls = snap["asset_class"]
    out = snap[["ticker", "asset_class", "category", "leverage"]].copy()

    z: dict[str, pd.Series] = {}
    for spec in c.factors:
        raw = snap[spec.column] if spec.column in snap.columns else pd.Series(np.nan, snap.index)
        x = _transform(spec, raw).where(_applicable(spec, cls))
        z[spec.column] = normalize(x, cls, c.normalization)
        out[f"z_{spec.column}"] = z[spec.column]

    group_scores: dict[str, pd.Series] = {}
    applicable_w = pd.Series(0.0, index=snap.index)
    available_w = pd.Series(0.0, index=snap.index)
    for g in GROUPS:
        specs = [s for s in c.factors if s.group == g]
        w = weights[g]
        if not specs:
            continue
        zs = pd.concat([z[s.column] for s in specs], axis=1)
        score = zs.mean(axis=1, skipna=True)  # NaN when no factor of the group has data
        group_scores[g] = score
        out[f"grp_{g}"] = score
        if w == 0:
            continue
        applies = pd.concat([_applicable(s, cls) for s in specs], axis=1).any(axis=1)
        applicable_w += np.where(applies, abs(w), 0.0)
        available_w += np.where(applies & score.notna(), abs(w), 0.0)

    denom = available_w.where(available_w > 0)
    composite = pd.Series(0.0, index=snap.index)
    for g, gscore in group_scores.items():
        w = weights[g]
        specs = [s for s in c.factors if s.group == g]
        n_avail = pd.concat([z[s.column].notna() for s in specs], axis=1).sum(axis=1)
        for s in specs:
            contrib = (w * z[s.column] / n_avail.where(n_avail > 0) / denom).fillna(0.0)
            if w == 0:
                contrib = pd.Series(0.0, index=snap.index)
            out[f"contrib_{s.column}"] = contrib
            composite += contrib
        out[f"w_{g}"] = np.where(gscore.notna() & (denom.notna()), w / denom, 0.0) if w else 0.0

    out["coverage"] = (available_w / applicable_w.where(applicable_w > 0)).fillna(0.0)
    out["composite"] = composite.where(denom.notna())
    pens = risk_penalties(snap, c.penalties)
    out = pd.concat([out, pens], axis=1)
    out["risk_penalty"] = pens.sum(axis=1)
    out["score"] = out["composite"] - out["risk_penalty"]
    return out

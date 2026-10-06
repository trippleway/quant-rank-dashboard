"""Daily ranking: factor snapshot on ``asof`` → eligible universe → scores → Top 50 + JSON.

Point-in-time: the inputs are the stored features (each value uses data knowable at the
close of its date, ADR 0003), the regime label of ``asof`` and bars dated ``<= asof``
(liquidity screen and return correlations). The ranking is meant for trading on t+1.
``tests/test_rank_lookahead.py`` checks that ranking from truncated inputs is identical.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from qrd import DISCLAIMER
from qrd.config import Settings
from qrd.features.build import load_prices
from qrd.features.factors import FACTOR_COLUMNS
from qrd.features.regime import NEUTRAL, UNKNOWN
from qrd.scoring.composite import PENALTY_COLUMNS, score_cross_section
from qrd.scoring.config import GROUPS, ScoringConfig
from qrd.scoring.explain import main_risks, top_reasons
from qrd.scoring.select import (
    Selection,
    correlations_from_returns,
    return_correlations,
    select_top,
)
from qrd.storage import ParquetStore
from qrd.universe import LiquidityRules, liquidity_filter

SCHEMA_VERSION = "1.0"
NOTES = (
    "排名在 asof 收盤後以當日（含）以前可得的資料計算，供下一個交易日參考。",
    "Regime 輸入（VIX、信用利差、曲線、美元、油價、黃金、GDELT 語調）是總體與國際局勢的"
    "代理指標，不是局勢本身的量測。",
    "財報型品質／價值因子未納入（免費來源沒有 point-in-time 財報）；"
    "缺少的因子以降權處理，不當作 0。",
    "Universe 為現有成分的靜態快照，存在存活者偏誤。",
)


@dataclass
class RankResult:
    asof: pd.Timestamp
    regime: dict[str, Any]
    weights: dict[str, float]
    scored: pd.DataFrame  # every candidate on asof: raw factors, z, contributions, score
    ineligible: pd.DataFrame  # ticker, reason
    selection: Selection
    cfg: ScoringConfig = field(default_factory=ScoringConfig)

    @property
    def top(self) -> pd.DataFrame:
        return self.selection.selected


def _regime_row(regime: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    reg = regime.set_index("date") if "date" in regime.columns else regime
    if asof not in reg.index:
        return {"label": UNKNOWN, "stress_score": None, "n_components": 0, "contributions": {}}
    row = reg.loc[asof]
    stress = _num(row["stress_score"]) if "stress_score" in reg.columns else None
    return {
        "label": str(row["regime"]),
        "stress_score": stress,
        "n_components": int(_num(row["n_components"]) or 0) if "n_components" in reg.columns else 0,
        "contributions": {
            c.removeprefix("contrib_"): v
            for c in reg.columns
            if c.startswith("contrib_") and (v := _num(row[c])) is not None
        },
    }


def rank_asof(
    factors: pd.DataFrame,
    regime: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    asof: pd.Timestamp | None = None,
    cfg: ScoringConfig | None = None,
    liquidity: LiquidityRules | None = None,
    screen: pd.DataFrame | None = None,
    returns: pd.DataFrame | None = None,
) -> RankResult:
    """Rank one date. ``screen`` (``liquidity_filter`` output for ``asof``) and ``returns``
    (``daily_returns_wide`` of all bars) may be precomputed by callers that rank many
    dates (the backtest); results are identical to computing them here."""
    c = cfg or ScoringConfig()
    day = pd.Timestamp(asof) if asof is not None else pd.Timestamp(factors["date"].max())
    snap = factors[factors["date"] == day].sort_values("ticker").reset_index(drop=True)
    if snap.empty:
        raise ValueError(f"no factors on {day.date()}")
    reg = _regime_row(regime, day)
    weights_regime = NEUTRAL if reg["label"] == UNKNOWN else reg["label"]

    # Tickers with factors earlier but not on asof (stale data) are reported, not ranked.
    known = set(factors.loc[factors["date"] <= day, "ticker"].unique())
    reasons = {t: "no bar on asof (stale data)" for t in sorted(known - set(snap["ticker"]))}

    if screen is None:
        screen = liquidity_filter(prices, day, liquidity)
    liq = screen.set_index("ticker")
    liquid = snap["ticker"].map(liq["eligible"]).fillna(False).astype(bool)
    for t in snap.loc[~liquid, "ticker"]:
        reasons[t] = f"liquidity: {liq.at[t, 'reason']}" if t in liq.index else "liquidity: no bars"
    cand = snap[liquid].reset_index(drop=True)
    if c.exclude_short_history:  # backtest list: at least a year of history (PLAN §5)
        short = cand["short_history"].fillna(True).astype(bool)
        for t in cand.loc[short, "ticker"]:
            reasons[t] = "history < 1 year (excluded from backtest ranking)"
        cand = cand[~short].reset_index(drop=True)

    scored = score_cross_section(cand, weights_regime, c)
    low_cov = scored["coverage"] < c.min_coverage
    for t, cov in scored.loc[low_cov, ["ticker", "coverage"]].itertuples(index=False):
        reasons[t] = f"coverage {cov:.2f} < {c.min_coverage}"
    scored.loc[low_cov, "score"] = float("nan")
    raw_cols = [col for col in [*FACTOR_COLUMNS, "rate_duration"] if col in cand.columns]
    scored = scored.merge(cand[["ticker", *raw_cols]], on="ticker", how="left")

    eligible = scored.loc[scored["score"].notna(), "ticker"].tolist()
    if returns is None:
        corr = return_correlations(prices, eligible, day, c.selection)
    else:
        corr = correlations_from_returns(returns, eligible, day, c.selection)
    selection = select_top(scored, corr, c.selection)
    inel = pd.DataFrame(sorted(reasons.items()), columns=["ticker", "reason"])
    return RankResult(
        asof=day,
        regime={**reg, "weights_regime": weights_regime},
        weights=dict(c.weights_for(weights_regime)),
        scored=scored,
        ineligible=inel,
        selection=selection,
        cfg=c,
    )


# --- JSON output ------------------------------------------------------------------------


def _num(x: Any, digits: int = 4) -> float | None:
    if x is None or pd.isna(x):
        return None
    v = float(x)
    return round(v, digits) if math.isfinite(v) else None


def _entry(row: pd.Series, cfg: ScoringConfig) -> dict[str, Any]:
    factors = []
    groups: dict[str, dict[str, float | None]] = {}
    for s in cfg.factors:
        contrib = float(row.get(f"contrib_{s.column}", 0.0))
        factors.append(
            {
                "factor": s.column,
                "label": s.label,
                "group": s.group,
                "value": _num(row.get(s.column), 6),
                "z": _num(row.get(f"z_{s.column}")),
                "contribution": round(contrib, 6),
            }
        )
        g = groups.setdefault(
            s.group,
            {
                "score": _num(row.get(f"grp_{s.group}")),
                "weight": _num(row.get(f"w_{s.group}")),
                "contribution": 0.0,
            },
        )
        g["contribution"] = round(float(g["contribution"] or 0.0) + contrib, 6)
    penalties = {
        p.removeprefix("pen_"): round(float(row[p]), 4) for p in PENALTY_COLUMNS if row[p] > 0
    }
    return {
        "rank": int(row["rank"]),
        "ticker": row["ticker"],
        "asset_class": row["asset_class"],
        "category": row["category"],
        "leverage": float(row["leverage"]),
        "score": round(float(row["adjusted_score"]), 4),
        "composite": round(float(row["composite"]), 4),
        "risk_penalty": round(float(row["risk_penalty"]), 4),
        "concentration_penalty": round(float(row["concentration_penalty"]), 4),
        "penalties": penalties,
        "coverage": round(float(row["coverage"]), 4),
        "short_history": bool(row.get("short_history", False)),
        "groups": groups,
        "factors": factors,
        "reasons": top_reasons(row, cfg.factors),
        "risks": main_risks(row),
    }


def to_json(result: RankResult, generated_at: datetime | None = None) -> dict[str, Any]:
    sel = result.cfg.selection
    top = result.top
    stamp = (generated_at or datetime.now(UTC)).isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "top50",
        "asof": str(result.asof.date()),
        "generated_at": stamp,
        "disclaimer": DISCLAIMER,
        "notes": list(NOTES),
        "regime": result.regime,
        "weights": {g: result.weights.get(g, 0.0) for g in GROUPS},
        "constraints": {
            "top_n": sel.top_n,
            "asset_class_caps": dict(sel.asset_class_caps),
            "category_cap": sel.category_cap,
            "leveraged_cap": sel.leveraged_cap,
            "max_correlation": sel.max_correlation,
            "corr_window": sel.corr_window,
            "concentration_penalty": sel.concentration_penalty,
            "min_coverage": result.cfg.min_coverage,
        },
        "universe": {
            "candidates": len(result.scored) + len(result.ineligible),
            "eligible": int(result.scored["score"].notna().sum()),
            "ineligible": len(result.ineligible),
        },
        "counts": {
            "asset_class": {k: int(v) for k, v in top["asset_class"].value_counts().items()},
            "leveraged_or_inverse": int((top["leverage"] != 1).sum()),
        },
        "top": [_entry(row, result.cfg) for _, row in top.iterrows()],
        "skipped": [
            {"ticker": t, "score": round(s, 4), "reason": r}
            for t, s, r in result.selection.skipped.itertuples(index=False)
        ],
        "ineligible": result.ineligible.to_dict(orient="records"),
    }


# --- storage wiring ---------------------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def run_rank(settings: Settings, asof: pd.Timestamp | None = None) -> dict[str, Any]:
    """Rank from stored features; write JSON + full score table. Returns a summary."""
    store = ParquetStore(settings.data_dir)
    factors = store.read("features", "factors")
    regime = store.read("features", "regime")
    if factors is None or regime is None or factors.empty:
        raise RuntimeError(f"no features under {settings.data_dir}; run `qrd features` first")
    if asof is not None and asof > factors["date"].max():
        raise RuntimeError(
            f"features end on {factors['date'].max().date()}; "
            f"re-run `qrd features` to rank {asof.date()}"
        )
    result = rank_asof(factors, regime, load_prices(store), asof=asof)
    payload = to_json(result)
    day = payload["asof"]
    out_dir = settings.rankings_dir
    paths = {"top50": out_dir / f"top50-{day}.json"}
    if asof is None:  # a historical --asof run must not replace the current ranking
        paths["latest"] = out_dir / "latest.json"
    for p in paths.values():
        _write_json(p, payload)
    scores_path = store.write("rankings", f"scores-{day}", result.scored)
    return {
        "asof": day,
        "regime": result.regime["label"],
        "weights_regime": result.regime["weights_regime"],
        "selected": len(result.top),
        "eligible": payload["universe"]["eligible"],
        "ineligible": payload["universe"]["ineligible"],
        "counts": payload["counts"],
        "top10": result.top["ticker"].head(10).tolist(),
        "paths": {**{k: str(v) for k, v in paths.items()}, "scores": str(scores_path)},
    }

"""Feature stage: stored bars + macro → factors, macro panel and regime.

``build_features`` is a pure function of its inputs; ``point_in_time`` cuts inputs to
what was knowable on ``asof`` (bars dated ``<= asof``, observations *available*
``<= asof``). Look-ahead tests assert that building on full data and on point-in-time
data gives identical rows up to ``asof``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from qrd.config import Settings
from qrd.features.factors import BENCHMARK, compute_price_factors, compute_rate_duration
from qrd.features.macro import macro_panel
from qrd.features.regime import RegimeConfig, classify_regime, regime_inputs
from qrd.ingest.gdelt import TONE_QUERIES
from qrd.ingest.macro import MACRO_SPECS
from qrd.storage import ParquetStore

log = logging.getLogger("qrd.features")

OBS_COLUMNS = ["obs_date", "available_date", "series", "value"]
RATE_SERIES = "ust_10y"
KNOWN_SERIES = tuple(s.series for s in MACRO_SPECS) + tuple(q.series for q in TONE_QUERIES)
META_COLUMNS = ["asset_class", "category", "leverage"]


@dataclass
class FeatureSet:
    factors: pd.DataFrame  # long: date, ticker, meta, factor columns
    panel: pd.DataFrame  # wide macro panel indexed by date
    regime: pd.DataFrame  # indexed by date


def point_in_time(
    prices: pd.DataFrame, observations: pd.DataFrame, asof: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inputs exactly as they were knowable at the close of ``asof``."""
    p = prices[prices["date"] <= asof]
    o = observations[observations["available_date"] <= asof]
    return p.reset_index(drop=True), o.reset_index(drop=True)


def trading_calendar(prices: pd.DataFrame, reference: str = BENCHMARK) -> pd.DatetimeIndex:
    ref = prices.loc[prices["ticker"] == reference, "date"]
    dates = ref if not ref.empty else prices["date"]
    return pd.DatetimeIndex(sorted(dates.unique()), name="date")


def build_features(
    prices: pd.DataFrame,
    observations: pd.DataFrame,
    universe: pd.DataFrame,
    *,
    exclude: set[str] | frozenset[str] = frozenset(),
    regime_cfg: RegimeConfig | None = None,
) -> FeatureSet:
    calendar = trading_calendar(prices)
    panel = macro_panel(observations, calendar, series=KNOWN_SERIES)
    regime = classify_regime(regime_inputs(panel, prices), regime_cfg)

    keep = set(universe["ticker"]) - set(exclude)
    keep.add(BENCHMARK)  # needed for beta; dropped below if not in the universe
    bars = prices[prices["ticker"].isin(keep)]
    factors = compute_price_factors(bars)

    yields = observations[observations["series"] == RATE_SERIES]
    if yields.empty:
        factors["rate_duration"] = np.nan
    else:
        dur = pd.concat(
            [compute_rate_duration(g, yields) for _, g in bars.groupby("ticker", sort=True)],
            ignore_index=True,
        )
        factors = factors.merge(dur, on=["date", "ticker"], how="left")

    meta = universe.set_index("ticker")[META_COLUMNS]
    factors = factors[factors["ticker"].isin(meta.index.difference(list(exclude)))]
    factors = factors.join(meta, on="ticker")
    lead = ["date", "ticker", *META_COLUMNS]
    factors = factors[lead + [c for c in factors.columns if c not in lead]]
    return FeatureSet(factors.reset_index(drop=True), panel, regime)


# --- storage wiring -------------------------------------------------------------------


def load_prices(store: ParquetStore) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in store.keys("prices")]
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "close", "adj_close", "volume"])
    return pd.concat(frames, ignore_index=True)


def load_observations(store: ParquetStore) -> pd.DataFrame:
    frames = [
        pd.read_parquet(p, columns=OBS_COLUMNS)
        for kind in ("macro", "sentiment")
        for p in store.keys(kind)
    ]
    if not frames:
        return pd.DataFrame(columns=OBS_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def latest_unusable(quality_dir: Path) -> set[str]:
    """Tickers with an ``error`` issue in the most recent quality report."""
    reports = sorted(quality_dir.glob("quality-*.json")) if quality_dir.is_dir() else []
    if not reports:
        return set()
    issues = json.loads(reports[-1].read_text(encoding="utf-8"))
    return {i["ticker"] for i in issues if i.get("severity") == "error"}


@dataclass
class FeatureSummary:
    asof: str
    tickers: int
    excluded: list[str]
    regime: str
    stress_score: float | None
    n_components: int
    contributions: dict[str, float]
    factor_coverage: dict[str, float]
    paths: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


def run_features(
    settings: Settings, universe: pd.DataFrame, asof: pd.Timestamp | None = None
) -> FeatureSummary:
    store = ParquetStore(settings.data_dir)
    prices = load_prices(store)
    if prices.empty:
        raise RuntimeError(f"no price data under {settings.prices_dir}; run `qrd ingest` first")
    observations = load_observations(store)
    if asof is not None:
        prices, observations = point_in_time(prices, observations, asof)
    excluded = latest_unusable(settings.quality_dir)
    fs = build_features(prices, observations, universe, exclude=excluded)

    paths = {
        "factors": str(store.write("features", "factors", fs.factors)),
        "macro_panel": str(store.write("features", "macro_panel", fs.panel.reset_index())),
        "regime": str(store.write("features", "regime", fs.regime.reset_index())),
    }
    last_date = fs.factors["date"].max()
    snap = fs.factors[fs.factors["date"] == last_date]
    numeric = snap.select_dtypes("number").drop(columns=["leverage", "history_sessions"])
    coverage = {c: round(float(numeric[c].notna().mean()), 4) for c in numeric.columns}
    reg = fs.regime.iloc[-1]
    contrib = {
        c.removeprefix("contrib_"): round(float(reg[c]), 4)
        for c in fs.regime.columns
        if c.startswith("contrib_") and pd.notna(reg[c])
    }
    stress = reg["stress_score"]
    return FeatureSummary(
        asof=str(pd.Timestamp(last_date).date()),
        tickers=int(snap["ticker"].nunique()),
        excluded=sorted(excluded),
        regime=str(reg["regime"]),
        stress_score=None if pd.isna(stress) else round(float(stress), 4),
        n_components=int(reg["n_components"]),
        contributions=contrib,
        factor_coverage=coverage,
        paths=paths,
    )

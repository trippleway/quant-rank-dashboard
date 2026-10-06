"""No look-ahead in the daily ranking (SYNTHETIC FIXTURE data only).

Property: ranking on ``t`` from features built on point-in-time inputs (bars dated
``<= t``, macro *available* ``<= t``) equals ranking on ``t`` from the full history —
the whole score table, the Top N and the JSON payload. Corrupting everything after
``t`` must not change it either. A canary shows the fixture is sensitive to a leak.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from qrd.features.build import FeatureSet, build_features, point_in_time
from qrd.features.regime import RegimeComponent, RegimeConfig
from qrd.scoring.config import ScoringConfig, SelectionConfig
from qrd.scoring.rank import RankResult, rank_asof, to_json
from tests.helpers import make_bars

N = 420
START = "2022-01-03"
UNIVERSE = [
    ("SPY", "equity_etf", "broad_us", 1),
    ("VOO", "equity_etf", "broad_us", 1),
    ("QQQ", "equity_etf", "broad_us", 1),
    ("SSO", "equity_etf", "broad_us", 2),
    ("SH", "equity_etf", "broad_us", -1),
    ("HYG", "bond_etf", "corporate_hy", 1),
    ("IEF", "bond_etf", "treasury_intermediate", 1),
    ("TLT", "bond_etf", "treasury_long", 1),
    ("SHY", "bond_etf", "treasury_short", 1),
    ("AGG", "bond_etf", "aggregate", 1),
    ("TBT", "bond_etf", "treasury_long", -2),
    ("GLD", "commodity_etf", "precious_metals", 1),
    ("USO", "commodity_etf", "energy", 1),
    ("UUP", "currency_etf", "usd", 1),
    ("VIXY", "volatility_etp", "vix_futures", 1),
    *[
        (f"S{i:02d}", "equity", "information_technology" if i < 6 else "financials", 1)
        for i in range(12)
    ],
]
MACRO = {"vix": 1, "hy_oas": 1, "curve_10y2y": 1, "ust_10y": 1, "usd_broad": 7, "wti": 7}
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
        ]
    ),
    pct_window=200,
)
CFG = ScoringConfig(selection=SelectionConfig(top_n=22, category_cap=4, leveraged_cap=1))
CUTOFFS = [300, 360, N - 3]
FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _universe() -> pd.DataFrame:
    return pd.DataFrame(
        [(*row, "etf") for row in UNIVERSE],
        columns=["ticker", "asset_class", "category", "leverage", "instrument"],
    )


def _prices() -> pd.DataFrame:
    frames = []
    for i, (t, *_rest) in enumerate(UNIVERSE):
        df = make_bars(t, start=START, periods=N, seed=i + 100, price=20 + 5 * i)
        if t == "VOO":  # near-duplicate of SPY → exercised by correlation de-dup
            spy = make_bars("SPY", start=START, periods=N, seed=100, price=20)
            df[["open", "high", "low", "close", "adj_close"]] = (
                spy[["open", "high", "low", "close", "adj_close"]].to_numpy() * 1.5
            )
        if t == "S11":  # stops trading early → stale on later cutoffs
            df = df.iloc[:330]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _observations() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frames = []
    for series, lag in MACRO.items():
        dates = pd.bdate_range(START, periods=N + 10)
        values = 30 + np.cumsum(rng.normal(0, 1, len(dates)))
        frames.append(
            pd.DataFrame(
                {
                    "obs_date": dates,
                    "available_date": dates + pd.offsets.BDay(lag),
                    "series": series,
                    "value": values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _rank(prices: pd.DataFrame, obs: pd.DataFrame, t: pd.Timestamp) -> RankResult:
    fs: FeatureSet = build_features(prices, obs, _universe(), regime_cfg=REGIME_CFG)
    return rank_asof(fs.factors, fs.regime, prices, asof=t, cfg=CFG)


def _assert_same(a: RankResult, b: RankResult) -> None:
    pd.testing.assert_frame_equal(a.scored, b.scored)
    pd.testing.assert_frame_equal(a.top, b.top)
    pd.testing.assert_frame_equal(a.selection.skipped, b.selection.skipped)
    pd.testing.assert_frame_equal(a.ineligible, b.ineligible)
    assert to_json(a, FIXED_TIME) == to_json(b, FIXED_TIME)


def _day(pos: int) -> pd.Timestamp:
    return pd.bdate_range(START, periods=N)[pos]


@pytest.fixture(scope="module")
def full_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    return _prices(), _observations()


def test_fixture_exercises_ranking(full_inputs: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    """Guard against vacuous comparisons: constraints and regimes really bind."""
    res = _rank(*full_inputs, _day(CUTOFFS[-1]))
    # pool exhausted: every eligible ticker is either selected or skipped with a reason
    assert len(res.top) + len(res.selection.skipped) == res.scored["score"].notna().sum()
    assert 15 <= len(res.top) < CFG.selection.top_n
    assert res.regime["label"] != "unknown"
    assert res.scored["composite"].notna().sum() >= 20
    reasons = " ".join(res.selection.skipped["reason"])
    assert "correlation" in reasons  # VOO duplicates SPY
    assert "S11" in set(res.ineligible["ticker"])  # stale
    assert (res.top["leverage"] != 1).sum() <= 1


@pytest.mark.parametrize("pos", CUTOFFS)
def test_ranking_from_truncated_inputs_is_identical(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame], pos: int
) -> None:
    t = _day(pos)
    prices, obs = full_inputs
    full = _rank(prices, obs, t)
    p, o = point_in_time(prices, obs, t)
    _assert_same(full, _rank(p, o, t))


@pytest.mark.parametrize("pos", CUTOFFS[:2])
def test_corrupting_future_does_not_change_ranking(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame], pos: int
) -> None:
    t = _day(pos)
    prices, obs = (df.copy() for df in full_inputs)
    full = _rank(prices, obs, t)
    rng = np.random.default_rng(3)
    future = prices["date"] > t
    for col in ("open", "high", "low", "close", "adj_close"):
        prices.loc[future, col] *= rng.uniform(0.2, 5.0, future.sum())
    prices.loc[future, "volume"] = 1.0
    obs.loc[obs["available_date"] > t, "value"] = 1e6
    _assert_same(full, _rank(prices, obs, t))


def test_canary_future_factors_change_ranking(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    """Scoring t with factors from t+20 (a leak) must give a different result."""
    t, later = _day(CUTOFFS[0]), _day(CUTOFFS[0] + 20)
    prices, obs = full_inputs
    fs = build_features(prices, obs, _universe(), regime_cfg=REGIME_CFG)
    honest = rank_asof(fs.factors, fs.regime, prices, asof=t, cfg=CFG)
    leaky_factors = fs.factors.copy()
    leaky_factors.loc[leaky_factors["date"] == later, "date"] = t + pd.Timedelta(hours=1)
    leaky_factors = leaky_factors[leaky_factors["date"] != t]
    leaky_factors.loc[leaky_factors["date"] == t + pd.Timedelta(hours=1), "date"] = t
    leaky = rank_asof(leaky_factors, fs.regime, prices, asof=t, cfg=CFG)
    with pytest.raises(AssertionError):
        _assert_same(honest, leaky)

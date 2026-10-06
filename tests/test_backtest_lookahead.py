"""No look-ahead in the walk-forward backtest (SYNTHETIC FIXTURE data only).

Property: for a cutoff ``C``, running the whole pipeline (features → ranking on every
signal date → simulation) on inputs cut at ``C`` (bars dated ``<= C``, macro *available*
``<= C``) gives the same holdings and the same daily returns up to ``C`` as running it on
the full history. Corrupting everything after ``C`` must not change them either. A canary
(factors relabelled 20 sessions early) shows the comparison detects a leak.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from qrd.backtest.run import (
    FREQUENCIES,
    MONTHLY,
    STRATEGY,
    WEEKLY,
    BacktestConfig,
    BacktestResult,
    Market,
    run_backtest,
    signal_dates,
)
from qrd.features.build import build_features, point_in_time
from qrd.scoring.config import ScoringConfig, SelectionConfig
from qrd.scoring.rank import rank_asof
from qrd.scoring.select import daily_returns_wide
from qrd.universe import LiquidityPanel, liquidity_filter
from tests.synthetic_market import REGIME_CFG, N, day, observations, prices, universe
from tests.test_rank_lookahead import _assert_same

SCORING = ScoringConfig(
    exclude_short_history=True,
    selection=SelectionConfig(top_n=10, category_cap=4, leveraged_cap=1),
)
START = day(258)
CUTOFFS = [330, 385]


def _cfg(end: pd.Timestamp) -> BacktestConfig:
    return BacktestConfig(
        start=START,
        end=end,
        min_years=0.2,
        min_eligible=15,
        n_random=30,
        robustness=False,
        scoring=SCORING,
    )


def _market(p: pd.DataFrame, o: pd.DataFrame, leak: int = 0) -> Market:
    fs = build_features(p, o, universe(), regime_cfg=REGIME_CFG)
    factors = fs.factors
    if leak:  # canary: the value computed on t + leak is labelled t
        cal = pd.DatetimeIndex(sorted(factors["date"].unique()))
        pos = cal.get_indexer(pd.DatetimeIndex(factors["date"])) - leak
        factors = factors[pos >= 0].assign(date=cal[pos[pos >= 0]])
    return Market.build(factors, fs.regime, p, fs.panel)


def _backtest(p: pd.DataFrame, o: pd.DataFrame, end: pd.Timestamp, leak: int = 0) -> BacktestResult:
    return run_backtest(_market(p, o, leak), _cfg(end))


def _assert_same_until(full: BacktestResult, cut: BacktestResult, c: pd.Timestamp) -> None:
    for f in FREQUENCIES:
        a, b = full.results[f], cut.results[f]
        traded = [i for i, t in enumerate(a.trade_idx) if full.market.calendar[t] <= c]
        traded_b = [i for i, t in enumerate(b.trade_idx) if cut.market.calendar[t] <= c]
        assert traded == traded_b
        for i in traded:
            assert a.steps[i].signal == b.steps[i].signal
            assert a.steps[i].selected == b.steps[i].selected
            pd.testing.assert_series_equal(a.steps[i].scores, b.steps[i].scores)
        assert set(a.runs) == set(b.runs)
        for name in a.runs:
            x = a.runs[name].daily.loc[:c]
            y = b.runs[name].daily.loc[:c]
            assert list(x.index) == list(y.index)
            np.testing.assert_allclose(x.to_numpy(), y.to_numpy(), rtol=1e-12, atol=1e-15)


@pytest.fixture(scope="module")
def full_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    return prices(), observations()


@pytest.fixture(scope="module")
def full_result(full_inputs: tuple[pd.DataFrame, pd.DataFrame]) -> BacktestResult:
    return _backtest(*full_inputs, day(N - 1))


def test_fixture_exercises_backtest(full_result: BacktestResult) -> None:
    """Guard against vacuous comparisons."""
    for f in FREQUENCIES:
        fr = full_result.results[f]
        assert len(fr.steps) >= (20 if f == WEEKLY else 5)
        assert all(1 <= len(s.selected) <= 10 for s in fr.steps)
        assert len({tuple(s.selected) for s in fr.steps}) > 1  # holdings change over time
        assert {"strategy", "equal_weight", "spy", "sixty_forty"} <= set(fr.runs)
        d = fr.runs[STRATEGY].daily.dropna()
        assert d.std() > 0
        assert not np.allclose(d, fr.runs["equal_weight"].daily.dropna())
        assert fr.random is not None and fr.random.cagr.std() > 0
    assert {s.regime for s in full_result.results[WEEKLY].steps} - {"unknown"}


@pytest.mark.parametrize("pos", CUTOFFS)
def test_backtest_from_truncated_inputs_is_identical(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame], full_result: BacktestResult, pos: int
) -> None:
    c = day(pos)
    p, o = point_in_time(*full_inputs, c)
    _assert_same_until(full_result, _backtest(p, o, c), c)


def test_corrupting_future_does_not_change_past_returns(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    c = day(CUTOFFS[0])
    p, o = (df.copy() for df in full_inputs)
    honest = _backtest(p, o, day(N - 1))
    rng = np.random.default_rng(5)
    future = p["date"] > c
    for col in ("open", "high", "low", "close", "adj_close"):
        p.loc[future, col] *= rng.uniform(0.2, 5.0, future.sum())
    p.loc[future, "volume"] = 1.0
    o.loc[o["available_date"] > c, "value"] = 1e6
    _assert_same_until(honest, _backtest(p, o, day(N - 1)), c)


def test_canary_leaky_factors_are_detected(full_inputs: tuple[pd.DataFrame, pd.DataFrame]) -> None:
    c = day(CUTOFFS[0])
    full = _backtest(*full_inputs, day(N - 1), leak=20)
    p, o = point_in_time(*full_inputs, c)
    with pytest.raises(AssertionError):
        _assert_same_until(full, _backtest(p, o, c, leak=20), c)


def test_trades_happen_the_session_after_the_signal(full_result: BacktestResult) -> None:
    cal = full_result.market.calendar
    for fr in full_result.results.values():
        for step, t in zip(fr.steps, fr.trade_idx, strict=True):
            assert cal[t - 1] == step.signal


def test_signal_dates_are_first_sessions_and_prefix_stable() -> None:
    cal = pd.bdate_range("2024-01-01", "2024-03-29")
    start, end = pd.Timestamp("2024-01-10"), cal[-1]
    monthly = signal_dates(cal, MONTHLY, start, end)
    assert [str(d.date()) for d in monthly] == ["2024-01-10", "2024-02-01", "2024-03-01"]
    weekly = signal_dates(cal, WEEKLY, start, end)
    assert weekly[0] == start
    assert all(d.dayofweek == 0 for d in weekly[1:])  # Mondays (no holidays in bdate_range)
    # cutting the calendar never turns a later day into a signal (unlike "last day of month")
    for cut in range(20, len(cal)):
        sub = cal[: cut + 1]
        got = signal_dates(sub, MONTHLY, start, sub[-1])
        assert got == [d for d in monthly if d < sub[-1]]


@pytest.mark.parametrize("pos", [262, 330, N - 1])
def test_precomputed_inputs_match_direct_ranking(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame], pos: int
) -> None:
    p, o = full_inputs
    t = day(pos)
    panel = LiquidityPanel.build(p)
    direct = liquidity_filter(p, t)
    pd.testing.assert_frame_equal(panel.on(t), direct, check_exact=False, rtol=1e-12)
    fs = build_features(p, o, universe(), regime_cfg=REGIME_CFG)
    a = rank_asof(fs.factors, fs.regime, p, asof=t, cfg=SCORING)
    b = rank_asof(
        fs.factors,
        fs.regime,
        p,
        asof=t,
        cfg=SCORING,
        screen=panel.on(t),
        returns=daily_returns_wide(p),
    )
    _assert_same(a, b)


def test_backtest_ranking_excludes_short_history(
    full_inputs: tuple[pd.DataFrame, pd.DataFrame],
) -> None:
    p, o = full_inputs
    p = p[~((p["ticker"] == "QQQ") & (p["date"] < day(200)))]  # QQQ listed late
    fs = build_features(p, o, universe(), regime_cfg=REGIME_CFG)
    t = day(300)
    daily = rank_asof(
        fs.factors, fs.regime, p, asof=t, cfg=replace(SCORING, exclude_short_history=False)
    )
    bt = rank_asof(fs.factors, fs.regime, p, asof=t, cfg=SCORING)
    assert "QQQ" in set(daily.scored.dropna(subset=["score"])["ticker"])
    reasons = bt.ineligible.set_index("ticker")["reason"]
    assert reasons["QQQ"].startswith("history < 1 year")
    assert "QQQ" not in set(bt.scored["ticker"])

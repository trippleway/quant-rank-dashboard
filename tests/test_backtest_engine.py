"""Portfolio simulation, costs and metrics on hand-built returns (SYNTHETIC FIXTURE)."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from qrd.backtest.costs import CostModel
from qrd.backtest.engine import segment_returns, simulate
from qrd.backtest.metrics import (
    cagr,
    decile_returns,
    deflated_sharpe,
    drawdown,
    expected_max_sharpe,
    information_coefficients,
    monthly_returns,
    perf_metrics,
    probabilistic_sharpe,
    sharpe,
)


def _const(w: list[float]) -> Callable[[int], np.ndarray]:
    return lambda k: np.array([w])


def _zero_cost(n: int) -> Callable[[int], np.ndarray]:
    return lambda k: np.zeros(n)


def test_buy_and_hold_drifts_with_prices() -> None:
    r = np.array([[0.0, 0.0], [0.0, 0.0], [0.10, 0.0], [0.10, -0.50]])
    sim = simulate(r, [1], _const([0.5, 0.5]), _zero_cost(2))
    d = sim.daily[0]
    assert np.isnan(d[0])
    assert d[1] == 0.0  # trade day, no cost
    assert d[2] == pytest.approx(0.05)  # 0.5 * 10%
    # day 3: weights drifted to 0.55/0.5 of 1.05 → (0.55*1.1 + 0.5*0.5) / 1.05 - 1
    assert d[3] == pytest.approx((0.55 * 1.1 + 0.5 * 0.5) / 1.05 - 1)
    total = np.prod(1 + d[1:]) - 1
    assert total == pytest.approx(0.5 * 1.21 + 0.5 * 0.5 - 1)


def test_new_weights_only_earn_after_the_trade_close() -> None:
    """Switch B → A at the close of day 2: A's day-2 jump is missed, its day-3 move is earned."""
    r = np.zeros((5, 2))
    r[2, 0] = 0.50  # A jumps on the trade day itself
    r[3, 0] = 0.10  # first return after the trade
    targets = [np.array([[0.0, 1.0]]), np.array([[1.0, 0.0]])]
    sim = simulate(r, [1, 2], lambda k: targets[k], _zero_cost(2))
    d = sim.daily[0]
    assert d[2] == 0.0  # still holding B on day 2
    assert d[3] == pytest.approx(0.10)


def test_costs_and_turnover() -> None:
    r = np.zeros((4, 2))
    r[2, 0] = 1.0  # A doubles → weights drift from 50/50 to 2/3, 1/3
    rates = np.array([0.001, 0.003])
    sim = simulate(r, [0, 2], _const([0.5, 0.5]), lambda k: rates)
    # initial build from cash: |Δw| = (0.5, 0.5)
    assert sim.turnover[0, 0] == pytest.approx(0.5)
    assert sim.cost[0, 0] == pytest.approx(0.5 * 0.001 + 0.5 * 0.003)
    assert sim.daily[0, 0] == pytest.approx(-sim.cost[0, 0])
    # rebalance back to 50/50 from 2/3, 1/3
    assert sim.turnover[0, 1] == pytest.approx(1 / 6)
    assert sim.cost[0, 1] == pytest.approx(1 / 6 * 0.001 + 1 / 6 * 0.003)
    gross = 0.5 * 2 + 0.5 - 1  # day-2 portfolio return before the cost
    assert sim.daily[0, 2] == pytest.approx((1 + gross) * (1 - sim.cost[0, 1]) - 1)


def test_cash_earns_zero_and_vectorised_portfolios_match_single_runs() -> None:
    rng = np.random.default_rng(0)
    r = rng.normal(0, 0.01, (30, 4))
    w = np.array([[0.25, 0.25, 0.25, 0.25], [0.5, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]])
    rates = np.full(4, 0.0005)
    both = simulate(r, [3, 10, 20], lambda k: w, lambda k: rates)
    for i in range(3):
        one = simulate(r, [3, 10, 20], _const(w[i].tolist()), lambda k: rates)
        np.testing.assert_allclose(both.daily[i], one.daily[0])
    assert np.nansum(np.abs(both.daily[2])) == 0.0  # all cash
    value = 0.5 + 0.5 * np.cumprod(1 + r[4:10, 0])  # half in asset 0, half in cash
    np.testing.assert_allclose(both.daily[1, 4:10], value / np.r_[1.0, value[:-1]] - 1)


def test_simulate_rejects_bad_schedule() -> None:
    r = np.zeros((5, 1))
    with pytest.raises(ValueError, match="increasing"):
        simulate(r, [2, 2], _const([1.0]), _zero_cost(1))
    with pytest.raises(ValueError, match="range"):
        simulate(r, [5], _const([1.0]), _zero_cost(1))


def test_segment_returns_compound_between_trades() -> None:
    r = np.array([[0.0], [0.1], [0.1], [np.nan], [0.5]])
    seg = segment_returns(r, [0, 2, 4])
    np.testing.assert_allclose(seg[:, 0], [1.1 * 1.1 - 1, 1.5 - 1])


def test_cost_model_tiers_and_complex_products() -> None:
    m = CostModel()
    adv = pd.Series([5e8, 5e7, 1e6, np.nan, 5e8, 5e8])
    lev = pd.Series([1, 1, 1, 1, 3, 1])
    cls = pd.Series(["equity"] * 5 + ["volatility_etp"])
    bps = m.bps(adv, lev, cls).tolist()
    assert bps == [5.0, 7.5, 10.0, 10.0, 10.0, 10.0]
    assert (CostModel(multiplier=2.0).bps(adv, lev, cls) == pd.Series(bps) * 2).all()


# --- metrics --------------------------------------------------------------------------


def _daily(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def test_cagr_and_drawdown() -> None:
    r = _daily([0.001] * 252)
    assert cagr(r) == pytest.approx(1.001**252 - 1)
    dd = drawdown(_daily([0.10, -0.50, 0.20]))
    assert dd.min() == pytest.approx(-0.5)
    assert dd.iloc[-1] == pytest.approx(0.5 * 1.2 - 1)  # 0.66 vs the 1.1 peak


def test_sharpe_uses_excess_returns() -> None:
    rng = np.random.default_rng(1)
    r = _daily(list(rng.normal(0.001, 0.01, 500)))
    rf = pd.Series(0.0004, index=r.index)
    expected = (r - 0.0004).mean() / (r - 0.0004).std(ddof=1) * math.sqrt(252)
    assert sharpe(r, rf) == pytest.approx(expected)
    m = perf_metrics(r, rf, period_returns=pd.Series([0.1, -0.1, 0.2]))
    assert m["sharpe"] == pytest.approx(expected)
    assert m["win_rate_periods"] == pytest.approx(2 / 3)
    cagr_, mdd = m["cagr"], m["max_drawdown"]
    assert cagr_ is not None and mdd is not None
    assert m["calmar"] == pytest.approx(cagr_ / abs(mdd))


def test_monthly_returns_compound_within_month() -> None:
    r = pd.Series(
        [0.1, 0.1, -0.05], index=pd.to_datetime(["2024-01-02", "2024-01-31", "2024-02-01"])
    )
    m = monthly_returns(r)
    assert m["ret"].tolist() == pytest.approx([0.21, -0.05])
    assert m[["year", "month"]].values.tolist() == [[2024, 1], [2024, 2]]


def test_information_coefficients_and_deciles() -> None:
    s = pd.Series(np.arange(100, dtype=float))
    ic, ric = information_coefficients(s, s**3)
    assert ric == pytest.approx(1.0)
    assert ic is not None and 0.8 < ic < 1.0
    dec = decile_returns(s, s / 100)
    assert dec is not None and list(dec.index) == list(range(1, 11))
    assert dec.is_monotonic_increasing
    assert information_coefficients(s.iloc[:2], s.iloc[:2]) == (None, None)


def test_probabilistic_and_deflated_sharpe() -> None:
    assert probabilistic_sharpe(0.05, 0.05, 1000, 0.0, 3.0) == pytest.approx(0.5)
    assert probabilistic_sharpe(0.10, 0.0, 1000, 0.0, 3.0) > 0.99
    assert expected_max_sharpe(0.001, 1) == 0.0
    assert expected_max_sharpe(0.001, 10) < expected_max_sharpe(0.001, 100)
    rng = np.random.default_rng(2)
    r = pd.Series(rng.normal(0.0005, 0.01, 1000))
    one = deflated_sharpe(r, [0.05])
    many = deflated_sharpe(r, list(rng.normal(0.02, 0.02, 50)))
    assert one["deflated_sharpe"] == pytest.approx(one["psr_vs_zero"])
    assert many["deflated_sharpe"] < one["deflated_sharpe"]  # type: ignore[operator]
    assert many["n_trials"] == 50

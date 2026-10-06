"""Portfolio simulation with drift, turnover and costs (vectorised over many portfolios).

Timing convention (no look-ahead): ``returns[d]`` is the return from the close of session
``d - 1`` to the close of ``d``. A portfolio decided from data up to the close of signal
session ``t`` is traded at the close of ``t + 1`` (``trade_idx``) and first earns
``returns[t + 2]``. Between trades weights drift with prices (buy and hold); at each trade
the cost ``Σ |w_new − w_drifted| · cost_rate`` is charged on that day. Days before the
first trade are NaN. Uninvested weight is cash earning 0 (rf is handled in the metrics).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np


@dataclass
class SimResult:
    daily: np.ndarray  # (S, D) daily portfolio returns after costs, NaN before first trade
    turnover: np.ndarray  # (S, K) one-way turnover Σ|Δw| / 2 at each trade
    cost: np.ndarray  # (S, K) cost as a fraction of portfolio value at each trade


def simulate(
    returns: np.ndarray,
    trade_idx: Sequence[int],
    targets: Callable[[int], np.ndarray],
    cost_rates: Callable[[int], np.ndarray],
) -> SimResult:
    """Simulate S portfolios over D sessions and N assets.

    ``returns``: (D, N) simple returns, NaN treated as 0 (no bar: price unchanged).
    ``targets(k)``: (S, N) target weights at trade ``k`` (rows sum to <= 1; rest is cash).
    ``cost_rates(k)``: (N,) one-way cost as a fraction (bps / 1e4) at trade ``k``.
    ``targets`` and ``cost_rates`` are called once per trade, in order.
    """
    n_days, n_assets = returns.shape
    if list(trade_idx) != sorted(set(trade_idx)):
        raise ValueError("trade_idx must be strictly increasing")
    if trade_idx and (trade_idx[0] < 0 or trade_idx[-1] >= n_days):
        raise ValueError("trade_idx out of range")
    growth = 1.0 + np.nan_to_num(returns, nan=0.0)
    n_trades = len(trade_idx)
    daily = np.empty((0, n_days))
    turnover = np.empty((0, n_trades))
    cost = np.empty((0, n_trades))
    drifted = np.empty((0, n_assets))
    for k, t in enumerate(trade_idx):
        w = np.asarray(targets(k), dtype=float)
        if k == 0:
            n_port = w.shape[0]
            daily = np.full((n_port, n_days), np.nan)
            turnover = np.zeros((n_port, n_trades))
            cost = np.zeros((n_port, n_trades))
            drifted = np.zeros((n_port, n_assets))
        dw = np.abs(w - drifted)
        turnover[:, k] = dw.sum(axis=1) / 2
        cost[:, k] = dw @ np.asarray(cost_rates(k), dtype=float)
        before = np.nan_to_num(daily[:, t], nan=0.0)
        daily[:, t] = (1 + before) * (1 - cost[:, k]) - 1
        end = trade_idx[k + 1] if k + 1 < n_trades else n_days - 1
        if end <= t:
            drifted = w
            continue
        cum = np.cumprod(growth[t + 1 : end + 1], axis=0)  # (L, N)
        value = (1 - w.sum(axis=1))[:, None] + w @ cum.T  # (S, L), 1 = value after trade
        prev = np.concatenate([np.ones((value.shape[0], 1)), value[:, :-1]], axis=1)
        daily[:, t + 1 : end + 1] = value / prev - 1
        drifted = w * cum[-1][None, :] / value[:, -1:]
    return SimResult(daily, turnover, cost)


def segment_returns(returns: np.ndarray, trade_idx: Sequence[int]) -> np.ndarray:
    """(K-1, N) compounded asset returns held from trade ``k`` to trade ``k + 1``."""
    growth = 1.0 + np.nan_to_num(returns, nan=0.0)
    out = [np.prod(growth[a + 1 : b + 1], axis=0) - 1 for a, b in pairwise(trade_idx)]
    return np.array(out).reshape(len(out), returns.shape[1])

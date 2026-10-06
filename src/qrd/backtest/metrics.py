"""Performance, signal-quality and multiple-testing statistics for daily return series.

Conventions: 252 sessions per year; excess returns over a daily risk-free series (3-month
Treasury bill, point-in-time) for Sharpe / Sortino; drawdowns on the compounded curve.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import cast

import numpy as np
import pandas as pd

YEAR = 252
EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


def _clean(x: float) -> float | None:
    return float(x) if x is not None and math.isfinite(x) else None


def equity_curve(r: pd.Series) -> pd.Series:
    return (1 + r.fillna(0.0)).cumprod()


def drawdown(r: pd.Series) -> pd.Series:
    eq = equity_curve(r)
    return eq / eq.cummax() - 1


def cagr(r: pd.Series) -> float:
    n = int(r.notna().sum())
    if n == 0:
        return float("nan")
    total = float(equity_curve(r).iloc[-1])
    return total ** (YEAR / n) - 1 if total > 0 else -1.0


def sharpe(r: pd.Series, rf: pd.Series | None = None) -> float:
    ex = (r - (rf.reindex(r.index).fillna(0.0) if rf is not None else 0.0)).dropna()
    sd = float(ex.std(ddof=1))
    if len(ex) < 2 or not sd > 0:  # noqa: PLR2004
        return float("nan")
    return float(ex.mean()) / sd * math.sqrt(YEAR)


def perf_metrics(
    r: pd.Series, rf: pd.Series | None = None, period_returns: pd.Series | None = None
) -> dict[str, float | None]:
    """Headline metrics of a daily return series (NaN-free part only)."""
    r = r.dropna()
    ex = r - (rf.reindex(r.index).fillna(0.0) if rf is not None else 0.0)
    vol = float(r.std(ddof=1)) * math.sqrt(YEAR) if len(r) > 1 else float("nan")
    downside = math.sqrt(float((ex.clip(upper=0) ** 2).mean())) * math.sqrt(YEAR)
    sortino = float(ex.mean()) * YEAR / downside if downside > 0 else float("nan")
    g = cagr(r)
    mdd = float(drawdown(r).min()) if len(r) else float("nan")
    out = {
        "cagr": g,
        "total_return": float(equity_curve(r).iloc[-1] - 1) if len(r) else float("nan"),
        "ann_vol": vol,
        "sharpe": sharpe(r, rf),
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": g / abs(mdd) if mdd < 0 else float("nan"),
        "win_rate_daily": float((r > 0).mean()) if len(r) else float("nan"),
        "days": float(len(r)),
    }
    if period_returns is not None and len(period_returns):
        out["win_rate_periods"] = float((period_returns > 0).mean())
    return {k: _clean(v) for k, v in out.items()}


def monthly_returns(r: pd.Series) -> pd.DataFrame:
    """Compounded calendar-month returns: columns year, month, ret."""
    r = r.dropna()
    idx = pd.DatetimeIndex(r.index)
    m = (1 + r).groupby([idx.year, idx.month]).prod() - 1
    df = m.rename("ret").reset_index()
    df.columns = pd.Index(["year", "month", "ret"])
    return df


def rolling_sharpe(r: pd.Series, rf: pd.Series | None, window: int = YEAR) -> pd.Series:
    ex = r - (rf.reindex(r.index).fillna(0.0) if rf is not None else 0.0)
    roll = ex.rolling(window, min_periods=window)
    out: pd.Series = roll.mean() / roll.std(ddof=1) * math.sqrt(YEAR)
    return out


def information_coefficients(
    scores: pd.Series, forward: pd.Series
) -> tuple[float | None, float | None]:
    """Pearson IC and Spearman rank IC between scores and forward returns (aligned)."""
    df = pd.concat([scores.rename("s"), forward.rename("f")], axis=1).dropna()
    if len(df) < 3 or df["s"].nunique() < 2 or df["f"].nunique() < 2:  # noqa: PLR2004
        return None, None
    ic = float(np.corrcoef(df["s"].to_numpy(float), df["f"].to_numpy(float))[0, 1])
    ric = float(np.corrcoef(df["s"].rank().to_numpy(float), df["f"].rank().to_numpy(float))[0, 1])
    return _clean(ic), _clean(ric)


def decile_returns(scores: pd.Series, forward: pd.Series, n: int = 10) -> pd.Series | None:
    """Equal-weight forward return per score bucket (1 = lowest score, n = highest)."""
    df = pd.concat([scores.rename("s"), forward.rename("f")], axis=1).dropna()
    if len(df) < n * 2:
        return None
    bucket = pd.qcut(df["s"].rank(method="first"), n, labels=list(range(1, n + 1)))
    out: pd.Series = df.groupby(bucket, observed=True)["f"].mean()
    return out


def t_stat(x: pd.Series) -> float | None:
    x = x.dropna()
    if len(x) < 2 or not float(x.std(ddof=1)) > 0:  # noqa: PLR2004
        return None
    return _clean(float(x.mean()) / float(x.std(ddof=1)) * math.sqrt(len(x)))


def probabilistic_sharpe(
    sr: float, benchmark_sr: float, n_obs: int, skew: float, kurtosis: float
) -> float:
    """P(true SR > benchmark) given a non-annualised SR estimate (Bailey & López de Prado).

    ``kurtosis`` is the raw (non-excess) kurtosis of the returns.
    """
    denom = 1 - skew * sr + (kurtosis - 1) / 4 * sr**2
    if n_obs < 2 or not denom > 0:  # noqa: PLR2004
        return float("nan")
    return _N.cdf((sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def expected_max_sharpe(trial_sr_var: float, n_trials: int) -> float:
    """Expected maximum of ``n_trials`` non-annualised SR estimates under zero true SR."""
    if n_trials < 2 or not trial_sr_var > 0:  # noqa: PLR2004
        return 0.0
    a = _N.inv_cdf(1 - 1 / n_trials)
    b = _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(trial_sr_var) * ((1 - EULER_GAMMA) * a + EULER_GAMMA * b)


def deflated_sharpe(r: pd.Series, trial_sharpes_daily: list[float]) -> dict[str, float | None]:
    """Deflated Sharpe ratio of ``r`` given the SRs of every variant tried (incl. ``r``)."""
    x = r.dropna()
    sr = float(x.mean() / x.std(ddof=1)) if len(x) > 1 and x.std(ddof=1) > 0 else float("nan")
    trials = [s for s in trial_sharpes_daily if math.isfinite(s)]
    var = float(np.var(trials, ddof=1)) if len(trials) > 1 else 0.0
    sr0 = expected_max_sharpe(var, len(trials))
    skew = float(cast(float, x.skew()))
    kurt = float(cast(float, x.kurt())) + 3.0  # pandas reports excess kurtosis
    return {
        "sharpe_daily": _clean(sr),
        "n_trials": float(len(trials)),
        "trial_sharpe_std_daily": _clean(math.sqrt(var)),
        "expected_max_sharpe_daily": _clean(sr0),
        "psr_vs_zero": _clean(probabilistic_sharpe(sr, 0.0, len(x), skew, kurt)),
        "deflated_sharpe": _clean(probabilistic_sharpe(sr, sr0, len(x), skew, kurt)),
        "skew": _clean(skew),
        "kurtosis": _clean(kurt),
    }

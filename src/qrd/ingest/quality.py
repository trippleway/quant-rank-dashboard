"""Data-quality checks for daily bars.

Checks only *flag* problems — they never silently modify prices. Each issue has a
severity; a ticker with any ``error`` issue is marked unusable for downstream steps.

Checks:

* ``empty`` — no bars at all
* ``duplicate_dates`` — more than one bar per session
* ``non_positive_price`` — close / adj_close <= 0
* ``missing_values`` — share of NaN in close / adj_close / volume
* ``missing_sessions`` — sessions absent vs. the reference calendar since first bar
* ``ohlc_inconsistent`` — high < max(open, close) or low > min(open, close)
* ``abnormal_jump`` — |daily adj return| above a leverage-scaled threshold
* ``spike_reversal`` — a large jump immediately reversed: ``error`` (classic bad tick)
  when both legs exceed ×1.5 / ÷1.5, otherwise ``warn`` (crash days such as 2020-03 can
  produce genuine -30% / +30% V-shapes, which must not disqualify a ticker)
* ``zero_volume_streak`` — consecutive sessions with zero volume
* ``stale`` — last bar older than the reference calendar's last session
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass(frozen=True)
class QualityIssue:
    ticker: str
    check: str
    severity: Severity
    detail: str
    date: str | None = None


@dataclass(frozen=True)
class QualityConfig:
    jump_threshold: float = 0.40  # |adj return| for an unlevered instrument
    spike_threshold: float = 0.25  # jump size that, if reversed next day, is flagged
    # |log move| both legs must exceed for a reversal to be an error (bad tick): ×1.5 / ÷1.5
    spike_error_log_move: float = math.log(1.5)
    missing_values_warn: float = 0.01
    missing_values_error: float = 0.05
    missing_sessions_warn: float = 0.02
    missing_sessions_error: float = 0.10
    zero_volume_streak: int = 5
    stale_sessions: int = 3
    ohlc_tolerance: float = 0.005  # relative; vendors round OHLC differently


def _issue(
    ticker: str, check: str, sev: Severity, detail: str, when: object = None
) -> QualityIssue:
    stamp = None if when is None else str(pd.Timestamp(str(when)).date())
    return QualityIssue(ticker, check, sev, detail, stamp)


def _tiered(
    ticker: str, check: str, share: float, *, warn: float, error: float, what: str
) -> list[QualityIssue]:
    if share > error:
        return [_issue(ticker, check, Severity.ERROR, f"{share:.1%} {what}")]
    if share > warn:
        return [_issue(ticker, check, Severity.WARN, f"{share:.1%} {what}")]
    return []


def _integrity_checks(df: pd.DataFrame, ticker: str, cfg: QualityConfig) -> list[QualityIssue]:
    out: list[QualityIssue] = []
    nonpos = df[(df["close"] <= 0) | (df["adj_close"] <= 0)]
    if not nonpos.empty:
        out.append(
            _issue(
                ticker,
                "non_positive_price",
                Severity.ERROR,
                f"{len(nonpos)} bars",
                nonpos["date"].iloc[0],
            )
        )
    nan_share = float(df[["close", "adj_close", "volume"]].isna().any(axis=1).mean())
    out += _tiered(
        ticker,
        "missing_values",
        nan_share,
        warn=cfg.missing_values_warn,
        error=cfg.missing_values_error,
        what="of bars have NaN fields",
    )
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    tol = cfg.ohlc_tolerance
    bad_ohlc = (df["high"] < body_hi * (1 - tol)) | (df["low"] > body_lo * (1 + tol))
    if bool(bad_ohlc.any()):
        out.append(
            _issue(
                ticker,
                "ohlc_inconsistent",
                Severity.WARN,
                f"{int(bad_ohlc.sum())} bars",
                df.loc[bad_ohlc, "date"].iloc[0],
            )
        )
    zero = (df["volume"].fillna(0) == 0).astype(int)
    streak = int(zero.groupby((zero != zero.shift()).cumsum()).cumsum().max())
    if streak >= cfg.zero_volume_streak:
        out.append(
            _issue(
                ticker,
                "zero_volume_streak",
                Severity.WARN,
                f"{streak} consecutive zero-volume sessions",
            )
        )
    return out


def _calendar_checks(
    df: pd.DataFrame, ticker: str, calendar: pd.DatetimeIndex, cfg: QualityConfig
) -> list[QualityIssue]:
    out: list[QualityIssue] = []
    first, last = df["date"].iloc[0], df["date"].iloc[-1]
    expected = calendar[(calendar >= first) & (calendar <= last)]
    if len(expected):
        missing = expected.difference(pd.DatetimeIndex(df["date"]))
        out += _tiered(
            ticker,
            "missing_sessions",
            len(missing) / len(expected),
            warn=cfg.missing_sessions_warn,
            error=cfg.missing_sessions_error,
            what="of sessions missing",
        )
    lag = int((calendar > last).sum())
    if lag > cfg.stale_sessions:
        out.append(_issue(ticker, "stale", Severity.WARN, f"last bar is {lag} sessions old", last))
    return out


def _path_checks(
    df: pd.DataFrame, ticker: str, leverage: float, cfg: QualityConfig
) -> list[QualityIssue]:
    out: list[QualityIssue] = []
    ret = df["adj_close"].pct_change(fill_method=None)
    jump_limit = cfg.jump_threshold * max(1.0, abs(leverage))
    for when in df.loc[ret.abs() > jump_limit, "date"]:
        out.append(
            _issue(ticker, "abnormal_jump", Severity.WARN, f"|return| > {jump_limit:.0%}", when)
        )

    spike_limit = cfg.spike_threshold * max(1.0, abs(leverage))
    nxt = ret.shift(-1)
    reversal = (
        (ret.abs() > spike_limit) & (nxt.abs() > spike_limit) & (np.sign(ret) != np.sign(nxt))
    )
    # A genuine move rarely round-trips: require the next day to undo most of it.
    undo = ((1 + ret) * (1 + nxt) - 1).abs() < spike_limit / 2
    scale = max(1.0, abs(leverage))
    # Size of the smaller leg in log terms, so ×2-then-÷2 and ÷2-then-×2 score the same.
    log_ret = pd.Series(np.log1p(ret.to_numpy()), index=ret.index).abs()
    leg = pd.concat([log_ret, log_ret.shift(-1)], axis=1).min(axis=1, skipna=False)
    severe = leg > cfg.spike_error_log_move * scale
    for idx in df.index[reversal & undo]:
        sev = Severity.ERROR if bool(severe.loc[idx]) else Severity.WARN
        detail = (
            "jump reversed next session (bad tick?)"
            if sev == Severity.ERROR
            else "large move reversed next session (verify; may be genuine)"
        )
        out.append(_issue(ticker, "spike_reversal", sev, detail, df.loc[idx, "date"]))
    return out


def check_bars(
    bars: pd.DataFrame,
    ticker: str,
    calendar: pd.DatetimeIndex | None = None,
    leverage: float = 1.0,
    config: QualityConfig | None = None,
) -> list[QualityIssue]:
    """Run all checks on one ticker's bars; ``calendar`` is the reference session list."""
    cfg = config or QualityConfig()
    if bars.empty:
        return [_issue(ticker, "empty", Severity.ERROR, "no bars")]
    issues: list[QualityIssue] = []
    dup = int(bars["date"].duplicated().sum())
    if dup:
        issues.append(
            _issue(ticker, "duplicate_dates", Severity.ERROR, f"{dup} duplicated sessions")
        )
    df = bars.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
    issues += _integrity_checks(df, ticker, cfg)
    if calendar is not None and len(calendar):
        issues += _calendar_checks(df, ticker, calendar, cfg)
    issues += _path_checks(df, ticker, leverage, cfg)
    return issues


def issues_frame(issues: list[QualityIssue]) -> pd.DataFrame:
    cols = ["ticker", "check", "severity", "detail", "date"]
    return pd.DataFrame([asdict(i) for i in issues], columns=cols)


def unusable_tickers(issues: list[QualityIssue]) -> set[str]:
    return {i.ticker for i in issues if i.severity == Severity.ERROR}

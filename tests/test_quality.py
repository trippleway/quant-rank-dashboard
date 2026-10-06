"""Data-quality checks: each check fires on a crafted defect and stays quiet on clean data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qrd.ingest.quality import Severity, check_bars, issues_frame, unusable_tickers
from tests.helpers import make_bars


def _checks(issues: list) -> dict[str, Severity]:  # type: ignore[type-arg]
    return {i.check: i.severity for i in issues}


@pytest.fixture
def clean() -> pd.DataFrame:
    return make_bars("X", periods=200)


@pytest.fixture
def calendar(clean: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(clean["date"])


def test_clean_data_has_no_issues(clean: pd.DataFrame, calendar: pd.DatetimeIndex) -> None:
    assert check_bars(clean, "X", calendar) == []


def test_empty_is_error() -> None:
    assert _checks(check_bars(make_bars("X").iloc[:0], "X")) == {"empty": Severity.ERROR}


def test_duplicate_dates(clean: pd.DataFrame) -> None:
    dup = pd.concat([clean, clean.iloc[[5]]])
    assert _checks(check_bars(dup, "X"))["duplicate_dates"] == Severity.ERROR


def test_non_positive_price(clean: pd.DataFrame) -> None:
    bad = clean.copy()
    bad.loc[10, "close"] = 0.0
    assert _checks(check_bars(bad, "X"))["non_positive_price"] == Severity.ERROR


@pytest.mark.parametrize(("n_missing", "severity"), [(4, Severity.WARN), (20, Severity.ERROR)])
def test_missing_values_tiered(clean: pd.DataFrame, n_missing: int, severity: Severity) -> None:
    bad = clean.copy()
    bad.loc[bad.index[:n_missing], "volume"] = np.nan
    assert _checks(check_bars(bad, "X"))["missing_values"] == severity


@pytest.mark.parametrize(("n_drop", "severity"), [(6, Severity.WARN), (30, Severity.ERROR)])
def test_missing_sessions_vs_calendar(
    clean: pd.DataFrame, calendar: pd.DatetimeIndex, n_drop: int, severity: Severity
) -> None:
    holes = clean.drop(index=range(50, 50 + n_drop))
    assert _checks(check_bars(holes, "X", calendar))["missing_sessions"] == severity


def test_stale_series(clean: pd.DataFrame, calendar: pd.DatetimeIndex) -> None:
    old = clean.iloc[:-10]
    assert _checks(check_bars(old, "X", calendar))["stale"] == Severity.WARN


def test_ohlc_inconsistency(clean: pd.DataFrame) -> None:
    bad = clean.copy()
    bad.loc[7, "high"] = bad["close"].iloc[7] * 0.9
    assert _checks(check_bars(bad, "X"))["ohlc_inconsistent"] == Severity.WARN


def test_abnormal_jump_persistent_move_is_warning_only(clean: pd.DataFrame) -> None:
    moved = clean.copy()
    moved.loc[100:, ["close", "adj_close"]] *= 1.6  # +60% and it stays (e.g. buyout)
    found = _checks(check_bars(moved, "X"))
    assert found["abnormal_jump"] == Severity.WARN
    assert "spike_reversal" not in found


def test_jump_threshold_scales_with_leverage(clean: pd.DataFrame) -> None:
    moved = clean.copy()
    moved.loc[100:, ["close", "adj_close"]] *= 1.6
    assert "abnormal_jump" not in _checks(check_bars(moved, "X", leverage=3))


def test_spike_reversal_is_error(clean: pd.DataFrame) -> None:
    bad = clean.copy()
    bad.loc[100, ["close", "adj_close"]] *= 2.0
    found = _checks(check_bars(bad, "X"))
    assert found["spike_reversal"] == Severity.ERROR
    assert unusable_tickers(check_bars(bad, "X")) == {"X"}


def test_zero_volume_streak(clean: pd.DataFrame) -> None:
    bad = clean.copy()
    bad.loc[20:26, "volume"] = 0.0
    assert _checks(check_bars(bad, "X"))["zero_volume_streak"] == Severity.WARN


def test_issues_frame_columns(clean: pd.DataFrame) -> None:
    bad = clean.copy()
    bad.loc[10, "close"] = -1.0
    frame = issues_frame(check_bars(bad, "X"))
    assert list(frame.columns) == ["ticker", "check", "severity", "detail", "date"]
    assert frame.at[0, "date"] == str(pd.Timestamp(bad["date"].iloc[10]).date())

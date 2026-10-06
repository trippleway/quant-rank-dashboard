"""Macro adapters: parsing, availability lag and fallback chain (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from qrd.ingest.macro import (
    MACRO_SPECS,
    FredApiSource,
    FredCsvSource,
    MacroSpec,
    ProxySource,
    parse_fred_csv,
)
from qrd.ingest.pipeline import update_macro
from qrd.ingest.resilience import RunLog, SourceError, Status
from qrd.storage import ParquetStore
from tests.helpers import FakePriceSource, make_bars, read_required

SPEC = MacroSpec("ust_10y", "DGS10", "^TNX", 1, "10y")
NOW = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)

CSV = "observation_date,DGS10\n2024-12-26,4.58\n2024-12-27,.\n2024-12-30,4.55\n"


def test_parse_fred_csv_handles_missing_marker_and_lag() -> None:
    df = parse_fred_csv(CSV, SPEC, "fred_csv", date(2024, 1, 1))
    assert df["obs_date"].tolist() == [pd.Timestamp("2024-12-26"), pd.Timestamp("2024-12-30")]
    # Friday 12-26 + 1 business day = Friday 12-27; Monday 12-30 → Tuesday 12-31
    assert df["available_date"].tolist() == [pd.Timestamp("2024-12-27"), pd.Timestamp("2024-12-31")]
    assert (df["available_date"] > df["obs_date"]).all()
    assert not df["is_proxy"].any()


def test_parse_fred_csv_bad_layout() -> None:
    with pytest.raises(SourceError):
        parse_fred_csv("just_one_column\n1\n", SPEC, "fred_csv", date(2024, 1, 1))


def test_fred_api_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    src = FredApiSource("k", attempts=1)
    payload = {
        "observations": [
            {"date": "2024-12-30", "value": "4.55"},
            {"date": "2024-12-31", "value": "."},
        ]
    }

    def fake_get(fred_id: str, start: date) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(src, "_get", fake_get)
    df = src.fetch(SPEC, date(2024, 1, 1))
    assert df["value"].tolist() == [4.55]
    assert df["source"].iloc[0] == "fred_api"


def test_proxy_source_marks_proxy_and_has_no_lag() -> None:
    bars = make_bars("^TNX", start="2024-12-02", periods=20, price=4.5)
    df = ProxySource(FakePriceSource("yf", {"^TNX": bars})).fetch(
        SPEC, date(2024, 1, 1), date(2025, 1, 1)
    )
    assert df["is_proxy"].all()
    assert (df["available_date"] == df["obs_date"]).all()  # close known at the close


def test_gold_has_no_fred_series_so_yfinance_is_not_a_proxy() -> None:
    gold = next(s for s in MACRO_SPECS if s.series == "gold")
    bars = make_bars("GC=F", start="2024-12-02", periods=5, price=2600)
    df = ProxySource(FakePriceSource("yf", {"GC=F": bars})).fetch(
        gold, date(2024, 1, 1), date(2025, 1, 1)
    )
    assert not df["is_proxy"].any()


class _Csv(FredCsvSource):
    def __init__(self, text: str | None) -> None:
        super().__init__(attempts=1)
        self.text = text

    def _get(self, fred_id: str, start: date) -> str:
        if self.text is None:
            raise ConnectionError("fred down")
        return self.text


def _proxy() -> ProxySource:
    bars = make_bars("^TNX", start="2024-12-02", periods=20, price=4.5)
    return ProxySource(FakePriceSource("yf", {"^TNX": bars}))


def test_update_macro_primary_then_fallback(tmp_path: Path) -> None:
    store, rl = ParquetStore(tmp_path), RunLog()
    update_macro([SPEC], store, {SPEC.series: [_Csv(CSV), _proxy()]}, rl, NOW)
    assert rl.events[-1].status == Status.OK

    other = ParquetStore(tmp_path / "other")
    rl2 = RunLog()
    update_macro([SPEC], other, {SPEC.series: [_Csv(None), _proxy()]}, rl2, NOW)
    assert rl2.events[-1].status == Status.FALLBACK
    stored = other.read("macro", SPEC.series)
    assert stored is not None
    assert stored["is_proxy"].all()


def test_proxy_never_overwrites_stored_fred_series(tmp_path: Path) -> None:
    store, rl = ParquetStore(tmp_path), RunLog()
    update_macro([SPEC], store, {SPEC.series: [_Csv(CSV)]}, rl, NOW)
    before = read_required(store, "macro", SPEC.series)
    update_macro([SPEC], store, {SPEC.series: [_Csv(None), _proxy()]}, rl, NOW)
    assert rl.events[-1].status == Status.DEGRADED
    pd.testing.assert_frame_equal(read_required(store, "macro", SPEC.series), before)


def test_update_macro_total_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    rl = RunLog()
    update_macro([SPEC], ParquetStore(tmp_path), {SPEC.series: [_Csv(None)]}, rl, NOW)
    assert rl.events[-1].status == Status.FAILED
    assert "fred down" in rl.events[-1].message


def test_every_spec_has_some_source_and_sane_lag() -> None:
    for spec in MACRO_SPECS:
        assert spec.fred_id or spec.proxy_ticker, spec.series
        assert 0 <= spec.fred_lag_bdays <= 10


def test_update_macro_drops_partial_session_from_proxy(tmp_path: Path) -> None:
    # A proxy close for "today" fetched before the session is final is an intraday price:
    # storing it would leak a non-final value. Mirrors the rule applied to price bars.
    gold = next(s for s in MACRO_SPECS if s.series == "gold")
    bars = make_bars("GC=F", start="2024-12-02", periods=10, price=2600)  # to 2024-12-13
    src = ProxySource(FakePriceSource("yf", {"GC=F": bars}))
    store, rl = ParquetStore(tmp_path), RunLog()
    midday = datetime(2024, 12, 13, 18, 0, tzinfo=UTC)  # 13:00 New York, market open
    update_macro([gold], store, {gold.series: [src]}, rl, midday)
    stored = read_required(store, "macro", gold.series)
    assert stored["obs_date"].max() == pd.Timestamp("2024-12-12")

    after_close = datetime(2024, 12, 13, 23, 0, tzinfo=UTC)  # 18:00 New York
    update_macro([gold], store, {gold.series: [src]}, rl, after_close)
    assert read_required(store, "macro", gold.series)["obs_date"].max() == pd.Timestamp(
        "2024-12-13"
    )

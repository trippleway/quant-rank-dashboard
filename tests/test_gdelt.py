"""GDELT tone adapter: parsing, throttling responses, degradation (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from qrd.ingest.gdelt import GdeltToneSource, ToneQuery, parse_tone_payload
from qrd.ingest.pipeline import update_sentiment
from qrd.ingest.resilience import RunLog, SourceError, Status
from qrd.storage import ParquetStore

TQ = ToneQuery("gdelt_tone_test", "economy")


def _payload(days: list[str]) -> dict[str, Any]:
    data = []
    for d in days:
        data += [{"date": f"{d}T000000Z", "value": -1.0}, {"date": f"{d}T120000Z", "value": -3.0}]
    return {"timeline": [{"series": "Average Tone", "data": data}]}


def test_parse_collapses_to_daily_mean_with_next_bday_availability() -> None:
    df = parse_tone_payload(_payload(["20241227", "20241230"]), TQ.series, "gdelt_doc")
    assert df["value"].tolist() == [-2.0, -2.0]
    assert df["available_date"].tolist() == [pd.Timestamp("2024-12-30"), pd.Timestamp("2024-12-31")]


def test_parse_empty_timeline_raises() -> None:
    with pytest.raises(SourceError):
        parse_tone_payload({}, TQ.series, "gdelt_doc")


class _Fake(GdeltToneSource):
    def __init__(self, payload: dict[str, Any] | None) -> None:
        super().__init__(attempts=1, min_interval_s=0, sleep=lambda _s: None)
        self.payload = payload

    def _get(self, query: str) -> dict[str, Any]:
        if self.payload is None:
            raise SourceError("GDELT non-JSON response: 'Please limit requests'")
        return self.payload


def test_update_sentiment_drops_partial_utc_day_and_appends(tmp_path: Path) -> None:
    store, rl = ParquetStore(tmp_path), RunLog()
    now = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)
    update_sentiment([TQ], store, _Fake(_payload(["20241227", "20241230", "20241231"])), rl, now)
    stored = store.read("sentiment", TQ.series)
    assert stored is not None
    assert stored["obs_date"].max() == pd.Timestamp("2024-12-30")  # 12-31 still in progress

    later = datetime(2025, 1, 2, 22, 0, tzinfo=UTC)
    update_sentiment([TQ], store, _Fake(_payload(["20241231", "20250101"])), rl, later)
    stored = store.read("sentiment", TQ.series)
    assert stored is not None
    assert stored["obs_date"].dt.strftime("%m-%d").tolist() == ["12-27", "12-30", "12-31", "01-01"]


def test_update_sentiment_failure_degrades(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    now = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)
    first, second = RunLog(), RunLog()
    update_sentiment([TQ], store, _Fake(None), first, now)
    assert first.events[-1].status == Status.FAILED
    update_sentiment([TQ], store, _Fake(_payload(["20241227"])), second, now)
    update_sentiment([TQ], store, _Fake(None), second, now)
    assert [e.status for e in second.events] == [Status.OK, Status.DEGRADED]

"""Storage (Parquet + DuckDB), retries and the run log."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from qrd.ingest.resilience import RunLog, SourceError, Status, retry_call
from qrd.storage import ParquetStore, file_key
from tests.helpers import make_bars, read_required


def test_file_key_is_filesystem_safe_and_distinct() -> None:
    keys = {file_key(t) for t in ["^VIX", "BRK-B", "GC=F", "DX-Y.NYB", "VIX"]}
    assert len(keys) == 5
    assert all("/" not in k and "^" not in k and "=" not in k for k in keys)


def test_roundtrip_and_duckdb_view(tmp_path: Path) -> None:
    store = ParquetStore(tmp_path)
    a, b = make_bars("AAA", periods=5), make_bars("BRK-B", periods=7)
    store.write("prices", "AAA", a)
    store.write("prices", "BRK-B", b)
    pd.testing.assert_frame_equal(read_required(store, "prices", "AAA"), a)
    assert store.read("prices", "MISSING") is None
    assert not list((tmp_path / "prices").glob("*.tmp"))  # atomic write leaves no temp file

    rows = (
        store.connect().sql("SELECT ticker, count(*) FROM prices GROUP BY 1 ORDER BY 1").fetchall()
    )
    assert rows == [("AAA", 5), ("BRK-B", 7)]


def test_retry_eventually_succeeds_with_backoff() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"

    assert retry_call(flaky, attempts=3, backoff_s=0.5, sleep=sleeps.append) == "ok"
    assert sleeps == [0.5, 1.0]


def test_retry_gives_up_with_source_error() -> None:
    def down() -> None:
        raise TimeoutError("timeout")

    with pytest.raises(SourceError, match="after 2 attempts") as exc:
        retry_call(down, attempts=2, sleep=lambda _s: None)
    assert isinstance(exc.value.__cause__, TimeoutError)


def test_retry_does_not_swallow_unlisted_errors() -> None:
    def bug() -> None:
        raise KeyError("x")

    with pytest.raises(KeyError):
        retry_call(bug, retry_on=(ConnectionError,), sleep=lambda _s: None)


def test_run_log_summary_and_file(tmp_path: Path) -> None:
    rl = RunLog()
    rl.record("prices", "A", Status.OK, source="yfinance", rows=10)
    rl.record("prices", "B", Status.DEGRADED, source=None, message="down")
    rl.record("macro", "vix", Status.FALLBACK, source="yfinance_proxy")
    path = rl.write(tmp_path, "20240101T000000Z")
    data = json.loads(path.read_text())
    assert data["summary"]["prices"] == {"ok": 1, "fallback": 0, "degraded": 1, "failed": 0}
    assert data["events"][1]["message"] == "down"

"""Retries and a structured run log shared by all data adapters.

Every external call is wrapped in :func:`retry_call` (bounded attempts, exponential
backoff) and every outcome — success, fallback, degradation, failure — is recorded in a
:class:`RunLog` that is written to ``data/logs/`` so a failed day can be diagnosed later.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TypeVar

log = logging.getLogger("qrd.ingest")

T = TypeVar("T")

DEFAULT_TIMEOUT_S = 20.0


class SourceError(RuntimeError):
    """A data source could not deliver usable data (after retries)."""


class Status(StrEnum):
    OK = "ok"  # primary source delivered
    FALLBACK = "fallback"  # a backup source delivered
    DEGRADED = "degraded"  # no source delivered; stale cached data kept
    FAILED = "failed"  # no source delivered and nothing cached


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    backoff_s: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    label: str = "call",
) -> T:
    """Call ``fn`` up to ``attempts`` times with exponential backoff.

    Raises :class:`SourceError` (chained to the last exception) when all attempts fail.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            log.warning("%s failed (attempt %d/%d): %s", label, i + 1, attempts, exc)
            if i + 1 < attempts:
                sleep(backoff_s * (2**i))
    raise SourceError(f"{label} failed after {attempts} attempts: {last}") from last


@dataclass
class Event:
    dataset: str  # "prices" | "macro" | "sentiment" | ...
    key: str  # ticker / series id / query name
    status: Status
    source: str | None  # source that delivered, if any
    message: str = ""
    rows: int = 0


@dataclass
class RunLog:
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    events: list[Event] = field(default_factory=list)

    def record(
        self,
        dataset: str,
        key: str,
        status: Status,
        *,
        source: str | None,
        message: str = "",
        rows: int = 0,
    ) -> None:
        self.events.append(Event(dataset, key, status, source, message, rows))
        level = logging.INFO if status in (Status.OK, Status.FALLBACK) else logging.WARNING
        log.log(level, "[%s] %s: %s via %s %s", dataset, key, status, source, message)

    def counts(self, dataset: str | None = None) -> dict[str, int]:
        out = {s.value: 0 for s in Status}
        for e in self.events:
            if dataset is None or e.dataset == dataset:
                out[e.status.value] += 1
        return out

    def to_dict(self) -> dict[str, object]:
        datasets = sorted({e.dataset for e in self.events})
        return {
            "started_at": self.started_at,
            "summary": {d: self.counts(d) for d in datasets},
            "events": [asdict(e) for e in self.events],
        }

    def write(self, logs_dir: Path, stamp: str) -> Path:
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / f"ingest-{stamp}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

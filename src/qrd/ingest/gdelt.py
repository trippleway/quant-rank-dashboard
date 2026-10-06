"""GDELT DOC 2.0 average-tone timelines — a *proxy* for the international news climate.

Limitations (also in docs/data-dictionary.md):

* The DOC API only covers a rolling ~3-month window, so history accumulates in our
  cache day by day; there is no 5-year GDELT history for backtests at this stage.
* Tone measures the wording of news coverage, not "geopolitical risk" itself.
* The API rate-limits aggressively (≈1 request / 5 s) and answers with plain text when
  throttled; we space requests and treat any non-JSON answer as a failure.

Output schema::

    obs_date, available_date, series, value, source
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests

from qrd.ingest.resilience import DEFAULT_TIMEOUT_S, SourceError, retry_call

SENTIMENT_COLUMNS = ["obs_date", "available_date", "series", "value", "source"]


@dataclass(frozen=True)
class ToneQuery:
    series: str
    query: str


TONE_QUERIES: tuple[ToneQuery, ...] = (
    ToneQuery("gdelt_tone_economy", "(economy OR inflation OR recession) sourcelang:english"),
    ToneQuery(
        "gdelt_tone_geopolitics",
        "(war OR sanctions OR military OR conflict) sourcelang:english",
    ),
)


class GdeltToneSource:
    name = "gdelt_doc"
    URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        attempts: int = 3,
        min_interval_s: float = 6.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout_s = timeout_s
        self.attempts = attempts
        self.min_interval_s = min_interval_s
        self.sleep = sleep
        self._last_call = 0.0

    def _get(self, query: str) -> dict[str, Any]:
        wait = self.min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            self.sleep(wait)
        self._last_call = time.monotonic()
        resp = requests.get(
            self.URL,
            params={
                "query": query,
                "mode": "timelinetone",
                "format": "json",
                "timespan": "3months",
                "timelinesmooth": "0",
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        try:
            payload: dict[str, Any] = resp.json()
        except ValueError as exc:  # throttled: plain-text answer
            raise SourceError(f"GDELT non-JSON response: {resp.text[:120]!r}") from exc
        return payload

    def fetch(self, tq: ToneQuery) -> pd.DataFrame:
        payload = retry_call(
            lambda: self._get(tq.query),
            attempts=self.attempts,
            backoff_s=self.min_interval_s,
            sleep=self.sleep,
            label=f"gdelt {tq.series}",
        )
        return parse_tone_payload(payload, tq.series, self.name)


def parse_tone_payload(payload: dict[str, Any], series: str, source: str) -> pd.DataFrame:
    timeline = payload.get("timeline") or []
    if not timeline or not timeline[0].get("data"):
        raise SourceError(f"GDELT returned no timeline for {series}")
    points = timeline[0]["data"]
    stamps = pd.to_datetime([p["date"] for p in points], format="%Y%m%dT%H%M%SZ", utc=True)
    df = pd.DataFrame({"ts": stamps, "value": [float(p["value"]) for p in points]})
    # Collapse to a daily mean in UTC. A day's tone is complete only after that UTC day
    # ends, so it becomes usable on the next business day.
    df["obs_date"] = df["ts"].dt.tz_localize(None).dt.normalize()
    daily = df.groupby("obs_date")["value"].mean().reset_index()
    daily["obs_date"] = daily["obs_date"].astype("datetime64[ns]")
    daily["available_date"] = (daily["obs_date"] + pd.offsets.BDay(1)).astype("datetime64[ns]")
    daily["series"] = series
    daily["source"] = source
    return daily[SENTIMENT_COLUMNS]

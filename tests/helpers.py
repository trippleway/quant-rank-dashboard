"""Shared test helpers (import as ``tests.helpers``).

All price data produced here is SYNTHETIC FIXTURE data for tests only — it is never
written outside pytest's temporary directories and never published.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd

from qrd.ingest.prices import PRICE_COLUMNS
from qrd.ingest.resilience import SourceError

FIXTURE_SOURCE = "FIXTURE"


def make_bars(
    ticker: str,
    start: str = "2024-01-02",
    periods: int = 300,
    *,
    seed: int = 0,
    price: float = 100.0,
    volume: float = 1_000_000.0,
    source: str = FIXTURE_SOURCE,
) -> pd.DataFrame:
    """Synthetic business-day bars (FIXTURE) with consistent OHLC."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=periods)
    close = price * np.exp(np.cumsum(rng.normal(0, 0.01, periods)))
    open_ = close * (1 + rng.normal(0, 0.002, periods))
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    df = pd.DataFrame(
        {
            "date": dates.astype("datetime64[ns]"),
            "ticker": ticker,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": np.full(periods, volume),
            "source": source,
        }
    )
    return df[PRICE_COLUMNS]


class FakePriceSource:
    """In-memory PriceSource that serves FIXTURE bars and records each request."""

    def __init__(
        self,
        name: str,
        data: dict[str, pd.DataFrame] | None = None,
        *,
        fail: bool = False,
        crash: bool = False,
    ) -> None:
        self.name = name
        self.data = data or {}
        self.fail = fail
        self.crash = crash
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def fetch(self, tickers: Sequence[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        self.calls.append((tuple(tickers), start, end))
        if self.crash:
            raise ZeroDivisionError("adapter bug")
        if self.fail:
            raise SourceError(f"{self.name} down")
        out = {}
        for t in tickers:
            if t in self.data:
                df = self.data[t]
                sel = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] < pd.Timestamp(end))]
                if not sel.empty:
                    out[t] = sel.assign(source=self.name).reset_index(drop=True)
        return out


def read_required(store: object, kind: str, name: str) -> pd.DataFrame:
    """``ParquetStore.read`` that fails the test instead of returning None."""
    from qrd.storage import ParquetStore  # noqa: PLC0415

    assert isinstance(store, ParquetStore)
    df = store.read(kind, name)
    assert df is not None, f"{kind}/{name} not stored"
    return df

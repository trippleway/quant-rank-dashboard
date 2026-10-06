"""Price adapters: parsing vendor payloads into canonical bars (no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qrd.ingest.prices import (
    PRICE_COLUMNS,
    YahooChartSource,
    YFinanceSource,
    drop_incomplete_session,
    parse_chart_payload,
    split_yfinance_frame,
)
from qrd.ingest.resilience import SourceError
from tests.helpers import make_bars


def _yf_frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex(["2026-10-01", "2026-10-02"], name="Date")
    cols = pd.MultiIndex.from_product(
        [["AAA", "DEAD"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]],
        names=["Ticker", "Price"],
    )
    values = np.array(
        [
            [10, 11, 9, 10.5, 10.4, 1000] + [np.nan] * 6,
            [10.5, 12, 10, 11.5, 11.4, 2000] + [np.nan] * 6,
        ]
    )
    return pd.DataFrame(values, index=idx, columns=cols)


def test_split_yfinance_frame_drops_empty_tickers() -> None:
    out = split_yfinance_frame(_yf_frame(), ["AAA", "DEAD", "ABSENT"], "yfinance")
    assert list(out) == ["AAA"]
    aaa = out["AAA"]
    assert list(aaa.columns) == PRICE_COLUMNS
    assert aaa["adj_close"].tolist() == [10.4, 11.4]
    assert aaa["date"].dtype == "datetime64[ns]"


def test_split_yfinance_frame_rejects_flat_layout() -> None:
    flat = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2026-10-01"]))
    with pytest.raises(SourceError):
        split_yfinance_frame(flat, ["AAA"], "yfinance")


def _chart_payload(adj: bool = True) -> dict[str, Any]:
    # 2026-10-01 and 2026-10-02 09:30 New York in epoch seconds
    stamps = [1790861400, 1790947800]
    indicators: dict[str, Any] = {
        "quote": [
            {
                "open": [10.0, 10.5],
                "high": [11.0, 12.0],
                "low": [9.0, 10.0],
                "close": [10.5, None],  # vendor gap → row dropped
                "volume": [1000, 2000],
            }
        ]
    }
    if adj:
        indicators["adjclose"] = [{"adjclose": [10.4, None]}]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"exchangeTimezoneName": "America/New_York"},
                    "timestamp": stamps,
                    "indicators": indicators,
                }
            ],
            "error": None,
        }
    }


def test_parse_chart_payload_uses_exchange_dates() -> None:
    bars = parse_chart_payload(_chart_payload(), "AAA", "yahoo_chart")
    assert bars["date"].tolist() == [pd.Timestamp("2026-10-01")]
    assert bars.loc[0, "adj_close"] == 10.4


def test_parse_chart_payload_without_adjclose_leaves_nan() -> None:
    bars = parse_chart_payload(_chart_payload(adj=False), "AAA", "yahoo_chart")
    assert bars["adj_close"].isna().all()  # never silently substitute close


def test_parse_chart_payload_error_raises() -> None:
    with pytest.raises(ValueError, match="chart error"):
        parse_chart_payload({"chart": {"result": None, "error": {"code": "Not Found"}}}, "X", "y")


@pytest.mark.parametrize(
    ("utc_hour", "last_kept"),
    [(20, "2024-12-30"), (22, "2024-12-31")],  # 15:00 vs 17:00 New York
)
def test_drop_incomplete_session(utc_hour: int, last_kept: str) -> None:
    bars = make_bars("X", start="2024-12-23", periods=8)  # up to 2025-01-01 (future)
    now = datetime(2024, 12, 31, utc_hour, 0, tzinfo=UTC)
    out = drop_incomplete_session(bars, now)
    assert out["date"].max() == pd.Timestamp(last_kept)


def test_yfinance_source_isolates_failing_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    src = YFinanceSource(batch_size=1, attempts=1)

    def fake_download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
        if tickers == ["DEAD"]:
            raise ConnectionError("boom")
        return _yf_frame()

    monkeypatch.setattr(src, "_download", fake_download)
    out = src.fetch(["AAA", "DEAD"], date(2026, 10, 1), date(2026, 10, 3))
    assert list(out) == ["AAA"]


def test_yfinance_source_total_outage_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    src = YFinanceSource(attempts=1)

    def fake_download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
        raise ConnectionError("down")

    monkeypatch.setattr(src, "_download", fake_download)
    with pytest.raises(SourceError):
        src.fetch(["AAA"], date(2026, 10, 1), date(2026, 10, 3))


def test_chart_source_partial_and_total_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    src = YahooChartSource(attempts=1)

    def fake_get(ticker: str, start: date, end: date) -> dict[str, Any]:
        if ticker == "DEAD":
            raise ConnectionError("404")
        return _chart_payload()

    monkeypatch.setattr(src, "_get", fake_get)
    assert list(src.fetch(["AAA", "DEAD"], date(2026, 10, 1), date(2026, 10, 3))) == ["AAA"]
    with pytest.raises(SourceError):
        src.fetch(["DEAD"], date(2026, 10, 1), date(2026, 10, 3))

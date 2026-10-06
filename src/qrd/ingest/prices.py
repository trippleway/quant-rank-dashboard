"""Daily price adapters.

Primary: the ``yfinance`` library (batched downloads). Backup: Yahoo's public chart
endpoint called directly over HTTP — same upstream, but an independent code path that
survives ``yfinance`` breakages. If both fail, the pipeline keeps the cached data and
marks the ticker as degraded (see :mod:`qrd.ingest.pipeline`).

Canonical bar schema (one row per ticker per session)::

    date (datetime64, exchange session date, tz-naive), ticker, open, high, low, close,
    adj_close, volume, source
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import Any, ClassVar, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from qrd.ingest.resilience import DEFAULT_TIMEOUT_S, SourceError, retry_call

log = logging.getLogger("qrd.ingest.prices")

PRICE_COLUMNS = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "source"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]

NY = ZoneInfo("America/New_York")
# Bars dated "today" are only trusted after this New York time (regular close 16:00 plus
# a buffer for the closing auction / vendor finalisation). Earlier, today's bar is partial.
SESSION_FINAL_AFTER = time(17, 0)

_YF_FIELDS = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


class PriceSource(Protocol):
    name: str

    def fetch(self, tickers: Sequence[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        """Return canonical bars per ticker for ``start <= date < end``.

        Tickers with no data are omitted. Raises :class:`SourceError` when the source as a
        whole is unavailable.
        """
        ...


def empty_bars() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype="float64") for c in PRICE_COLUMNS})
    df["date"] = pd.Series(dtype="datetime64[ns]")
    df["ticker"] = pd.Series(dtype="object")
    df["source"] = pd.Series(dtype="object")
    return df[PRICE_COLUMNS]


def normalize_bars(raw: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    """Coerce a frame with OHLCV columns (index or ``date`` column) into canonical bars."""
    df = raw.copy()
    if "date" not in df.columns:
        df = df.rename_axis("date").reset_index()
    df["date"] = pd.to_datetime(df["date"])
    if getattr(df["date"].dt, "tz", None) is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df["date"] = df["date"].dt.normalize().astype("datetime64[ns]")
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        else:
            df[col] = float("nan")
    df["ticker"] = ticker
    df["source"] = source
    df = df.dropna(subset=["close"])
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date")
    return df[PRICE_COLUMNS].reset_index(drop=True)


def session_cutoff(now: datetime) -> pd.Timestamp:
    """First session date that may not be final yet: bars dated ``>=`` this are dropped."""
    ny_now = now.astimezone(NY)
    today = pd.Timestamp(ny_now.date())
    return today if ny_now.time() < SESSION_FINAL_AFTER else today + pd.Timedelta(days=1)


def drop_incomplete_session(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Drop bars that may still change: future dates, and today's bar before it is final."""
    if df.empty:
        return df
    return df[df["date"] < session_cutoff(now)].reset_index(drop=True)


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


class YFinanceSource:
    name = "yfinance"

    def __init__(
        self, *, batch_size: int = 50, timeout_s: float = DEFAULT_TIMEOUT_S, attempts: int = 3
    ) -> None:
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.attempts = attempts

    def _download(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        import yfinance as yf  # noqa: PLC0415 — heavy import, only when actually fetching

        frame = yf.download(
            tickers,
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            actions=False,
            group_by="ticker",
            threads=True,
            progress=False,
            timeout=self.timeout_s,
            multi_level_index=True,
        )
        if not isinstance(frame, pd.DataFrame):
            raise SourceError(f"yfinance returned {type(frame).__name__}")
        return frame

    def fetch(self, tickers: Sequence[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        errors: list[str] = []
        for batch in _chunks(tickers, self.batch_size):
            try:
                frame = retry_call(
                    partial(self._download, batch, start, end),
                    attempts=self.attempts,
                    label=f"yfinance batch[{batch[0]}..{batch[-1]}]",
                )
            except SourceError as exc:
                errors.append(str(exc))
                continue
            out.update(split_yfinance_frame(frame, batch, self.name))
        if errors and not out:
            raise SourceError("; ".join(errors))
        return out


def split_yfinance_frame(
    frame: pd.DataFrame, tickers: Sequence[str], source: str
) -> dict[str, pd.DataFrame]:
    """Split a ``group_by='ticker'`` multi-index download into canonical frames."""
    out: dict[str, pd.DataFrame] = {}
    if frame.empty:
        return out
    if not isinstance(frame.columns, pd.MultiIndex):
        raise SourceError("unexpected yfinance frame layout (expected MultiIndex columns)")
    present = set(frame.columns.get_level_values(0))
    for ticker in tickers:
        if ticker not in present:
            continue
        sub = pd.DataFrame(frame[ticker]).rename(columns=_YF_FIELDS)
        bars = normalize_bars(sub, ticker, source)
        if not bars.empty:
            out[ticker] = bars
    return out


class YahooChartSource:
    """Direct HTTP access to Yahoo's v8 chart endpoint (one request per ticker)."""

    name = "yahoo_chart"
    URL = "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
    HEADERS: ClassVar[dict[str, str]] = {"User-Agent": "Mozilla/5.0 (compatible; qrd-research/0.1)"}

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        attempts: int = 2,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self.attempts = attempts
        self.session = session or requests.Session()

    def _get(self, ticker: str, start: date, end: date) -> dict[str, Any]:
        t0 = int(datetime.combine(start, time(0), NY).timestamp())
        t1 = int(datetime.combine(end, time(0), NY).timestamp())
        resp = self.session.get(
            self.URL.format(ticker=ticker),
            params={
                "period1": str(t0),
                "period2": str(t1),
                "interval": "1d",
                "events": "div,split",
                "includeAdjustedClose": "true",
            },
            headers=self.HEADERS,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        return payload

    def fetch(self, tickers: Sequence[str], start: date, end: date) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        failures = 0
        for ticker in tickers:
            try:
                payload = retry_call(
                    partial(self._get, ticker, start, end),
                    attempts=self.attempts,
                    label=f"yahoo_chart {ticker}",
                )
                bars = parse_chart_payload(payload, ticker, self.name)
            except (SourceError, ValueError, KeyError, TypeError, IndexError) as exc:
                failures += 1
                log.warning("yahoo_chart %s: %s", ticker, exc)
                continue
            if not bars.empty:
                out[ticker] = bars
        if tickers and failures == len(tickers):
            raise SourceError(f"yahoo_chart failed for all {failures} tickers")
        return out


def parse_chart_payload(payload: dict[str, Any], ticker: str, source: str) -> pd.DataFrame:
    chart = payload["chart"]
    if chart.get("error"):
        raise ValueError(f"chart error: {chart['error']}")
    result = chart["result"][0]
    stamps = result.get("timestamp") or []
    if not stamps:
        return empty_bars()
    tz = ZoneInfo(result["meta"].get("exchangeTimezoneName") or "America/New_York")
    quote = result["indicators"]["quote"][0]
    adj = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    dates = [datetime.fromtimestamp(s, tz).date() for s in stamps]
    raw = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
            # No adjusted series → leave NaN (flagged by quality checks), never guess.
            "adj_close": adj if adj is not None else [float("nan")] * len(stamps),
            "volume": quote.get("volume"),
        }
    )
    return normalize_bars(raw, ticker, source)


def default_end(now: datetime) -> date:
    """Exclusive end date for requests: tomorrow in New York (partial bars dropped later)."""
    return now.astimezone(NY).date() + timedelta(days=1)

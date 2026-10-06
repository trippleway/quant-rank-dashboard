"""Macro series adapters with an ordered fallback chain.

For each series we try, in order:

1. FRED JSON API (only when ``FRED_API_KEY`` is set)
2. FRED public ``fredgraph.csv`` download (no key needed)
3. A yfinance proxy ticker (e.g. ``^TNX`` for the 10y yield) — marked ``is_proxy``

Output schema (one row per observation)::

    obs_date, available_date, series, value, source, is_proxy

``available_date`` is the first session on which the value may be used without
look-ahead: ``obs_date`` plus a per-series publication lag in business days. Feature code
(M2) must join on ``available_date``, never on ``obs_date``.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import requests

from qrd.ingest.prices import PriceSource
from qrd.ingest.resilience import DEFAULT_TIMEOUT_S, SourceError, retry_call

log = logging.getLogger("qrd.ingest.macro")

MACRO_COLUMNS = ["obs_date", "available_date", "series", "value", "source", "is_proxy"]


@dataclass(frozen=True)
class MacroSpec:
    series: str  # our id
    fred_id: str | None
    proxy_ticker: str | None  # yfinance ticker used as a proxy when FRED is unavailable
    fred_lag_bdays: int  # publication lag of the FRED series
    description: str


# Lags are deliberately conservative. H.15 yields / VIXCLS / ICE OAS: published the next
# business day. H.10 broad dollar (weekly, Monday) and EIA WTI spot (weekly): up to ~7.
MACRO_SPECS: tuple[MacroSpec, ...] = (
    MacroSpec("ust_3m", "DGS3MO", "^IRX", 1, "3-month Treasury constant maturity yield (%)"),
    MacroSpec("ust_2y", "DGS2", None, 1, "2-year Treasury constant maturity yield (%)"),
    MacroSpec("ust_5y", "DGS5", "^FVX", 1, "5-year Treasury constant maturity yield (%)"),
    MacroSpec("ust_10y", "DGS10", "^TNX", 1, "10-year Treasury constant maturity yield (%)"),
    MacroSpec("ust_30y", "DGS30", "^TYX", 1, "30-year Treasury constant maturity yield (%)"),
    MacroSpec("curve_10y2y", "T10Y2Y", None, 1, "10y minus 2y Treasury spread (pp)"),
    MacroSpec("breakeven_10y", "T10YIE", None, 1, "10-year breakeven inflation (%)"),
    MacroSpec("hy_oas", "BAMLH0A0HYM2", None, 1, "ICE BofA US High Yield OAS (%)"),
    MacroSpec("ig_oas", "BAMLC0A0CM", None, 1, "ICE BofA US Corporate (IG) OAS (%)"),
    MacroSpec("vix", "VIXCLS", "^VIX", 1, "CBOE VIX close"),
    MacroSpec("usd_broad", "DTWEXBGS", "DX-Y.NYB", 7, "Broad USD index (proxy: ICE DXY)"),
    MacroSpec("wti", "DCOILWTICO", "CL=F", 7, "WTI crude spot $/bbl (proxy: front future)"),
    MacroSpec("gold", None, "GC=F", 0, "Gold front-month future $/oz (yfinance only)"),
)


def with_available_date(df: pd.DataFrame, lag_bdays: int) -> pd.DataFrame:
    out = df.copy()
    offset = pd.offsets.BDay(lag_bdays)
    out["available_date"] = (out["obs_date"] + offset).astype("datetime64[ns]")
    return out


def _frame(
    dates: Iterable[Any], values: Iterable[Any], spec: MacroSpec, source: str, proxy: bool
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(list(dates)).astype("datetime64[ns]"),
            "value": pd.to_numeric(pd.Series(list(values), dtype="object"), errors="coerce"),
        }
    )
    df = df.dropna(subset=["value"]).drop_duplicates("obs_date", keep="last")
    df = df.sort_values("obs_date").reset_index(drop=True)
    df["series"] = spec.series
    df["source"] = source
    df["is_proxy"] = proxy
    lag = spec.fred_lag_bdays if source.startswith("fred") else 0
    return with_available_date(df, lag)[MACRO_COLUMNS]


class FredApiSource:
    name = "fred_api"
    URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self, api_key: str, *, timeout_s: float = DEFAULT_TIMEOUT_S, attempts: int = 3
    ) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.attempts = attempts

    def _get(self, fred_id: str, start: date) -> dict[str, Any]:
        resp = requests.get(
            self.URL,
            params={
                "series_id": fred_id,
                "api_key": self.api_key,
                "file_type": "json",
                "observation_start": start.isoformat(),
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
        return payload

    def fetch(self, spec: MacroSpec, start: date) -> pd.DataFrame:
        if spec.fred_id is None:
            raise SourceError(f"{spec.series}: no FRED id")
        fred_id = spec.fred_id
        payload = retry_call(
            lambda: self._get(fred_id, start), attempts=self.attempts, label=f"fred_api {fred_id}"
        )
        obs = payload.get("observations", [])
        # FRED encodes missing values as "."; _frame coerces them to NaN and drops them.
        return _frame([o["date"] for o in obs], [o["value"] for o in obs], spec, self.name, False)


class FredCsvSource:
    name = "fred_csv"
    URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S, attempts: int = 3) -> None:
        self.timeout_s = timeout_s
        self.attempts = attempts

    def _get(self, fred_id: str, start: date) -> str:
        resp = requests.get(
            self.URL,
            params={"id": fred_id, "cosd": start.isoformat()},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return resp.text

    def fetch(self, spec: MacroSpec, start: date) -> pd.DataFrame:
        if spec.fred_id is None:
            raise SourceError(f"{spec.series}: no FRED id")
        fred_id = spec.fred_id
        text = retry_call(
            lambda: self._get(fred_id, start), attempts=self.attempts, label=f"fred_csv {fred_id}"
        )
        return parse_fred_csv(text, spec, self.name, start)


def parse_fred_csv(text: str, spec: MacroSpec, source: str, start: date) -> pd.DataFrame:
    raw = pd.read_csv(io.StringIO(text))
    if raw.shape[1] < 2:  # noqa: PLR2004
        raise SourceError(f"unexpected FRED CSV layout for {spec.fred_id}: {list(raw.columns)}")
    date_col, value_col = raw.columns[0], raw.columns[1]
    df = _frame(raw[date_col], raw[value_col], spec, source, False)
    return df[df["obs_date"] >= pd.Timestamp(start)].reset_index(drop=True)


class ProxySource:
    """Macro proxies from a price source (close of a yfinance ticker)."""

    name = "yfinance_proxy"

    def __init__(self, prices: PriceSource) -> None:
        self.prices = prices

    def fetch(self, spec: MacroSpec, start: date, end: date) -> pd.DataFrame:
        if spec.proxy_ticker is None:
            raise SourceError(f"{spec.series}: no proxy ticker")
        bars = self.prices.fetch([spec.proxy_ticker], start, end).get(spec.proxy_ticker)
        if bars is None or bars.empty:
            raise SourceError(f"{spec.series}: proxy {spec.proxy_ticker} returned no data")
        # gold has no FRED series, so its yfinance series is the primary, not a proxy.
        is_proxy = spec.fred_id is not None
        return _frame(bars["date"], bars["close"], spec, self.name, is_proxy)

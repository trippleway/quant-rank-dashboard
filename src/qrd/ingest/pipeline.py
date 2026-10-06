"""Ingest orchestration: incremental updates, fallback chains, quality checks, run log.

No single source failure aborts the run. Per item the outcome is one of
``ok`` / ``fallback`` / ``degraded`` (stale cache kept) / ``failed`` (nothing available),
all recorded in the :class:`~qrd.ingest.resilience.RunLog`.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from qrd.config import Settings
from qrd.ingest.gdelt import TONE_QUERIES, GdeltToneSource, ToneQuery
from qrd.ingest.macro import (
    MACRO_SPECS,
    FredApiSource,
    FredCsvSource,
    MacroSpec,
    ProxySource,
)
from qrd.ingest.prices import (
    PriceSource,
    YahooChartSource,
    YFinanceSource,
    default_end,
    drop_incomplete_session,
)
from qrd.ingest.quality import QualityIssue, check_bars, issues_frame, unusable_tickers
from qrd.ingest.resilience import RunLog, SourceError, Status
from qrd.storage import ParquetStore

log = logging.getLogger("qrd.ingest.pipeline")

# ~5y backtest + 12m momentum + 200d warm-up, with margin.
DEFAULT_HISTORY_YEARS = 7
# Re-download this many calendar days before the last cached bar on each incremental run,
# both to pick up vendor revisions and to detect dividend/split re-adjustments.
OVERLAP_DAYS = 14
# Relative tolerance when comparing cached vs fresh prices on overlapping sessions.
ADJ_TOLERANCE = 1e-4
CALENDAR_TICKER = "SPY"


@dataclass
class PriceUpdate:
    statuses: dict[str, Status] = field(default_factory=dict)
    refetched_full: list[str] = field(default_factory=list)
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def unusable(self) -> set[str]:
        return unusable_tickers(self.issues)

    def coverage(self) -> float:
        if not self.statuses:
            return 0.0
        have = sum(
            s in (Status.OK, Status.FALLBACK, Status.DEGRADED) for s in self.statuses.values()
        )
        return have / len(self.statuses)


def history_start(now: datetime, years: int = DEFAULT_HISTORY_YEARS) -> date:
    d = now.date()
    return d.replace(year=d.year - years, day=min(d.day, 28))


def _fetch_chain(
    sources: Sequence[PriceSource], tickers: Sequence[str], start: date, end: date
) -> dict[str, tuple[pd.DataFrame, str, int]]:
    """Try each source in order for the tickers still missing."""
    got: dict[str, tuple[pd.DataFrame, str, int]] = {}
    remaining = list(tickers)
    for rank, src in enumerate(sources):
        if not remaining:
            break
        try:
            fetched = src.fetch(remaining, start, end)
        except SourceError as exc:
            log.warning("price source %s failed for %d tickers: %s", src.name, len(remaining), exc)
            continue
        except Exception as exc:  # an adapter bug must not abort the whole run
            log.exception("price source %s raised unexpectedly: %s", src.name, exc)
            continue
        for ticker, bars in fetched.items():
            if ticker in remaining and not bars.empty:
                got[ticker] = (bars, src.name, rank)
        remaining = [t for t in remaining if t not in got]
    return got


def adjustment_changed(
    cached: pd.DataFrame, fresh: pd.DataFrame, tol: float = ADJ_TOLERANCE
) -> bool:
    """True if overlapping sessions disagree on close or adj_close.

    A new dividend rescales the whole adjusted history and a split restates closes, so
    an incremental append would splice two different adjustment bases together.
    """
    both = cached.merge(fresh, on="date", suffixes=("_old", "_new"))
    if both.empty:
        return False
    for col in ("close", "adj_close"):
        old, new = both[f"{col}_old"], both[f"{col}_new"]
        valid = old.notna() & new.notna()
        if not bool(valid.any()):
            continue
        rel = ((new[valid] - old[valid]).abs() / old[valid].abs()).max()
        if float(rel) > tol:
            return True
    return False


def _plan_requests(
    tickers: Sequence[str], store: ParquetStore, start_full: date, *, full: bool
) -> tuple[dict[str, pd.DataFrame], dict[date, list[str]]]:
    """Load caches and group tickers by request start date (incremental vs full)."""
    cached: dict[str, pd.DataFrame] = {}
    groups: dict[date, list[str]] = defaultdict(list)
    for ticker in tickers:
        frame = store.read("prices", ticker)
        if frame is None or frame.empty:
            groups[start_full].append(ticker)
            continue
        cached[ticker] = frame
        if full:
            groups[start_full].append(ticker)
        else:
            last = pd.Timestamp(frame["date"].max()).date()
            groups[max(start_full, last - timedelta(days=OVERLAP_DAYS))].append(ticker)
    return cached, groups


def _store_ticker(
    ticker: str,
    fetched: tuple[pd.DataFrame, str, int] | None,
    old: pd.DataFrame | None,
    *,
    store: ParquetStore,
    run_log: RunLog,
    now: datetime,
    note: str,
) -> Status:
    bars = None if fetched is None else drop_incomplete_session(fetched[0], now)
    if fetched is not None and bars is not None and not bars.empty:
        _, source, rank = fetched
        if old is not None:
            keep = old[old["date"] < bars["date"].min()]
            bars = pd.concat([keep, bars], ignore_index=True)
        store.write("prices", ticker, bars)
        status = Status.OK if rank == 0 else Status.FALLBACK
        run_log.record("prices", ticker, status, source=source, message=note, rows=len(bars))
        return status
    if old is not None:
        last = pd.Timestamp(old["date"].max()).date()
        msg = "no new bars" if fetched is not None else "all sources failed"
        status = Status.OK if fetched is not None else Status.DEGRADED
        run_log.record(
            "prices",
            ticker,
            status,
            source=fetched[1] if fetched is not None else None,
            message=f"{msg}; cache to {last}",
            rows=len(old),
        )
        return status
    run_log.record("prices", ticker, Status.FAILED, source=None, message="no data from any source")
    return Status.FAILED


def update_prices(
    tickers: Sequence[str],
    store: ParquetStore,
    sources: Sequence[PriceSource],
    run_log: RunLog,
    now: datetime,
    *,
    full: bool = False,
    years: int = DEFAULT_HISTORY_YEARS,
    leverage: dict[str, float] | None = None,
) -> PriceUpdate:
    result = PriceUpdate()
    start_full = history_start(now, years)
    end = default_end(now)
    cached, groups = _plan_requests(tickers, store, start_full, full=full)

    fetched: dict[str, tuple[pd.DataFrame, str, int]] = {}
    for start, members in sorted(groups.items()):
        fetched.update(_fetch_chain(sources, members, start, end))

    # Incremental merges whose overlap disagrees are re-downloaded in full.
    needs_full = [
        t
        for t, (bars, _, _) in fetched.items()
        if t in cached and adjustment_changed(cached[t], drop_incomplete_session(bars, now))
    ]
    if needs_full:
        log.info(
            "adjustment basis changed for %d tickers; refetching full history", len(needs_full)
        )
        refetched = _fetch_chain(sources, needs_full, start_full, end)
        for ticker in needs_full:
            if ticker in refetched:
                fetched[ticker] = refetched[ticker]
                result.refetched_full.append(ticker)
            else:
                fetched.pop(ticker)  # never splice mismatched bases; keep the stale cache

    for ticker in tickers:
        refetched_full = ticker in result.refetched_full
        # A full refetch replaces the history entirely instead of merging with the cache.
        old = None if refetched_full else cached.get(ticker)
        note = "full refetch (adjustment changed)" if refetched_full else ""
        result.statuses[ticker] = _store_ticker(
            ticker, fetched.get(ticker), old, store=store, run_log=run_log, now=now, note=note
        )

    result.issues = run_quality_checks(store, tickers, leverage or {})
    return result


def run_quality_checks(
    store: ParquetStore, tickers: Sequence[str], leverage: dict[str, float]
) -> list[QualityIssue]:
    ref = store.read("prices", CALENDAR_TICKER)
    calendar = pd.DatetimeIndex(ref["date"]).sort_values() if ref is not None else None
    issues: list[QualityIssue] = []
    for ticker in tickers:
        bars = store.read("prices", ticker)
        if bars is None:
            continue  # already recorded as FAILED in the run log
        issues.extend(check_bars(bars, ticker, calendar, leverage.get(ticker, 1.0)))
    return issues


def _macro_chain(spec: MacroSpec, settings: Settings, proxy: ProxySource) -> list[object]:
    chain: list[object] = []
    if spec.fred_id is not None:
        if settings.fred_api_key:
            chain.append(FredApiSource(settings.fred_api_key))
        chain.append(FredCsvSource())
    if spec.proxy_ticker is not None:
        chain.append(proxy)
    return chain


def update_macro(
    specs: Sequence[MacroSpec],
    store: ParquetStore,
    chains: dict[str, list[object]],
    run_log: RunLog,
    now: datetime,
    *,
    years: int = DEFAULT_HISTORY_YEARS,
) -> None:
    """Macro series are small, so each run refetches the full window and replaces the file.

    A proxy never overwrites a stored non-proxy series (different units / definitions);
    in that case the stale FRED series is kept and the item is marked degraded.
    """
    start = history_start(now, years)
    end = default_end(now)
    for spec in specs:
        data: pd.DataFrame | None = None
        used, rank, errors = "", -1, []
        for i, src in enumerate(chains.get(spec.series, [])):
            try:
                if isinstance(src, ProxySource):
                    data = src.fetch(spec, start, end)
                elif isinstance(src, (FredApiSource, FredCsvSource)):
                    data = src.fetch(spec, start)
                else:  # pragma: no cover - defensive
                    raise SourceError(f"unknown macro source {src!r}")
            except Exception as exc:
                errors.append(f"{getattr(src, 'name', src)}: {exc}")
                data = None
                continue
            if data is not None and not data.empty:
                used, rank = str(getattr(src, "name", "")), i
                break
        old = store.read("macro", spec.series)
        if data is None or data.empty:
            status = Status.DEGRADED if old is not None else Status.FAILED
            run_log.record(
                "macro", spec.series, status, source=None, message=" | ".join(errors)[:500]
            )
            continue
        if old is not None and bool(data["is_proxy"].any()) and not bool(old["is_proxy"].any()):
            run_log.record(
                "macro",
                spec.series,
                Status.DEGRADED,
                source=None,
                message=f"only proxy {used} available; kept stored FRED series",
            )
            continue
        store.write("macro", spec.series, data)
        status = Status.OK if rank == 0 else Status.FALLBACK
        run_log.record(
            "macro",
            spec.series,
            status,
            source=used,
            message="; ".join(errors)[:500],
            rows=len(data),
        )


def update_sentiment(
    queries: Sequence[ToneQuery],
    store: ParquetStore,
    source: GdeltToneSource,
    run_log: RunLog,
    now: datetime,
) -> None:
    today_utc = pd.Timestamp(now.astimezone(UTC).date())
    for tq in queries:
        old = store.read("sentiment", tq.series)
        try:
            fresh = source.fetch(tq)
        except Exception as exc:
            status = Status.DEGRADED if old is not None else Status.FAILED
            run_log.record("sentiment", tq.series, status, source=None, message=str(exc)[:500])
            continue
        fresh = fresh[fresh["obs_date"] < today_utc]  # today's UTC day is still partial
        if old is not None and not fresh.empty:
            keep = old[old["obs_date"] < fresh["obs_date"].min()]
            fresh = pd.concat([keep, fresh], ignore_index=True)
        store.write("sentiment", tq.series, fresh)
        run_log.record("sentiment", tq.series, Status.OK, source=source.name, rows=len(fresh))


@dataclass
class IngestSummary:
    prices: PriceUpdate
    run_log: RunLog
    log_path: str
    quality_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "price_coverage": round(self.prices.coverage(), 4),
            "tickers": len(self.prices.statuses),
            "unusable_tickers": sorted(self.prices.unusable),
            "refetched_full": sorted(self.prices.refetched_full),
            "summary": self.run_log.to_dict()["summary"],
            "log": self.log_path,
            "quality": self.quality_path,
        }


def run_ingest(
    settings: Settings,
    universe: pd.DataFrame,
    *,
    now: datetime | None = None,
    full: bool = False,
    price_sources: Sequence[PriceSource] | None = None,
    include_macro: bool = True,
    include_sentiment: bool = True,
) -> IngestSummary:
    now = now or datetime.now(UTC)
    store = ParquetStore(settings.data_dir)
    run_log = RunLog()
    sources: list[PriceSource] = (
        list(price_sources) if price_sources is not None else [YFinanceSource(), YahooChartSource()]
    )
    tickers = universe["ticker"].tolist()
    if CALENDAR_TICKER not in tickers:
        tickers.append(CALENDAR_TICKER)
    leverage = dict(zip(universe["ticker"], universe["leverage"].astype(float), strict=True))
    prices = update_prices(tickers, store, sources, run_log, now, full=full, leverage=leverage)

    if include_macro:
        proxy = ProxySource(sources[0])
        chains = {s.series: _macro_chain(s, settings, proxy) for s in MACRO_SPECS}
        if not settings.fred_api_key:
            log.info("FRED_API_KEY not set; using public FRED CSV, then yfinance proxies")
        update_macro(MACRO_SPECS, store, chains, run_log, now)
    if include_sentiment:
        update_sentiment(TONE_QUERIES, store, GdeltToneSource(), run_log, now)

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    settings.quality_dir.mkdir(parents=True, exist_ok=True)
    quality_path = settings.quality_dir / f"quality-{stamp}.json"
    quality_path.write_text(
        json.dumps(issues_frame(prices.issues).to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )
    log_path = run_log.write(settings.logs_dir, stamp)
    return IngestSummary(prices, run_log, str(log_path), str(quality_path))

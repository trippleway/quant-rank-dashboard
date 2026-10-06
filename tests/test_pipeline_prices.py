"""Price ingest: caching, incremental updates, fallbacks and degradation (FIXTURE data)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from qrd.ingest.pipeline import OVERLAP_DAYS, adjustment_changed, update_prices
from qrd.ingest.resilience import RunLog, Status
from qrd.storage import ParquetStore
from tests.helpers import FakePriceSource, make_bars, read_required

# 2024-12-31 is a Tuesday; 22:00 UTC = 17:00 New York, after the session is final.
NOW = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)


def _universe_data(*tickers: str, periods: int = 260) -> dict[str, pd.DataFrame]:
    return {
        t: make_bars(t, start="2024-01-02", periods=periods, seed=i) for i, t in enumerate(tickers)
    }


def _store(tmp_path: Path) -> ParquetStore:
    return ParquetStore(tmp_path)


def test_first_run_fetches_and_caches(tmp_path: Path) -> None:
    data = _universe_data("SPY", "AAA")
    src = FakePriceSource("primary", data)
    store, rl = _store(tmp_path), RunLog()

    res = update_prices(["SPY", "AAA"], store, [src], rl, NOW, years=2)

    assert res.statuses == {"SPY": Status.OK, "AAA": Status.OK}
    cached = store.read("prices", "AAA")
    assert cached is not None
    assert len(cached) == len(data["AAA"])
    assert rl.counts("prices")["ok"] == 2


def test_incremental_run_requests_only_recent_window_and_merges(tmp_path: Path) -> None:
    full = _universe_data("SPY", periods=260)["SPY"]
    store, rl = _store(tmp_path), RunLog()
    first = full.iloc[:250]
    update_prices(["SPY"], store, [FakePriceSource("p", {"SPY": first})], rl, NOW, years=2)

    src = FakePriceSource("p", {"SPY": full})
    update_prices(["SPY"], store, [src], rl, NOW, years=2)

    (_, start, _end) = src.calls[0]
    last_cached = first["date"].max().date()
    assert start == last_cached - timedelta(days=OVERLAP_DAYS)
    merged = store.read("prices", "SPY")
    assert merged is not None
    assert len(merged) == len(full)
    assert not merged["date"].duplicated().any()
    pd.testing.assert_series_equal(
        merged["close"].reset_index(drop=True), full["close"].reset_index(drop=True)
    )


def test_full_flag_ignores_cache_window(tmp_path: Path) -> None:
    data = _universe_data("SPY")
    store, rl = _store(tmp_path), RunLog()
    update_prices(["SPY"], store, [FakePriceSource("p", data)], rl, NOW, years=2)
    src = FakePriceSource("p", data)
    update_prices(["SPY"], store, [src], rl, NOW, years=2, full=True)
    assert src.calls[0][1] <= date(2023, 1, 1)


def test_fallback_source_used_for_missing_tickers(tmp_path: Path) -> None:
    data = _universe_data("SPY", "AAA", "BBB")
    primary = FakePriceSource("primary", {"SPY": data["SPY"], "AAA": data["AAA"]})
    backup = FakePriceSource("backup", data)
    store, rl = _store(tmp_path), RunLog()

    res = update_prices(["SPY", "AAA", "BBB"], store, [primary, backup], rl, NOW, years=2)

    assert res.statuses["BBB"] == Status.FALLBACK
    assert backup.calls[0][0] == ("BBB",)  # backup only asked for what was missing
    bbb = store.read("prices", "BBB")
    assert bbb is not None
    assert set(bbb["source"]) == {"backup"}


def test_primary_outage_falls_back_for_everything(tmp_path: Path) -> None:
    data = _universe_data("SPY", "AAA")
    store, rl = _store(tmp_path), RunLog()
    res = update_prices(
        ["SPY", "AAA"],
        store,
        [FakePriceSource("primary", fail=True), FakePriceSource("backup", data)],
        rl,
        NOW,
        years=2,
    )
    assert set(res.statuses.values()) == {Status.FALLBACK}


def test_all_sources_down_keeps_cache_as_degraded(tmp_path: Path) -> None:
    data = _universe_data("SPY", "AAA")
    store, rl = _store(tmp_path), RunLog()
    update_prices(["SPY", "AAA"], store, [FakePriceSource("p", data)], rl, NOW, years=2)
    before = read_required(store, "prices", "AAA")

    rl2 = RunLog()
    res = update_prices(
        ["SPY", "AAA", "NEW"],
        store,
        [FakePriceSource("p", fail=True), FakePriceSource("b", crash=True)],
        rl2,
        NOW,
        years=2,
    )

    assert res.statuses["AAA"] == Status.DEGRADED
    assert res.statuses["NEW"] == Status.FAILED  # no cache, but the run completed
    pd.testing.assert_frame_equal(read_required(store, "prices", "AAA"), before)
    assert rl2.counts("prices") == {"ok": 0, "fallback": 0, "degraded": 2, "failed": 1}
    assert abs(res.coverage() - 2 / 3) < 1e-9


def test_partial_session_bar_is_not_stored(tmp_path: Path) -> None:
    # 2024-12-31 15:00 New York: the 2024-12-31 bar is still forming.
    intraday = datetime(2024, 12, 31, 20, 0, tzinfo=UTC)
    data = _universe_data("SPY", periods=261)  # last bar dated 2024-12-31
    assert data["SPY"]["date"].max() == pd.Timestamp("2024-12-31")
    store = _store(tmp_path)
    update_prices(["SPY"], store, [FakePriceSource("p", data)], RunLog(), intraday, years=2)
    stored = store.read("prices", "SPY")
    assert stored is not None
    assert stored["date"].max() == pd.Timestamp("2024-12-30")


def test_adjustment_change_triggers_full_refetch(tmp_path: Path) -> None:
    full = _universe_data("SPY", periods=260)["SPY"]
    store, rl = _store(tmp_path), RunLog()
    update_prices(
        ["SPY"], store, [FakePriceSource("p", {"SPY": full.iloc[:250]})], rl, NOW, years=2
    )

    # A new dividend rescales the whole adjusted history by 0.99.
    readjusted = full.assign(adj_close=full["adj_close"] * 0.99)
    src = FakePriceSource("p", {"SPY": readjusted})
    res = update_prices(["SPY"], store, [src], rl, NOW, years=2)

    assert res.refetched_full == ["SPY"]
    assert len(src.calls) == 2
    stored = store.read("prices", "SPY")
    assert stored is not None
    # The whole history now uses the new basis — no splice of old and new adj_close.
    pd.testing.assert_series_equal(
        stored["adj_close"].reset_index(drop=True),
        readjusted["adj_close"].reset_index(drop=True),
    )


def test_failed_full_refetch_keeps_cache_rather_than_splicing(tmp_path: Path) -> None:
    full = _universe_data("SPY", periods=260)["SPY"]
    store, rl = _store(tmp_path), RunLog()
    update_prices(
        ["SPY"], store, [FakePriceSource("p", {"SPY": full.iloc[:250]})], rl, NOW, years=2
    )
    before = read_required(store, "prices", "SPY")

    class OnceSource(FakePriceSource):
        def fetch(self, tickers, start, end):  # type: ignore[no-untyped-def]
            if self.calls:
                self.calls.append((tuple(tickers), start, end))
                return {}
            return super().fetch(tickers, start, end)

    readjusted = full.assign(adj_close=full["adj_close"] * 0.99)
    res = update_prices(["SPY"], store, [OnceSource("p", {"SPY": readjusted})], rl, NOW, years=2)

    assert res.statuses["SPY"] == Status.DEGRADED
    pd.testing.assert_frame_equal(read_required(store, "prices", "SPY"), before)


def test_adjustment_changed_detects_close_and_adj_differences() -> None:
    a = make_bars("X", periods=10)
    assert not adjustment_changed(a, a.copy())
    assert adjustment_changed(a, a.assign(adj_close=a["adj_close"] * 1.01))
    assert adjustment_changed(a, a.assign(close=a["close"] / 2))  # split restatement
    assert not adjustment_changed(a.iloc[:5], a.iloc[5:])  # no overlap


def test_quality_issues_are_reported_per_ticker(tmp_path: Path) -> None:
    data = _universe_data("SPY", "BAD")
    bad = data["BAD"].copy()
    bad.loc[100, ["close", "adj_close"]] = bad["close"].iloc[100] * 3  # spike…
    data["BAD"] = bad  # …reverted next day = bad tick
    res = update_prices(
        ["SPY", "BAD"], _store(tmp_path), [FakePriceSource("p", data)], RunLog(), NOW, years=2
    )
    assert res.unusable == {"BAD"}

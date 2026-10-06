"""`qrd daily` orchestration: step order, failure handling, backtest cadence, run log.

Fake steps are used for control flow; the end-to-end test writes SYNTHETIC FIXTURE prices
in place of the network ingest and runs the real features → rank → backtest → publish.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qrd import cli, daily
from qrd.backtest.report import run_stored_backtest
from qrd.backtest.run import BacktestConfig
from qrd.config import Settings
from qrd.daily import StepFn, backtest_due, default_steps, render_markdown, run_daily
from qrd.storage import ParquetStore
from qrd.universe import load_universe
from tests.helpers import make_bars

NOW = datetime(2026, 1, 9, 22, 30, tzinfo=UTC)


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fake_steps(
    calls: list[str], *, asof: str = "2026-01-09", fail: str | None = None
) -> dict[str, StepFn]:
    def make(name: str) -> StepFn:
        def step(settings: Settings) -> dict[str, Any]:
            calls.append(name)
            if name == fail:
                raise RuntimeError(f"{name} broke")
            if name == "rank":
                _write(settings.rankings_dir / "latest.json", {"asof": asof})
                return {"asof": asof, "selected": 50}
            if name == "backtest":
                _write(settings.backtest_dir / "latest.json", {"asof": asof})
            return {}

        return step

    return {name: make(name) for name in daily.STEP_ORDER}


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, fred_api_key=None)


def _statuses(summary: daily.DailySummary) -> dict[str, str]:
    return {s.name: s.status for s in summary.steps}


def test_runs_every_step_in_order_and_writes_log(tmp_path: Path) -> None:
    calls: list[str] = []
    summary = run_daily(_settings(tmp_path), _fake_steps(calls), now=NOW)
    assert calls == ["ingest", "features", "rank", "backtest", "publish"]
    assert summary.ok and summary.asof == "2026-01-09" and not summary.errors
    assert set(_statuses(summary).values()) == {"ok"}
    logged = json.loads(Path(str(summary.log_path)).read_text(encoding="utf-8"))
    assert logged["ok"] is True
    assert [s["name"] for s in logged["steps"]] == list(daily.STEP_ORDER)
    assert Path(str(summary.log_path)).name == "daily-20260109T223000Z.json"


@pytest.mark.parametrize("broken", ["ingest", "features", "rank", "publish"])
def test_failed_step_stops_the_run(tmp_path: Path, broken: str) -> None:
    calls: list[str] = []
    summary = run_daily(_settings(tmp_path), _fake_steps(calls, fail=broken), now=NOW)
    assert not summary.ok
    assert calls[-1] == broken
    statuses = _statuses(summary)
    assert statuses[broken] == "failed"
    after = daily.STEP_ORDER[daily.STEP_ORDER.index(broken) + 1 :]
    assert all(statuses[s] == "skipped" for s in after)
    assert summary.errors == [f"{broken}: RuntimeError: {broken} broke"]
    assert "❌" in render_markdown(summary)


def test_backtest_failure_degrades_to_stored_result(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _write(s.backtest_dir / "latest.json", {"asof": "2025-12-01"})
    calls: list[str] = []
    summary = run_daily(s, _fake_steps(calls, fail="backtest"), now=NOW)
    assert summary.ok
    assert _statuses(summary)["backtest"] == "degraded"
    assert calls[-1] == "publish"
    assert any("2025-12-01" in w for w in summary.warnings)


def test_backtest_failure_without_stored_result_fails(tmp_path: Path) -> None:
    calls: list[str] = []
    summary = run_daily(_settings(tmp_path), _fake_steps(calls, fail="backtest"), now=NOW)
    assert not summary.ok
    assert _statuses(summary)["publish"] == "skipped"


def test_backtest_due_rules(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    assert backtest_due(s, "auto", "2026-01-09")[0]  # nothing stored
    assert not backtest_due(s, "never", "2026-01-09")[0]
    _write(s.backtest_dir / "latest.json", {"asof": "2026-01-05"})
    assert not backtest_due(s, "auto", "2026-01-09", max_age_days=7)[0]
    assert backtest_due(s, "auto", "2026-01-12", max_age_days=7)[0]
    assert backtest_due(s, "always", "2026-01-05")[0]
    assert not backtest_due(s, "auto", None)[0]


def test_recent_backtest_is_skipped_in_auto_mode(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _write(s.backtest_dir / "latest.json", {"asof": "2026-01-08"})
    calls: list[str] = []
    summary = run_daily(s, _fake_steps(calls), now=NOW)
    assert "backtest" not in calls
    assert summary.ok and _statuses(summary)["backtest"] == "skipped"


def test_unchanged_ranking_date_warns(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    _write(s.rankings_dir / "latest.json", {"asof": "2026-01-09"})
    summary = run_daily(s, _fake_steps([]), backtest="never", now=NOW)
    assert summary.ok
    assert any("休市" in w for w in summary.warnings)


def test_stale_ranking_date_fails_after_publishing(tmp_path: Path) -> None:
    calls: list[str] = []
    summary = run_daily(
        _settings(tmp_path), _fake_steps(calls, asof="2026-01-02"), max_stale_days=5, now=NOW
    )
    assert calls[-1] == "publish"
    assert not summary.ok
    assert any("資料過期" in e for e in summary.errors)


def test_cli_daily_exit_code_and_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fail: list[str | None] = [None]
    monkeypatch.setattr(
        daily, "default_steps", lambda out, min_coverage=0.9: _fake_steps([], fail=fail[0])
    )
    md = tmp_path / "summary.md"
    args = ["daily", "--data-dir", str(tmp_path), "--markdown", str(md), "--max-stale-days", "9999"]
    assert cli.main(args) == 0
    assert "✅" in md.read_text(encoding="utf-8")
    fail[0] = "features"
    assert cli.main(args) == 1
    text = md.read_text(encoding="utf-8")
    assert "features: RuntimeError: features broke" in text  # appended, not overwritten
    assert "qrd daily — ✅" in text
    assert "Not investment advice" in capsys.readouterr().out


# --- end to end (SYNTHETIC FIXTURE prices instead of the network ingest) ------------------

START = "2022-01-03"
PERIODS = 600
ETFS = ["SPY", "AGG", "QQQ", "TLT", "IEF", "SHY", "GLD", "HYG", "UUP"]
STOCKS = load_universe().query("asset_class == 'equity'")["ticker"].head(45).tolist()


def _fixture_ingest(settings: Settings) -> dict[str, Any]:
    store = ParquetStore(settings.data_dir)
    for i, t in enumerate(ETFS + STOCKS):
        store.write("prices", t, make_bars(t, start=START, periods=PERIODS, seed=i, price=50))
    dates = pd.bdate_range(START, periods=PERIODS)
    rng = np.random.default_rng(0)
    for series, level in (("vix", 18), ("ust_10y", 4), ("ust_2y", 3.5), ("ust_3m", 4)):
        store.write(
            "macro",
            series,
            pd.DataFrame(
                {
                    "obs_date": dates,
                    "available_date": dates + pd.offsets.BDay(1),
                    "series": series,
                    "value": level + np.cumsum(rng.normal(0, 0.05, len(dates))),
                    "source": "FIXTURE",
                    "is_proxy": False,
                }
            ),
        )
    return {"price_coverage": 1.0, "tickers": len(ETFS) + len(STOCKS)}


def test_daily_end_to_end_publishes_site(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    out = tmp_path / "site"
    steps = default_steps(out)
    steps["ingest"] = _fixture_ingest
    steps["backtest"] = lambda st: run_stored_backtest(
        st, BacktestConfig(n_random=10, robustness=False)
    )
    last = pd.bdate_range(START, periods=PERIODS)[-1]
    summary = run_daily(s, steps, now=datetime.combine(last, datetime.min.time(), UTC))
    assert summary.ok, summary.errors
    assert set(_statuses(summary).values()) == {"ok"}
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asof"] == summary.asof == str(last.date())
    assert manifest["backtest_asof"] is not None
    assert manifest["demo"] is False
    assert "backtest.json" in manifest["files"]

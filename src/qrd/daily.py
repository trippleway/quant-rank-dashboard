"""`qrd daily`: ingest → features → rank → (backtest when due) → publish, with a run log.

Each step runs in order and is timed. A failed step stops the run (later steps are
``skipped``) except the backtest, which degrades to the previous stored result when one
exists. The summary is written to ``data/logs/daily-<stamp>.json`` and can be rendered as
Markdown for the GitHub Actions job summary.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from qrd import DISCLAIMER
from qrd.config import Settings

log = logging.getLogger(__name__)

STEP_ORDER = ("ingest", "features", "rank", "backtest", "publish")
BacktestMode = Literal["auto", "always", "never"]
BACKTEST_MODES: tuple[BacktestMode, ...] = ("auto", "always", "never")
# Re-run the (slow, ~3.5 min) backtest when the stored one is at least this old.
DEFAULT_BACKTEST_MAX_AGE_DAYS = 7
# Longest calendar gap between run date and ranking date that holidays + weekends explain.
DEFAULT_MAX_STALE_DAYS = 5

StepFn = Callable[[Settings], dict[str, Any]]


@dataclass
class StepResult:
    name: str
    status: Literal["ok", "failed", "skipped", "degraded"]
    seconds: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class DailySummary:
    started_at: str
    finished_at: str
    ok: bool
    asof: str | None
    steps: list[StepResult]
    warnings: list[str]
    errors: list[str]
    log_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "ok": self.ok,
            "asof": self.asof,
            "steps": [s.__dict__ for s in self.steps],
            "warnings": self.warnings,
            "errors": self.errors,
            "log": self.log_path,
        }


def _read_asof(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("asof")
    except (OSError, ValueError, AttributeError):
        return None
    return str(value) if value else None


def backtest_due(
    settings: Settings,
    mode: BacktestMode,
    rank_asof: str | None,
    max_age_days: int = DEFAULT_BACKTEST_MAX_AGE_DAYS,
) -> tuple[bool, str]:
    """Whether to re-run the backtest, and why (``auto``: missing or ≥ max_age_days old)."""
    if mode == "always":
        return True, "requested (--backtest always)"
    if mode == "never":
        return False, "disabled (--backtest never)"
    stored = _read_asof(settings.backtest_dir / "latest.json")
    if stored is None:
        return True, "no stored backtest"
    if rank_asof is None:
        return False, f"stored backtest {stored} kept (ranking date unknown)"
    age = (date.fromisoformat(rank_asof) - date.fromisoformat(stored)).days
    if age >= max_age_days:
        return True, f"stored backtest {stored} is {age} days older than ranking"
    return False, f"stored backtest {stored} is {age} days old (< {max_age_days})"


def default_steps(out_dir: Path, min_coverage: float = 0.9) -> dict[str, StepFn]:
    """The real pipeline stages, each returning a JSON-able summary or raising."""
    # Imports stay local so `qrd version` and tests that inject steps stay light.

    def ingest(settings: Settings) -> dict[str, Any]:
        from qrd.ingest.pipeline import run_ingest  # noqa: PLC0415
        from qrd.universe import load_universe  # noqa: PLC0415

        summary = run_ingest(settings, load_universe())
        report = summary.to_dict()
        coverage = summary.prices.coverage()
        if coverage < min_coverage:
            raise RuntimeError(f"price coverage {coverage:.1%} below {min_coverage:.0%}")
        return report

    def features(settings: Settings) -> dict[str, Any]:
        from qrd.features.build import run_features  # noqa: PLC0415
        from qrd.universe import load_universe  # noqa: PLC0415

        return run_features(settings, load_universe()).to_dict()

    def rank(settings: Settings) -> dict[str, Any]:
        from qrd.scoring.rank import run_rank  # noqa: PLC0415

        return run_rank(settings)

    def backtest(settings: Settings) -> dict[str, Any]:
        from qrd.backtest.report import run_stored_backtest  # noqa: PLC0415

        return run_stored_backtest(settings)

    def publish(settings: Settings) -> dict[str, Any]:
        from qrd.publish import run_publish  # noqa: PLC0415

        return run_publish(settings, out_dir)

    return {
        "ingest": ingest,
        "features": features,
        "rank": rank,
        "backtest": backtest,
        "publish": publish,
    }


def _run_step(name: str, fn: StepFn, settings: Settings) -> StepResult:
    log.info("=== %s: start ===", name)
    t0 = time.monotonic()
    try:
        detail = fn(settings)
    except Exception as exc:  # the orchestrator records every failure
        log.exception("=== %s: FAILED ===", name)
        return StepResult(
            name, "failed", round(time.monotonic() - t0, 1), error=f"{type(exc).__name__}: {exc}"
        )
    seconds = round(time.monotonic() - t0, 1)
    log.info("=== %s: ok (%.1fs) ===", name, seconds)
    return StepResult(name, "ok", seconds, detail=detail)


def run_daily(
    settings: Settings,
    steps: Mapping[str, StepFn],
    *,
    backtest: BacktestMode = "auto",
    backtest_max_age_days: int = DEFAULT_BACKTEST_MAX_AGE_DAYS,
    max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
    now: datetime | None = None,
) -> DailySummary:
    now = now or datetime.now(UTC)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    previous_asof = _read_asof(settings.rankings_dir / "latest.json")
    results: list[StepResult] = []
    warnings: list[str] = []
    errors: list[str] = []
    asof: str | None = None
    stopped = False

    for name in STEP_ORDER:
        if stopped:
            results.append(StepResult(name, "skipped", detail={"reason": "earlier step failed"}))
            continue
        if name == "backtest":
            due, why = backtest_due(settings, backtest, asof, backtest_max_age_days)
            if not due:
                log.info("=== backtest: skipped (%s) ===", why)
                results.append(StepResult(name, "skipped", detail={"reason": why}))
                continue
            log.info("backtest due: %s", why)
        res = _run_step(name, steps[name], settings)
        results.append(res)
        if res.status == "failed":
            fallback = _read_asof(settings.backtest_dir / "latest.json")
            if name == "backtest" and fallback is not None:
                res.status = "degraded"
                warnings.append(f"回測失敗，沿用 {fallback} 的回測結果：{res.error}")
                continue
            errors.append(f"{name}: {res.error}")
            stopped = True
            continue
        if name == "rank":
            asof = str(res.detail.get("asof")) if res.detail.get("asof") else None
            if asof is not None and asof == previous_asof:
                warnings.append(f"排名日期與上次相同（{asof}）：可能是休市日或資料源尚未更新")

    if asof is not None:
        lag = (now.date() - date.fromisoformat(asof)).days
        if lag > max_stale_days:
            errors.append(
                f"資料過期：排名日期 {asof} 距執行日 {now.date()} 已 {lag} 天"
                f"（上限 {max_stale_days}）"
            )

    finished = datetime.now(UTC).isoformat(timespec="seconds")
    summary = DailySummary(started, finished, not errors, asof, results, warnings, errors)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    path = settings.logs_dir / f"daily-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    summary.log_path = str(path)
    path.write_text(
        json.dumps(summary.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return summary


_ICON = {"ok": "✅ ok", "failed": "❌ failed", "skipped": "⏭ skipped", "degraded": "⚠️ degraded"}


def _step_note(step: StepResult) -> str:
    if step.error:
        return step.error
    d = step.detail
    notes = {
        "ingest": lambda: f"coverage {d.get('price_coverage')}, {d.get('tickers')} tickers",
        "features": lambda: f"asof {d.get('asof')}, regime {d.get('regime')}",
        "rank": lambda: f"asof {d.get('asof')}, {d.get('selected')} selected",
        "backtest": lambda: f"period {d.get('period')}",
        "publish": lambda: f"health {d.get('health')}, {d.get('assets')} asset files",
    }
    if "reason" in d:
        return str(d["reason"])
    return notes[step.name]() if step.name in notes and d else ""


def render_markdown(summary: DailySummary) -> str:
    """Short Markdown report for ``$GITHUB_STEP_SUMMARY``."""
    head = "✅ 成功" if summary.ok else "❌ 失敗"
    lines = [
        f"## qrd daily — {head}",
        "",
        f"- 排名日期：{summary.asof or '—'}",
        f"- 開始／結束（UTC）：{summary.started_at} → {summary.finished_at}",
        "",
        "| 步驟 | 狀態 | 秒 | 說明 |",
        "|---|---|---:|---|",
    ]
    for s in summary.steps:
        note = _step_note(s).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {s.name} | {_ICON[s.status]} | {s.seconds:.1f} | {note} |")
    for title, items in (("錯誤", summary.errors), ("警告", summary.warnings)):
        if items:
            lines += ["", f"### {title}", *[f"- {x}" for x in items]]
    lines += ["", f"僅供研究與學習，不構成投資建議。{DISCLAIMER}", ""]
    return "\n".join(lines)

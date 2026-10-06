"""`.github/scripts/daily-issue.sh` against a stub `gh` that records its calls."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "daily-issue.sh"
STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
if [[ "$1 $2" == "issue list" ]]; then echo -n "$GH_EXISTING"; fi
if [[ "$*" == *--body-file* ]]; then
  for ((i = 1; i <= $#; i++)); do
    if [[ "${!i}" == "--body-file" ]]; then j=$((i + 1)); cat "${!j}" >> "$GH_BODY"; fi
  done
fi
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(
    tmp_path: Path, pipeline: str, deploy: str, existing: str = "", summary: str | None = None
) -> tuple[list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB, encoding="utf-8")
    gh.chmod(0o755)
    calls, body = tmp_path / "calls.txt", tmp_path / "body.txt"
    calls.write_text("", encoding="utf-8")
    body.write_text("", encoding="utf-8")
    summary_file = tmp_path / "summary.md"
    if summary is not None:
        summary_file.write_text(summary, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALLS": str(calls),
        "GH_BODY": str(body),
        "GH_EXISTING": existing,
        "GITHUB_REPOSITORY": "owner/repo",
        "RUN_URL": "https://example.invalid/run/1",
        "PIPELINE_RESULT": pipeline,
        "DEPLOY_RESULT": deploy,
        "SUMMARY_FILE": str(summary_file),
    }
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
    return calls.read_text(encoding="utf-8").splitlines(), body.read_text(encoding="utf-8")


def test_failure_opens_issue_with_summary(tmp_path: Path) -> None:
    calls, body = _run(tmp_path, "failure", "skipped", summary="| ingest | ❌ failed |")
    assert calls[0].startswith("issue list")
    assert calls[1].startswith("issue create") and "daily pipeline failing" in calls[1]
    assert "https://example.invalid/run/1" in body
    assert "| ingest | ❌ failed |" in body
    assert "GitHub Pages" not in body  # deploy hint only when the pipeline itself passed


def test_failure_with_open_issue_comments_instead(tmp_path: Path) -> None:
    calls, body = _run(tmp_path, "success", "failure", existing="7")
    assert calls[1].startswith("issue comment 7")
    assert not any(c.startswith("issue create") for c in calls)
    assert "Source 選「GitHub Actions」" in body
    assert "沒有 qrd daily 摘要" in body


def test_cancelled_run_counts_as_failure(tmp_path: Path) -> None:
    calls, _ = _run(tmp_path, "cancelled", "skipped")
    assert any(c.startswith("issue create") for c in calls)


def test_success_closes_open_issue(tmp_path: Path) -> None:
    calls, _ = _run(tmp_path, "success", "success", existing="7")
    assert calls[1].startswith("issue comment 7") and "已恢復" in calls[1]
    assert calls[2].startswith("issue close 7")


def test_success_without_issue_does_nothing(tmp_path: Path) -> None:
    calls, _ = _run(tmp_path, "success", "success")
    assert calls == [calls[0]] and calls[0].startswith("issue list")

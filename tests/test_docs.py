"""M7 documentation checks: links resolve, screenshots exist, every doc carries the disclaimer."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted([ROOT / "README.md", ROOT / "web" / "README.md", *(ROOT / "docs").rglob("*.md")])
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
DISCLAIMER = re.compile(r"僅供研究與學習.{0,10}不構成.{0,4}投資建議")
SCREENSHOT_PAGES = [
    "overview",
    "rankings",
    "asset",
    "macro",
    "backtest",
    "changes",
    "methodology",
]


def _relative_links(path: Path) -> list[str]:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    targets = (m.group(1) for m in LINK.finditer(text))
    return [t for t in targets if not re.match(r"[a-z]+:|#", t)]


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path: Path) -> None:
    missing = [t for t in _relative_links(path) if not (path.parent / t.split("#")[0]).exists()]
    assert not missing, f"{path.relative_to(ROOT)} has broken links: {missing}"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_doc_has_disclaimer(path: Path) -> None:
    assert DISCLAIMER.search(path.read_text(encoding="utf-8"))


def test_readme_shows_every_page_screenshot() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    images = {t for t in _relative_links(ROOT / "README.md") if t.startswith("docs/screenshots/")}
    for page in SCREENSHOT_PAGES:
        assert f"docs/screenshots/light-{page}.webp" in images, page
    assert "docs/screenshots/dark-overview.webp" in images
    section = readme.split("## 截圖", 1)[1].split("\n## ", 1)[0]
    # Screenshots must say where the numbers came from and when (no unlabeled sample data).
    assert "真實 pipeline 輸出" in section
    assert re.search(r"資料日期 \d{4}-\d{2}-\d{2}", section)


def test_readme_status_is_not_stale() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "開發中" not in readme

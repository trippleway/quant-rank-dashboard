"""M0 smoke tests: package layout and CLI wiring."""

from __future__ import annotations

import importlib

import pytest

import qrd
from qrd.cli import main

SUBPACKAGES = ["ingest", "universe", "features", "scoring", "backtest", "publish"]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_importable(name: str) -> None:
    module = importlib.import_module(f"qrd.{name}")
    assert module.__doc__


def test_version_command_prints_disclaimer(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert qrd.__version__ in out
    assert "Not investment advice" in out


def test_daily_fails_loudly_until_implemented(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["daily"]) == 1
    assert "not implemented" in capsys.readouterr().err


def test_unknown_command_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["nope"])
    assert exc.value.code != 0

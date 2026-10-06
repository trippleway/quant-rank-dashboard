"""End-to-end `qrd features` on a temporary store (SYNTHETIC FIXTURE data only)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qrd import DISCLAIMER
from qrd.cli import main
from qrd.storage import ParquetStore
from qrd.universe import load_universe
from tests.helpers import make_bars, read_required

TICKERS = ["SPY", "HYG", "IEF", "TLT", "AAPL"]


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    s = ParquetStore(tmp_path)
    for i, t in enumerate(TICKERS):
        s.write("prices", t, make_bars(t, start="2023-01-02", periods=400, seed=i))
    dates = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(0)
    for series in ("vix", "ust_10y"):
        s.write(
            "macro",
            series,
            pd.DataFrame(
                {
                    "obs_date": dates,
                    "available_date": dates + pd.offsets.BDay(1),
                    "series": series,
                    "value": 15 + np.cumsum(rng.normal(0, 0.1, len(dates))),
                    "source": "FIXTURE",
                    "is_proxy": False,
                }
            ),
        )
    quality = tmp_path / "quality"
    quality.mkdir()
    bad = [{"ticker": "AAPL", "check": "x", "severity": "error", "detail": "", "date": None}]
    (quality / "quality-20200101T000000Z.json").write_text(json.dumps(bad), encoding="utf-8")
    return s


def test_features_command_writes_outputs(
    store: ParquetStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["features", "--data-dir", str(store.root)]) == 0
    out = capsys.readouterr().out
    assert DISCLAIMER in out
    summary = json.loads(out[: out.rindex("}") + 1])
    assert summary["excluded"] == ["AAPL"]
    assert summary["asof"] == str(pd.bdate_range("2023-01-02", periods=400)[-1].date())
    factors = read_required(store, "features", "factors")
    assert set(factors["ticker"]) == {"SPY", "HYG", "IEF", "TLT"}  # unusable AAPL dropped
    assert set(factors["asset_class"]) <= set(load_universe()["asset_class"])
    regime = read_required(store, "features", "regime")
    assert {"date", "regime", "stress_score"} <= set(regime.columns)
    panel = read_required(store, "features", "macro_panel")
    assert {"vix", "hy_oas", "gdelt_tone_economy"} <= set(panel.columns)  # stable schema


def test_features_asof_truncates(store: ParquetStore, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["features", "--data-dir", str(store.root), "--asof", "2023-12-29"]) == 0
    factors = read_required(store, "features", "factors")
    assert factors["date"].max() == pd.Timestamp("2023-12-29")


def test_features_without_data_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["features", "--data-dir", str(tmp_path)]) == 1
    assert "qrd ingest" in capsys.readouterr().err

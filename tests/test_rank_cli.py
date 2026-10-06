"""End-to-end `qrd features` → `qrd rank` on a temporary store (SYNTHETIC FIXTURE data)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qrd import DISCLAIMER
from qrd.cli import main
from qrd.storage import ParquetStore
from tests.helpers import make_bars

TICKERS = ["SPY", "VOO", "QQQ", "TQQQ", "SQQQ", "HYG", "IEF", "TLT", "SHY", "GLD", "UUP"]
TICKERS += ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "UNH", "KO", "NEE", "CAT", "AMZN"]


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    s = ParquetStore(tmp_path)
    for i, t in enumerate(TICKERS):
        s.write("prices", t, make_bars(t, start="2023-01-02", periods=420, seed=i, price=50))
    dates = pd.bdate_range("2023-01-02", periods=420)
    rng = np.random.default_rng(0)
    for series in ("vix", "ust_10y", "curve_10y2y"):
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
    return s


def _summary(out: str) -> dict[str, object]:
    start = out.rindex("\n{", 0, out.rindex("}")) + 1 if "\n{" in out else 0
    parsed: dict[str, object] = json.loads(out[start : out.rindex("}") + 1])
    return parsed


def test_rank_writes_top50_json_with_breakdown(
    store: ParquetStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["features", "--data-dir", str(store.root)]) == 0
    capsys.readouterr()
    assert main(["rank", "--data-dir", str(store.root)]) == 0
    out = capsys.readouterr().out
    assert DISCLAIMER in out
    summary = _summary(out)
    last = str(pd.bdate_range("2023-01-02", periods=420)[-1].date())
    assert summary["asof"] == last
    payload = json.loads((store.root / "rankings" / "latest.json").read_text(encoding="utf-8"))
    dated = store.root / "rankings" / f"top50-{last}.json"
    assert json.loads(dated.read_text(encoding="utf-8")) == payload
    assert payload["schema_version"] == "1.0"
    assert payload["disclaimer"] == DISCLAIMER
    top = payload["top"]
    assert 0 < len(top) <= 50
    assert [e["rank"] for e in top] == list(range(1, len(top) + 1))
    tickers = [e["ticker"] for e in top]
    assert len(set(tickers)) == len(tickers)
    for e in top:
        contrib = sum(f["contribution"] for f in e["factors"])
        assert contrib == pytest.approx(e["composite"], abs=1e-3)
        assert e["score"] == pytest.approx(
            e["composite"] - e["risk_penalty"] - e["concentration_penalty"], abs=1e-3
        )
        assert 1 <= len(e["risks"]) <= 3
        assert len(e["reasons"]) <= 3
        assert set(e["groups"]) == {"momentum", "low_risk", "liquidity", "yield", "duration"}
    lev = {e["ticker"]: e for e in top if e["leverage"] != 1}
    for e in lev.values():
        assert e["risks"][0]["code"] == "leveraged_inverse"
        assert e["risk_penalty"] > 0
    scores = pd.read_parquet(store.root / "rankings" / f"scores-{last}.parquet")
    assert set(tickers) <= set(scores["ticker"])


def test_rank_asof_does_not_touch_latest(
    store: ParquetStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["features", "--data-dir", str(store.root)]) == 0
    assert main(["rank", "--data-dir", str(store.root), "--asof", "2024-05-01"]) == 0
    capsys.readouterr()
    assert (store.root / "rankings" / "top50-2024-05-01.json").is_file()
    assert not (store.root / "rankings" / "latest.json").exists()


def test_rank_without_features_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["rank", "--data-dir", str(tmp_path)]) == 1
    assert "qrd features" in capsys.readouterr().err


def test_rank_asof_beyond_features_fails(
    store: ParquetStore, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["features", "--data-dir", str(store.root), "--asof", "2024-01-31"]) == 0
    capsys.readouterr()
    assert main(["rank", "--data-dir", str(store.root), "--asof", "2024-03-01"]) == 1
    assert "re-run `qrd features`" in capsys.readouterr().err

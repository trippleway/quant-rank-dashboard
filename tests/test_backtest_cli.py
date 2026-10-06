"""End-to-end `qrd features` → `qrd backtest` on a temporary store (SYNTHETIC FIXTURE data)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qrd import DISCLAIMER
from qrd.cli import main
from qrd.storage import ParquetStore
from qrd.universe import load_universe
from tests.helpers import make_bars

START = "2022-01-03"
PERIODS = 600
ETFS = ["SPY", "AGG", "QQQ", "TQQQ", "SQQQ", "HYG", "IEF", "TLT", "SHY", "GLD", "UUP", "VIXY"]
UNI = load_universe()
STOCKS = UNI.loc[UNI["asset_class"] == "equity", "ticker"].head(45).tolist()
assert set(ETFS) <= set(UNI["ticker"])


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> ParquetStore:
    s = ParquetStore(tmp_path_factory.mktemp("bt"))
    for i, t in enumerate(ETFS + STOCKS):
        s.write("prices", t, make_bars(t, start=START, periods=PERIODS, seed=i, price=50))
    dates = pd.bdate_range(START, periods=PERIODS)
    rng = np.random.default_rng(0)
    for series, level in (("vix", 18), ("ust_10y", 4), ("curve_10y2y", 0.5), ("ust_3m", 4)):
        s.write(
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
    return s


@pytest.fixture(scope="module")
def payload(store: ParquetStore) -> dict[str, Any]:
    assert main(["features", "--data-dir", str(store.root)]) == 0
    report = store.root / "copy" / "backtest-report.md"
    code = main(
        ["backtest", "--data-dir", str(store.root), "--sims", "40", "--report", str(report)]
    )
    assert code == 0
    data: dict[str, Any] = json.loads(
        (store.root / "backtest" / "latest.json").read_text(encoding="utf-8")
    )
    return data


def test_backtest_payload_covers_plan_section_5(payload: dict[str, Any]) -> None:
    p = payload
    assert p["schema_version"] == "1.0" and p["kind"] == "backtest"
    assert p["disclaimer"] == DISCLAIMER
    period = p["period"]
    assert isinstance(period, dict)
    assert period["shortened"] is True  # 5 years requested, ~1.4 usable
    assert 1.0 <= period["years"] < 2.0
    assert len(p["biases"]) >= 8
    assert any("存活者偏誤" in b for b in p["biases"])
    assert any("期間縮短" in b for b in p["biases"])
    assumptions = p["assumptions"]
    assert isinstance(assumptions, dict)
    assert assumptions["parameters_fitted"] is False
    assert assumptions["risk_free"] == "ust_3m"
    freqs = p["frequencies"]
    assert isinstance(freqs, dict) and set(freqs) == {"weekly", "monthly"}
    for blk in freqs.values():
        m = blk["metrics"]
        assert {"strategy", "spy", "sixty_forty", "equal_weight", "random_median"} <= set(m)
        for key in ("cagr", "ann_vol", "sharpe", "sortino", "max_drawdown", "calmar"):
            assert m["strategy"][key] is not None
        assert m["strategy"]["turnover_annual"] > 0
        assert 0 <= m["strategy"]["win_rate_periods"] <= 1
        assert blk["random"]["n"] == 40
        assert 0 <= blk["random"]["strategy_percentile"]["sharpe"] <= 1
        assert blk["ic"]["periods"] >= 3
        assert set(blk["ic"]["deciles"]["ann_return"]) == {str(i) for i in range(1, 11)}
        assert set(blk["split"]) == {"in_sample", "out_of_sample"}
        assert blk["regimes"]
        series = blk["series"]
        n = len(series["dates"])
        assert n > 200
        for key in ("strategy", "spy", "sixty_forty", "equal_weight", "random_p50"):
            assert len(series["equity"][key]) == n
        assert len(series["drawdown"]["strategy"]) == n
        assert len(series["rolling_sharpe"]["strategy"]) == n
        assert blk["monthly_returns"]["strategy"]
        assert blk["capacity"]["median_aum_usd"] > 0
    rob = p["robustness"]
    assert isinstance(rob, dict)
    kinds = {v["kind"] for v in rob["variants"]}
    assert kinds == {"base", "sensitivity", "ablation"}
    names = {v["name"] for v in rob["variants"]}
    assert {"no_regime", "no_momentum", "cost_x2", "top_n_30"} <= names
    ds = rob["deflated_sharpe"]
    assert ds["n_trials"] == len(rob["variants"])
    assert 0 <= ds["deflated_sharpe"] <= ds["psr_vs_zero"] <= 1


def test_backtest_writes_report_and_tables(store: ParquetStore, payload: dict[str, Any]) -> None:
    out = store.root / "backtest"
    day = payload["asof"]
    assert json.loads((out / f"backtest-{day}.json").read_text(encoding="utf-8")) == payload
    md = (out / f"report-{day}.md").read_text(encoding="utf-8")
    assert md == (store.root / "copy" / "backtest-report.md").read_text(encoding="utf-8")
    for heading in ("## 假設", "每週再平衡", "每月再平衡", "## 穩健性", "## 偏誤與限制"):
        assert heading in md
    assert "不構成投資建議" in md and "Deflated Sharpe" in md
    holdings = pd.read_parquet(out / "holdings-monthly.parquet")
    assert (holdings.groupby("signal_date")["weight"].sum().round(9) == 1).all()
    assert (holdings["trade_date"] > holdings["signal_date"]).all()
    daily = pd.read_parquet(out / "daily-weekly.parquet")
    assert {"date", "strategy", "spy"} <= set(daily.columns)


def test_backtest_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backtest", "--data-dir", str(tmp_path)]) == 1
    assert "qrd features" in capsys.readouterr().err


def test_backtest_too_short_window_fails(
    store: ParquetStore, payload: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    end = str(pd.bdate_range(START, periods=PERIODS)[300].date())
    assert main(["backtest", "--data-dir", str(store.root), "--end", end, "--sims", "0"]) == 1
    assert "shorter than" in capsys.readouterr().err

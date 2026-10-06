"""`qrd publish`: frontend JSON from pipeline outputs (SYNTHETIC FIXTURE data only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from qrd import DISCLAIMER
from qrd.backtest.metrics import perf_metrics
from qrd.cli import main
from qrd.publish.build import (
    MIN_BACKTEST_SESSIONS,
    SCHEMA_VERSION,
    buy_and_hold,
    compute_changes,
    regime_segments,
)
from qrd.storage import ParquetStore
from qrd.universe import load_universe
from tests.helpers import make_bars

# --- compute_changes (hand-built payloads) -----------------------------------------------


def _entry(t: str, rank: int) -> dict[str, Any]:
    return {
        "ticker": t,
        "rank": rank,
        "asset_class": "equity",
        "reasons": [{"label": "12-1 月動能"}],
    }


def _scored(scores: dict[str, float], mom: dict[str, float]) -> pd.DataFrame:
    tickers = sorted(scores)
    return pd.DataFrame(
        {
            "ticker": tickers,
            "score": [scores[t] for t in tickers],
            "contrib_mom_12_1": [mom.get(t, 0.0) for t in tickers],
            "contrib_vol_63": [0.0 for _ in tickers],
        }
    )


def _payload(asof: str, order: list[str], regime: str = "neutral", **extra: Any) -> dict[str, Any]:
    return {
        "asof": asof,
        "regime": {"label": regime, "weights_regime": regime},
        "constraints": {"top_n": 3},
        "top": [_entry(t, i + 1) for i, t in enumerate(order)],
        "skipped": extra.get("skipped", []),
        "ineligible": extra.get("ineligible", []),
    }


def test_changes_entries_exits_and_movers_with_reasons() -> None:
    prev = _payload("2026-01-02", ["A", "B", "C", "D", "E", "F", "G"])
    cur = _payload(
        "2026-01-05",
        ["G", "A", "B", "C", "D", "H", "I"],
        skipped=[{"ticker": "E", "score": 0.5, "reason": "category cap x (8)"}],
        ineligible=[{"ticker": "F", "reason": "no bar on asof (stale data)"}],
    )
    prev_s = _scored(
        {t: 1.0 - i / 10 for i, t in enumerate("ABCDEFGHI")}, {"G": 0.1, "H": 0.2, "I": 0.0}
    )
    cur_s = _scored(
        {"G": 2.0, "A": 1.0, "B": 0.9, "C": 0.8, "D": 0.7, "E": 0.6, "H": 0.5, "I": 0.4},
        {"G": 0.6, "H": 0.5, "I": 0.0},
    )
    ch = compute_changes(cur, prev, cur_s, prev_s, threshold=5)
    assert [e["ticker"] for e in ch["entered"]] == ["H", "I"]
    assert [e["ticker"] for e in ch["exited"]] == ["E", "F"]
    exits = {e["ticker"]: e["reasons"] for e in ch["exited"]}
    assert exits["E"][0] == "受約束排除：category cap x (8)"
    assert exits["F"][0] == "今日不合格：no bar on asof (stale data)"
    assert any("動能貢獻 +0.30" in r for r in ch["entered"][0]["reasons"])
    # G moved 7 → 1 (+6); A..D moved down by 1 (below threshold)
    assert [(m["ticker"], m["change"]) for m in ch["movers"]] == [("G", 6)]
    assert ch["movers"][0]["reasons"] == ["動能貢獻 +0.50"]
    assert ch["unchanged"] == 0
    assert ch["regime_changed"] is False


def test_changes_score_position_and_regime_note() -> None:
    prev = _payload("2026-01-02", ["A", "B"], regime="neutral")
    cur = _payload("2026-01-05", ["A", "C"], regime="risk_off")
    prev_s = _scored({"A": 1.0, "B": 0.9, "C": 0.1}, {})
    cur_s = _scored({"A": 1.0, "C": 0.9, "X": 0.85, "B": 0.5}, {})
    ch = compute_changes(cur, prev, cur_s, prev_s)
    assert ch["regime_changed"] is True
    (exit_b,) = ch["exited"]
    assert exit_b["reasons"][0] == "分數排序第 4，未進前 3"
    assert any("neutral 轉為 risk_off" in r for r in exit_b["reasons"])
    (enter_c,) = ch["entered"]
    assert enter_c["score_prev"] == 0.1 and enter_c["score"] == 0.9
    assert ch["unchanged"] == 1


def test_changes_entry_without_previous_score_is_explained() -> None:
    prev = _payload("2026-01-02", ["A"])
    cur = _payload("2026-01-05", ["N"])
    ch = compute_changes(cur, prev, _scored({"N": 1.0, "A": 0.2}, {}), _scored({"A": 1.0}, {}))
    assert ch["entered"][0]["score_prev"] is None
    assert "前一交易日不在合格名單（流動性／資料）" in ch["entered"][0]["reasons"]


# --- single-asset buy and hold ----------------------------------------------------------


def _close(n: int, seed: int = 0, start: str = "2020-01-01") -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)


def test_buy_and_hold_ignores_prices_after_asof() -> None:
    close = _close(900)
    asof = close.index[700]
    full = buy_and_hold(close, None, None, asof)
    tampered = close.copy()
    tampered[tampered.index > asof] *= 5.0  # future prices must not matter
    cut = buy_and_hold(close[close.index <= asof], None, None, asof)
    assert full == cut == buy_and_hold(tampered, None, None, asof)
    assert full["end"] == str(asof.date())
    expected = perf_metrics(close[close.index <= asof].pct_change().iloc[1:])
    assert full["metrics"]["cagr"] == pytest.approx(expected["cagr"], abs=1e-6)


def test_buy_and_hold_requires_twelve_months() -> None:
    close = _close(MIN_BACKTEST_SESSIONS)  # one return short
    res = buy_and_hold(close, None, None, close.index[-1])
    assert res["available"] is False and "不足" in res["reason"]
    longer = _close(MIN_BACKTEST_SESSIONS + 1)
    assert buy_and_hold(longer, None, None, longer.index[-1])["available"] is True
    assert buy_and_hold(longer, None, None, longer.index[-1])["shortened"] is True


def test_regime_segments_are_contiguous_runs() -> None:
    reg = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=5),
            "regime": ["neutral", "neutral", "risk_off", "risk_off", "neutral"],
        }
    )
    segs = regime_segments(reg)
    assert [(s["regime"], s["days"]) for s in segs] == [
        ("neutral", 2),
        ("risk_off", 2),
        ("neutral", 1),
    ]
    assert segs[1]["start"] == "2026-01-05" and segs[1]["end"] == "2026-01-06"


# --- end to end -------------------------------------------------------------------------

START = "2022-01-03"
PERIODS = 600
ETFS = ["SPY", "AGG", "QQQ", "TLT", "IEF", "SHY", "GLD", "HYG", "UUP"]
UNI = load_universe()
STOCKS = UNI.loc[UNI["asset_class"] == "equity", "ticker"].head(45).tolist()


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> tuple[ParquetStore, Path]:
    s = ParquetStore(tmp_path_factory.mktemp("pub"))
    for i, t in enumerate(ETFS + STOCKS):
        s.write("prices", t, make_bars(t, start=START, periods=PERIODS, seed=i, price=50))
    dates = pd.bdate_range(START, periods=PERIODS)
    rng = np.random.default_rng(0)
    for series, level in (("vix", 18), ("ust_10y", 4), ("ust_2y", 3.5), ("ust_3m", 4)):
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
    root = str(s.root)
    assert main(["features", "--data-dir", root]) == 0
    assert main(["rank", "--data-dir", root]) == 0
    bt = ["backtest", "--data-dir", root, "--sims", "10", "--no-robustness"]
    assert main(bt) == 0
    out = s.root / "site"
    assert main(["publish", "--data-dir", root, "--out", str(out)]) == 0
    return s, out


def _read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_publish_writes_versioned_files(site: tuple[ParquetStore, Path]) -> None:
    _, out = site
    manifest = _read(out / "manifest.json")
    assert manifest["demo"] is False
    assert set(manifest["files"]) == {
        "manifest.json",
        "rankings.json",
        "changes.json",
        "macro.json",
        "backtest.json",
    }
    for name in manifest["files"]:
        p = _read(out / name)
        assert p["schema_version"] in (SCHEMA_VERSION, "1.0")
        assert p["disclaimer"] == DISCLAIMER
        assert p["asof"] == manifest["asof"]
    assert manifest["health"]["prices"]["tickers"] == len(ETFS + STOCKS)
    assert manifest["health"]["status"] in ("ok", "degraded")


def test_publish_rankings_and_assets_cover_top(site: tuple[ParquetStore, Path]) -> None:
    store, out = site
    stored = _read(store.root / "rankings" / "latest.json")
    pub = _read(out / "rankings.json")
    assert [e["ticker"] for e in pub["top"]] == [e["ticker"] for e in stored["top"]]
    assert all(len(e["sparkline"]) == 63 for e in pub["top"])
    files = {a["ticker"]: a["file"] for a in _read(out / "manifest.json")["assets"]}
    assert {e["ticker"] for e in pub["top"]} | {"SPY", "AGG"} <= set(files)
    a = _read(out / files[pub["top"][0]["ticker"]])
    assert a["in_top"] is True and a["ranking"]["rank"] == 1
    assert a["price"]["dates"][-1] == pub["asof"]
    assert len(a["factors"]) > 0 and all(
        f["percentile"] is None or 0 <= f["percentile"] <= 1 for f in a["factors"]
    )
    assert a["backtest"]["available"] is True
    assert a["rank_history"][-1] == {"date": pub["asof"], "rank": 1, "source": "daily"}


def test_publish_changes_use_point_in_time_previous_ranking(
    site: tuple[ParquetStore, Path],
) -> None:
    store, out = site
    ch = _read(out / "changes.json")
    factors = store.read("features", "factors")
    assert factors is not None
    days = sorted(factors["date"].unique())
    assert ch["prev_asof"] == str(pd.Timestamp(days[-2]).date())
    # The previous ranking must equal a stand-alone `qrd rank --asof prev` run.
    assert main(["rank", "--data-dir", str(store.root), "--asof", ch["prev_asof"]]) == 0
    prev = _read(store.root / "rankings" / f"top50-{ch['prev_asof']}.json")
    cur = _read(out / "rankings.json")
    prev_set = {e["ticker"] for e in prev["top"]}
    cur_set = {e["ticker"] for e in cur["top"]}
    assert {e["ticker"] for e in ch["entered"]} == cur_set - prev_set
    assert {e["ticker"] for e in ch["exited"]} == prev_set - cur_set
    prev_rank = {e["ticker"]: e["rank"] for e in prev["top"]}
    assert all(e["prev_rank"] == prev_rank.get(e["ticker"]) for e in cur["top"])


def test_publish_macro_has_curve_and_regime(site: tuple[ParquetStore, Path]) -> None:
    _, out = site
    m = _read(out / "macro.json")
    assert m["dates"][-1] == m["asof"]
    assert m["curves"][0]["label"] == "今日"
    assert {p["tenor"] for p in m["curves"][0]["points"]} >= {"3M", "2Y", "10Y"}
    assert sum(s["days"] for s in m["regime"]["segments"]) == len(m["regime"]["dates"])
    assert m["sources"]["vix"]["source"] == "FIXTURE"


def test_publish_without_ranking_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["publish", "--data-dir", str(tmp_path), "--out", str(tmp_path / "o")]) == 1
    assert "run `qrd rank` first" in capsys.readouterr().err

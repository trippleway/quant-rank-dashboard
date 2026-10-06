"""Publish stage: pipeline outputs → versioned static JSON for the web frontend.

Inputs are what earlier stages stored under ``data/`` (latest ranking + score table,
features, regime, macro panel, prices, backtest, ingest logs and quality reports). Nothing
here re-fits or re-scores today's ranking: ``rankings.json`` is the stored ``latest.json``
plus display helpers. The previous session's ranking (for ``changes.json``) is recomputed
with the same ``rank_asof`` from features dated on that session, so it is point-in-time.

Output layout (``SCHEMA_VERSION`` applies to every file)::

    manifest.json        asof, files, data health, disclaimer
    rankings.json        Top 50 with breakdown, sparklines and previous rank
    changes.json         entries / exits / big movers vs the previous session, with reasons
    macro.json           macro series, yield-curve snapshots, regime timeline
    backtest.json        stored backtest payload (unchanged)
    assets/<KEY>.json    price + moving averages, factor percentiles, rank history,
                         buy-and-hold backtest of the single asset
"""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from qrd import DISCLAIMER
from qrd.backtest.metrics import YEAR, drawdown, equity_curve, perf_metrics
from qrd.config import Settings
from qrd.features.build import load_prices
from qrd.features.factors import BENCHMARK
from qrd.ingest.macro import MACRO_SPECS
from qrd.scoring.config import GROUPS, ScoringConfig
from qrd.scoring.rank import rank_asof, to_json
from qrd.storage import ParquetStore, file_key

SCHEMA_VERSION = "1.0"
SPARKLINE_SESSIONS = 63
MOVER_THRESHOLD = 5
HISTORY_YEARS = 5
MIN_BACKTEST_SESSIONS = YEAR  # PLAN §5: at least 12 months for a backtest
MA_WINDOWS = (50, 200)
CURVE_TENORS: tuple[tuple[str, str], ...] = (
    ("3M", "ust_3m"),
    ("2Y", "ust_2y"),
    ("5Y", "ust_5y"),
    ("10Y", "ust_10y"),
    ("30Y", "ust_30y"),
)
CURVE_LOOKBACKS = (("今日", 0), ("1 個月前", 21), ("1 年前", 252))
EXTRA_ASSETS = (BENCHMARK, "AGG")
GROUP_LABELS = {
    "momentum": "動能",
    "low_risk": "低風險",
    "liquidity": "流動性",
    "yield": "收益率",
    "duration": "存續期",
}
REGIME_LABELS = {"risk_on": "risk-on", "neutral": "neutral", "risk_off": "risk-off"}
NOTES = (
    "所有數字由 pipeline 以真實資料產生；前端不得以假資料替代。",
    "Regime 與宏觀序列是總體與國際局勢的代理指標，不是局勢本身的量測。",
    "單一標的回測為買進持有的歷史模擬（含存活者偏誤與調整價限制），不是排名策略、也不是預期報酬。",
)


def _num(x: Any, digits: int = 4) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, digits) if math.isfinite(v) else None


def _day(ts: Any) -> str:
    return str(pd.Timestamp(ts).date())


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _envelope(kind: str, asof: str, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "asof": asof,
        "generated_at": generated_at,
        "disclaimer": DISCLAIMER,
    }


# --- changes ----------------------------------------------------------------------------


def group_contributions(scored: pd.DataFrame, cfg: ScoringConfig) -> pd.DataFrame:
    """ticker × group sum of factor contributions to the composite."""
    out = pd.DataFrame(index=scored["ticker"].to_numpy())
    for g in GROUPS:
        cols = [f"contrib_{s.column}" for s in cfg.factors if s.group == g]
        cols = [c for c in cols if c in scored.columns]
        out[g] = scored[cols].fillna(0.0).sum(axis=1).to_numpy() if cols else 0.0
    return out


def _score_positions(scored: pd.DataFrame) -> pd.Series:
    """1-based position by score among eligible tickers (before Top-N constraints)."""
    s = scored.set_index("ticker")["score"].dropna()
    order = sorted(s.index, key=lambda t: (-float(s[t]), t))
    return pd.Series(range(1, len(order) + 1), index=order, dtype="int64")


def _driver(delta: pd.Series, sign: int) -> str | None:
    """Largest group contribution change in direction ``sign`` as text."""
    d = delta[delta * sign > 0]
    if d.empty:
        return None
    g = str(d.abs().idxmax())
    return f"{GROUP_LABELS.get(g, g)}貢獻 {float(d[g]):+.3f}"


class _Diff:
    """Lookups shared by the entry / exit / mover explanations."""

    def __init__(
        self,
        cur: dict[str, Any],
        prev: dict[str, Any],
        cur_scored: pd.DataFrame,
        prev_scored: pd.DataFrame,
        cfg: ScoringConfig,
    ) -> None:
        self.gc_cur = group_contributions(cur_scored, cfg)
        self.gc_prev = group_contributions(prev_scored, cfg)
        self.pos_cur = _score_positions(cur_scored)
        self.score_cur = cur_scored.set_index("ticker")["score"]
        self.score_prev = prev_scored.set_index("ticker")["score"]
        self.skipped = {s["ticker"]: s["reason"] for s in cur.get("skipped", [])}
        self.inel = {s["ticker"]: s["reason"] for s in cur.get("ineligible", [])}
        self.top_n = cur["constraints"]["top_n"]
        w0, w1 = prev["regime"]["weights_regime"], cur["regime"]["weights_regime"]
        self.regime_changed = w0 != w1
        self.regime_note = f"Regime 權重組由 {w0} 轉為 {w1}，因子權重改變" if w0 != w1 else None

    def driver(self, t: str, sign: int) -> list[str]:
        if t not in self.gc_cur.index or t not in self.gc_prev.index:
            return []
        diff = self.gc_cur.loc[t].astype(float) - self.gc_prev.loc[t].astype(float)
        d = _driver(pd.Series(diff, dtype=float), sign)
        return [d] if d else []

    def scores(self, t: str) -> dict[str, float | None]:
        return {
            "score_prev": _num(self.score_prev[t]) if t in self.score_prev.index else None,
            "score": _num(self.score_cur[t]) if t in self.score_cur.index else None,
        }

    def regime(self) -> list[str]:
        return [self.regime_note] if self.regime_note else []

    def exit_status(self, t: str) -> list[str]:
        if t in self.inel:
            return [f"今日不合格：{self.inel[t]}"]
        if t in self.skipped:
            return [f"受約束排除：{self.skipped[t]}"]
        if t in self.pos_cur.index:
            return [f"分數排序第 {int(self.pos_cur[t])}，未進前 {self.top_n}"]
        return []


def compute_changes(
    cur: dict[str, Any],
    prev: dict[str, Any],
    cur_scored: pd.DataFrame,
    prev_scored: pd.DataFrame,
    *,
    cfg: ScoringConfig | None = None,
    threshold: int = MOVER_THRESHOLD,
) -> dict[str, Any]:
    """Entries, exits and big rank moves between two Top-N payloads, with reasons.

    Both rankings must be point-in-time on their own ``asof``; this function only compares.
    """
    dx = _Diff(cur, prev, cur_scored, prev_scored, cfg or ScoringConfig())
    cur_rank = {e["ticker"]: e for e in cur["top"]}
    prev_rank = {e["ticker"]: e for e in prev["top"]}

    entered = []
    for t in sorted(set(cur_rank) - set(prev_rank), key=lambda t: cur_rank[t]["rank"]):
        e, sc = cur_rank[t], dx.scores(t)
        why = dx.driver(t, +1)
        if sc["score_prev"] is None:
            why.append("前一交易日不在合格名單（流動性／資料）")
        why += dx.regime() + [f"主要入選因子：{r['label']}" for r in e["reasons"][:1]]
        entered.append(
            {"ticker": t, "rank": e["rank"], "asset_class": e["asset_class"], **sc, "reasons": why}
        )

    exited = [
        {
            "ticker": t,
            "prev_rank": prev_rank[t]["rank"],
            "asset_class": prev_rank[t]["asset_class"],
            **dx.scores(t),
            "reasons": dx.exit_status(t) + dx.driver(t, -1) + dx.regime(),
        }
        for t in sorted(set(prev_rank) - set(cur_rank), key=lambda t: prev_rank[t]["rank"])
    ]

    movers = []
    for t, e in cur_rank.items():
        move = prev_rank[t]["rank"] - e["rank"] if t in prev_rank else 0  # positive = up
        if abs(move) < threshold or t not in prev_rank:
            continue
        why = dx.driver(t, 1 if move > 0 else -1) + dx.regime()
        movers.append(
            {
                "ticker": t,
                "rank": e["rank"],
                "prev_rank": prev_rank[t]["rank"],
                "change": move,
                "asset_class": e["asset_class"],
                **dx.scores(t),
                "reasons": why or ["其他標的分數變動造成的相對排序變化"],
            }
        )
    movers.sort(key=lambda m: (-abs(m["change"]), m["ticker"]))
    return {
        "asof": cur["asof"],
        "prev_asof": prev["asof"],
        "regime": {"prev": prev["regime"]["label"], "cur": cur["regime"]["label"]},
        "regime_changed": dx.regime_changed,
        "threshold": threshold,
        "entered": entered,
        "exited": exited,
        "movers": movers,
        "unchanged": sum(
            1 for t in cur_rank if t in prev_rank and cur_rank[t]["rank"] == prev_rank[t]["rank"]
        ),
    }


# --- assets -----------------------------------------------------------------------------


def buy_and_hold(
    close: pd.Series, benchmark: pd.Series | None, rf: pd.Series | None, asof: pd.Timestamp
) -> dict[str, Any]:
    """Buy-and-hold simulation of one asset over its last ``HISTORY_YEARS`` (<= asof)."""
    px = close[close.index <= asof].dropna()
    start = asof - pd.DateOffset(years=HISTORY_YEARS)
    px = px[px.index >= start]
    r = px.pct_change().iloc[1:]
    if len(r) < MIN_BACKTEST_SESSIONS:
        return {
            "available": False,
            "reason": f"歷史 {len(r)} 個交易日，不足 {MIN_BACKTEST_SESSIONS}（12 個月）",
        }
    out: dict[str, Any] = {
        "available": True,
        "start": _day(r.index[0]),
        "end": _day(r.index[-1]),
        "years": round(len(r) / YEAR, 2),
        "shortened": bool(r.index[0] > start + pd.Timedelta(days=10)),
        "metrics": {k: _num(v, 6) for k, v in perf_metrics(r, rf).items()},
    }
    weekly = equity_curve(r).resample("W-FRI").last().dropna()
    dd = drawdown(r).resample("W-FRI").min().reindex(weekly.index)
    series: dict[str, Any] = {
        "dates": [_day(d) for d in weekly.index],
        "equity": [_num(v, 5) for v in weekly],
        "drawdown": [_num(v, 5) for v in dd],
    }
    if benchmark is not None:
        b = benchmark.reindex(r.index)
        if b.notna().sum() >= MIN_BACKTEST_SESSIONS:
            out["benchmark_metrics"] = {k: _num(v, 6) for k, v in perf_metrics(b, rf).items()}
            beq = equity_curve(b).resample("W-FRI").last().reindex(weekly.index)
            series["benchmark"] = [_num(v, 5) for v in beq]
    out["series"] = series
    return out


def price_block(close: pd.Series, asof: pd.Timestamp) -> dict[str, Any]:
    px = close[close.index <= asof].dropna()
    mas = {f"ma{w}": px.rolling(w, min_periods=w).mean() for w in MA_WINDOWS}
    start = asof - pd.DateOffset(years=HISTORY_YEARS)
    keep = px.index >= start
    return {
        "dates": [_day(d) for d in px.index[keep]],
        "close": [_num(v, 4) for v in px[keep]],
        **{k: [_num(v, 4) for v in m[keep]] for k, m in mas.items()},
    }


def factor_percentiles(
    scored: pd.DataFrame, ticker: str, cfg: ScoringConfig
) -> list[dict[str, Any]]:
    """Each factor's z-score and its percentile among eligible tickers on asof."""
    elig = scored[scored["score"].notna()]
    row = scored[scored["ticker"] == ticker]
    out = []
    for s in cfg.factors:
        col = f"z_{s.column}"
        if col not in scored.columns or row.empty:
            continue
        z = row[col].iloc[0]
        vals = elig[col].dropna()
        pct = (
            float((vals < z).mean() + 0.5 * (vals == z).mean())
            if pd.notna(z) and len(vals)
            else None
        )
        out.append(
            {
                "factor": s.column,
                "label": s.label,
                "group": s.group,
                "value": _num(row[s.column].iloc[0], 6) if s.column in row.columns else None,
                "z": _num(z),
                "percentile": _num(pct, 3),
            }
        )
    return out


def rank_history(
    ticker: str, holdings: pd.DataFrame | None, points: list[tuple[str, int | None, str]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if holdings is not None and not holdings.empty:
        h = holdings[holdings["ticker"] == ticker].set_index("signal_date")["rank"]
        for d in sorted(holdings["signal_date"].unique()):
            v = h.get(d)
            rows.append(
                {
                    "date": _day(d),
                    "rank": int(v) if v is not None and pd.notna(v) else None,
                    "source": "backtest_monthly",
                }
            )
    seen = {r["date"] for r in rows}
    for d, rk, src in points:
        if d not in seen:
            rows.append({"date": d, "rank": rk, "source": src})
    return sorted(rows, key=lambda r: r["date"])


# --- macro ------------------------------------------------------------------------------


def regime_segments(regime: pd.DataFrame) -> list[dict[str, Any]]:
    r = regime.sort_values("date")
    segs: list[dict[str, Any]] = []
    for d, lab in zip(r["date"], r["regime"], strict=True):
        if segs and segs[-1]["regime"] == lab:
            segs[-1]["end"] = _day(d)
            segs[-1]["days"] += 1
        else:
            segs.append({"regime": str(lab), "start": _day(d), "end": _day(d), "days": 1})
    return segs


def macro_block(
    panel: pd.DataFrame, regime: pd.DataFrame, store: ParquetStore, asof: pd.Timestamp
) -> dict[str, Any]:
    p = panel.copy()
    if "date" in p.columns:
        p = p.set_index("date")
    p = p[(p.index <= asof) & (p.index >= asof - pd.DateOffset(years=HISTORY_YEARS))]
    meta = {s.series: s.description for s in MACRO_SPECS}
    sources: dict[str, Any] = {}
    for col in p.columns:
        raw = store.read("macro", col)
        info: dict[str, Any] = {"description": meta.get(col, col)}
        if raw is not None and not raw.empty:
            last = raw.sort_values("obs_date").iloc[-1]
            info |= {
                "source": str(last["source"]),
                "is_proxy": bool(last.get("is_proxy", False)),
                "last_obs": _day(last["obs_date"]),
            }
        else:
            info |= {"source": None, "is_proxy": None, "last_obs": None}
        valid = p[col].dropna()
        info["last_value"] = _num(valid.iloc[-1]) if len(valid) else None
        info["coverage"] = _num(float(p[col].notna().mean()) if len(p) else 0.0, 3)
        sources[col] = info
    curves = []
    for label, back in CURVE_LOOKBACKS:
        if len(p) <= back:
            continue
        row = p.iloc[-1 - back]
        curves.append(
            {
                "label": label,
                "date": _day(p.index[-1 - back]),
                "points": [
                    {"tenor": t, "value": _num(row.get(col))}
                    for t, col in CURVE_TENORS
                    if col in p.columns
                ],
            }
        )
    reg = regime.copy()
    if "date" not in reg.columns:
        reg = reg.reset_index()
    reg = reg[(reg["date"] <= asof) & (reg["date"] >= p.index.min())] if len(p) else reg.iloc[:0]
    return {
        "dates": [_day(d) for d in p.index],
        "series": {c: [_num(v) for v in p[c]] for c in p.columns},
        "sources": sources,
        "curves": curves,
        "regime": {
            "dates": [_day(d) for d in reg["date"]],
            "label": [str(x) for x in reg["regime"]],
            "stress_score": [_num(x) for x in reg["stress_score"]],
            "segments": regime_segments(reg),
        },
    }


# --- health -----------------------------------------------------------------------------


RECENT_RUNS = 5


def _recent_json(folder: Path, pattern: str, n: int = RECENT_RUNS) -> list[tuple[str, Any]]:
    files = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return [(f.name, json.loads(f.read_text(encoding="utf-8"))) for f in files[-n:]][::-1]


def health_block(settings: Settings, prices: pd.DataFrame, asof: pd.Timestamp) -> dict[str, Any]:
    """Freshness of every ticker on asof plus the most recent ingest runs and quality reports.

    Ingest runs can cover a subset of tickers (``--tickers``), so several runs are listed
    instead of treating the last one as the state of the whole store.
    """
    last_bar = prices.groupby("ticker")["date"].max()
    stale = sorted(last_bar[last_bar < asof].index.tolist())
    runs = []
    for name, log in _recent_json(settings.logs_dir, "ingest-*.json"):
        if not isinstance(log, dict):
            continue
        problems = [e for e in log.get("events", []) if e.get("status") != "ok"]
        runs.append(
            {
                "file": name,
                "started_at": log.get("started_at"),
                "summary": log.get("summary", {}),
                "problems_total": len(problems),
                "problems": problems[:20],
            }
        )
    reports = []
    for name, issues in _recent_json(settings.quality_dir, "quality-*.json"):
        if not isinstance(issues, list):
            continue
        by: dict[str, int] = {}
        for i in issues:
            k = f"{i.get('severity')}:{i.get('check')}"
            by[k] = by.get(k, 0) + 1
        errors = [i for i in issues if i.get("severity") == "error"]
        reports.append({"file": name, "issues": len(issues), "by_check": by, "errors": errors[:20]})
    degraded = bool(stale) or bool(runs and runs[0]["problems_total"])
    return {
        "status": "degraded" if degraded else "ok",
        "status_rule": "degraded = 有標的最後一根 K 線早於 asof，或最近一次 ingest 有非 ok 事件",
        "prices": {
            "tickers": len(last_bar),
            "fresh": int((last_bar >= asof).sum()),
            "stale": [{"ticker": t, "last_bar": _day(last_bar[t])} for t in stale[:100]],
        },
        "ingest_runs": runs,
        "quality_reports": reports,
    }


# --- wiring -----------------------------------------------------------------------------


@dataclass
class PublishInputs:
    ranking: dict[str, Any]
    scored: pd.DataFrame
    factors: pd.DataFrame
    regime: pd.DataFrame
    panel: pd.DataFrame
    prices: pd.DataFrame
    backtest: dict[str, Any] | None
    holdings: pd.DataFrame | None


def load_inputs(settings: Settings) -> PublishInputs:
    store = ParquetStore(settings.data_dir)
    latest = settings.rankings_dir / "latest.json"
    if not latest.is_file():
        raise RuntimeError(f"no ranking at {latest}; run `qrd rank` first")
    ranking = json.loads(latest.read_text(encoding="utf-8"))
    scored = store.read("rankings", f"scores-{ranking['asof']}")
    factors = store.read("features", "factors")
    regime = store.read("features", "regime")
    panel = store.read("features", "macro_panel")
    if scored is None or factors is None or regime is None or panel is None:
        raise RuntimeError("missing score table or features; run `qrd features` and `qrd rank`")
    bt_path = settings.backtest_dir / "latest.json"
    backtest = json.loads(bt_path.read_text(encoding="utf-8")) if bt_path.is_file() else None
    return PublishInputs(
        ranking=ranking,
        scored=scored,
        factors=factors,
        regime=regime,
        panel=panel,
        prices=load_prices(store),
        backtest=backtest,
        holdings=store.read("backtest", "holdings-monthly"),
    )


def _wide_close(prices: pd.DataFrame) -> pd.DataFrame:
    col = "adj_close" if "adj_close" in prices.columns else "close"
    return prices.pivot_table(index="date", columns="ticker", values=col).sort_index()


def _previous_changes(
    inputs: PublishInputs, asof: pd.Timestamp, cfg: ScoringConfig
) -> tuple[dict[str, Any], dict[str, int]]:
    """Changes vs the previous session, ranked point-in-time on that session."""
    prior = sorted(d for d in inputs.factors["date"].unique() if pd.Timestamp(d) < asof)
    if not prior:
        empty = {"asof": inputs.ranking["asof"], "prev_asof": None, "entered": [], "exited": []}
        return empty | {"movers": [], "regime": None, "regime_changed": False, "unchanged": 0}, {}
    prev_day = pd.Timestamp(prior[-1])
    prev_res = rank_asof(inputs.factors, inputs.regime, inputs.prices, asof=prev_day, cfg=cfg)
    prev_payload = to_json(prev_res)
    ranks = {e["ticker"]: e["rank"] for e in prev_payload["top"]}
    return compute_changes(
        inputs.ranking, prev_payload, inputs.scored, prev_res.scored, cfg=cfg
    ), ranks


def _rankings_payload(
    ranking: dict[str, Any], close: pd.DataFrame, prev_ranks: dict[str, int], stamp: str
) -> dict[str, Any]:
    asof = pd.Timestamp(ranking["asof"])
    top = []
    for e in ranking["top"]:
        t = e["ticker"]
        px = close[t].loc[:asof].dropna().tail(SPARKLINE_SESSIONS) if t in close else pd.Series()
        top.append(
            {
                **e,
                "prev_rank": prev_ranks.get(t),
                "sparkline": [_num(v, 4) for v in px],
                "ret_1d": _num(px.iloc[-1] / px.iloc[-2] - 1, 6) if len(px) > 1 else None,
            }
        )
    return {
        **ranking,
        "top": top,
        "generated_at": stamp,
        "ranking_generated_at": ranking.get("generated_at"),
        "group_labels": GROUP_LABELS,
    }


def _risk_free(panel: pd.DataFrame, calendar: pd.Index) -> pd.Series | None:
    """Daily 3-month bill return known at the prior close (same as the backtest)."""
    p = panel.set_index("date") if "date" in panel.columns else panel
    if "ust_3m" not in p.columns:
        return None
    rate = p["ust_3m"].astype(float).reindex(calendar).ffill()
    return (rate / 100 / YEAR).shift(1).fillna(0.0)


def _write_assets(
    inputs: PublishInputs,
    close: pd.DataFrame,
    changes: dict[str, Any],
    prev_ranks: dict[str, int],
    out_dir: Path,
    *,
    stamp: str,
    cfg: ScoringConfig,
) -> list[dict[str, Any]]:
    ranking = inputs.ranking
    asof = pd.Timestamp(ranking["asof"])
    rf = _risk_free(inputs.panel, close.index)
    bench = close[BENCHMARK].pct_change() if BENCHMARK in close else None
    by_ticker = {e["ticker"]: e for e in ranking["top"]}
    exited = [x["ticker"] for x in changes["exited"]]
    wanted = [t for t in dict.fromkeys([*by_ticker, *exited, *EXTRA_ASSETS]) if t in close]
    meta = inputs.scored.set_index("ticker")
    index = []
    for t in wanted:
        entry = by_ticker.get(t)
        known = t in meta.index
        info = {
            "ticker": t,
            "asset_class": str(meta.at[t, "asset_class"]) if known else None,
            "category": str(meta.at[t, "category"]) if known else None,
            "leverage": _num(meta.at[t, "leverage"]) if known else None,
        }
        points = [(ranking["asof"], entry["rank"] if entry else None, "daily")]
        if changes.get("prev_asof"):
            points.append((changes["prev_asof"], prev_ranks.get(t), "daily"))
        payload = {
            **_envelope("asset", ranking["asof"], stamp),
            **info,
            "in_top": entry is not None,
            "ranking": entry,
            "score": _num(meta.at[t, "score"]) if known else None,
            "factors": factor_percentiles(inputs.scored, t, cfg),
            "price": price_block(close[t], asof),
            "rank_history": rank_history(t, inputs.holdings, points),
            "rank_history_note": "月度點為回測訊號日的排名（回測榜，排除歷史不足一年者）；"
            "每日點為每日榜。空值代表當日未進榜。",
            "backtest": buy_and_hold(close[t], bench if t != BENCHMARK else None, rf, asof),
        }
        name = f"assets/{file_key(t)}.json"
        _write_json(out_dir / name, payload)
        index.append({"ticker": t, "file": name, "in_top": entry is not None, **info})
    return index


def _replace_dir(staging: Path, out_dir: Path) -> None:
    """Swap the freshly built site into place; never delete a foreign directory."""
    if out_dir.exists():
        if any(out_dir.iterdir()) and not (out_dir / "manifest.json").is_file():
            shutil.rmtree(staging)
            raise RuntimeError(f"{out_dir} exists and is not a published site; refusing to replace")
        shutil.rmtree(out_dir)
    staging.rename(out_dir)


def build_site(settings: Settings, inputs: PublishInputs, out_dir: Path) -> dict[str, Any]:
    """Write every frontend JSON under ``out_dir`` (built aside, then swapped in)."""
    cfg = ScoringConfig()
    ranking = inputs.ranking
    asof = pd.Timestamp(ranking["asof"])
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    warnings: list[str] = []
    feat_end = pd.Timestamp(inputs.factors["date"].max())
    if feat_end > asof:
        warnings.append(f"排名 asof {asof.date()} 早於最新特徵 {feat_end.date()}；請重跑 qrd rank")
    staging = out_dir.with_name(out_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    close = _wide_close(inputs.prices)

    changes, prev_ranks = _previous_changes(inputs, asof, cfg)
    if changes["prev_asof"] is None:
        warnings.append("沒有前一交易日的特徵，無法計算異動")
    _write_json(
        staging / "changes.json", {**_envelope("changes", ranking["asof"], stamp), **changes}
    )
    _write_json(staging / "rankings.json", _rankings_payload(ranking, close, prev_ranks, stamp))
    macro = macro_block(inputs.panel, inputs.regime, ParquetStore(settings.data_dir), asof)
    _write_json(staging / "macro.json", {**_envelope("macro", ranking["asof"], stamp), **macro})
    files = ["manifest.json", "rankings.json", "changes.json", "macro.json"]
    if inputs.backtest is not None:
        _write_json(staging / "backtest.json", inputs.backtest)
        files.append("backtest.json")
    else:
        warnings.append("沒有回測輸出；請執行 qrd backtest")
    assets = _write_assets(inputs, close, changes, prev_ranks, staging, stamp=stamp, cfg=cfg)
    manifest = {
        **_envelope("manifest", ranking["asof"], stamp),
        "notes": list(NOTES),
        "demo": False,
        "files": files,
        "assets": assets,
        "ranking_asof": ranking["asof"],
        "backtest_asof": inputs.backtest["asof"] if inputs.backtest else None,
        "features_end": _day(feat_end),
        "health": health_block(settings, inputs.prices, asof),
        "warnings": warnings,
    }
    _write_json(staging / "manifest.json", manifest)
    _replace_dir(staging, out_dir)
    return manifest


def run_publish(settings: Settings, out_dir: Path) -> dict[str, Any]:
    inputs = load_inputs(settings)
    manifest = build_site(settings, inputs, out_dir)
    return {
        "asof": manifest["asof"],
        "out_dir": str(out_dir),
        "files": manifest["files"],
        "assets": len(manifest["assets"]),
        "health": manifest["health"]["status"],
        "warnings": manifest["warnings"],
    }

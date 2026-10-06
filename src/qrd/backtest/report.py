"""Backtest outputs: versioned JSON for the frontend and an auto-generated Markdown report.

Both always carry the disclaimer and the bias / limitation disclosures (PLAN §5): the
numbers are a historical simulation under stated assumptions, not expected returns.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qrd import DISCLAIMER
from qrd.backtest.metrics import drawdown, equity_curve, monthly_returns, rolling_sharpe
from qrd.backtest.run import (
    EQUAL_WEIGHT,
    FREQUENCIES,
    RANDOM_MEDIAN,
    SIXTY_FORTY,
    SPY,
    STRATEGY,
    BacktestConfig,
    BacktestResult,
    FrequencyResult,
    Market,
    deflated,
    ic_summary,
    metrics_table,
    regime_table,
    run_backtest,
    split_metrics,
    variant_table,
)
from qrd.config import Settings
from qrd.features.build import load_prices
from qrd.storage import ParquetStore

SCHEMA_VERSION = "1.0"
SERIES_LABELS = {
    STRATEGY: "策略（Top N 等權）",
    SPY: "SPY 買進持有",
    SIXTY_FORTY: "60/40（SPY/AGG，月再平衡）",
    EQUAL_WEIGHT: "等權重 universe",
    RANDOM_MEDIAN: "隨機選股（中位數）",
}

BIASES = (
    "存活者偏誤：universe 是 2026-10 的現有成分快照，回測期間已下市、被併購或被剔除的標的不在其中，"
    "會**高估**報酬（對等權重 universe 與隨機基準同樣適用，但不代表互相抵銷）。",
    "資料品質：價格來自 yfinance／Yahoo 的調整價，除權息與分割調整可能有誤或事後修訂；"
    "回測用的是今天下載的調整歷史，不是當時可得的版本。",
    "宏觀資料修訂：FRED 只提供最新修訂值（非 ALFRED vintage），發布日期已對齊，"
    "但修訂本身仍有 look-ahead。",
    "成交假設：訊號於 t 日收盤後產生、t+1 收盤成交；未模擬盤中衝擊、漲跌停、借券或無法成交。"
    "成本為依流動性分級的固定 bps 模型，實際價差與衝擊可能更高（尤其壓力期間）。",
    "容量：容量估計假設每次再平衡每檔最多成交其 60 日平均成交額的固定比例，僅為量級參考。",
    "多重檢定：參數敏感度與 ablation 共測試多組變體，表現最好的變體有選擇偏誤；"
    "Deflated Sharpe 只計入本報告列出的變體，開發過程中的隱性嘗試沒有計入，實際偏誤更大。",
    "參數未擬合：因子權重、門檻、懲罰皆為事前主觀設定，沒有用回測結果調整；"
    "樣本內／外切分用來檢查穩定度，不代表有做過「樣本內調參」。",
    "Regime 暖機：regime 需約一年 trailing 歷史，早期為 unknown（採 neutral 權重）；"
    "HY OAS 只有約 3 年、GDELT 只有約 3 個月歷史，早期 regime 由較少的成分決定。",
)


def _r(x: Any, digits: int = 6) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, digits) if math.isfinite(v) else None


def _clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        return _r(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


def _series_block(res: BacktestResult, fr: FrequencyResult) -> dict[str, Any]:
    t0 = fr.trade_idx[0]
    idx = res.market.calendar[t0:]
    rf = res.market.rf
    equity, dd, roll = {}, {}, {}
    for name, run in fr.runs.items():
        d = run.daily.iloc[t0:]
        equity[name] = [_r(v) for v in equity_curve(d)]
        dd[name] = [_r(v) for v in drawdown(d)]
        roll[name] = [_r(v, 4) for v in rolling_sharpe(d, rf, res.cfg.rolling_window)]
    if fr.random is not None:
        for col in fr.random.equity_quantiles.columns:
            equity[f"random_{col}"] = [_r(v) for v in fr.random.equity_quantiles[col]]
    return {
        "dates": [str(d.date()) for d in idx],
        "equity": equity,
        "drawdown": dd,
        "rolling_sharpe": roll,
        "rolling_window": res.cfg.rolling_window,
    }


def _monthly_block(fr: FrequencyResult) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for name in (STRATEGY, SPY):
        if name in fr.runs:
            m = monthly_returns(fr.runs[name].daily)
            out[name] = [
                {"year": int(y), "month": int(mo), "ret": _r(v)}
                for y, mo, v in m.itertuples(index=False)
            ]
    return out


def _random_block(fr: FrequencyResult, strategy: dict[str, float | None]) -> dict[str, Any]:
    rnd = fr.random
    if rnd is None:
        return {}

    def pct(arr: np.ndarray, value: float | None) -> float | None:
        a = arr[np.isfinite(arr)]
        return float((a < value).mean()) if value is not None and len(a) else None

    def dist(arr: np.ndarray) -> dict[str, float | None]:
        a = arr[np.isfinite(arr)]
        qs = np.quantile(a, [0.05, 0.25, 0.5, 0.75, 0.95]) if len(a) else [np.nan] * 5
        return {k: _r(v) for k, v in zip(["p05", "p25", "p50", "p75", "p95"], qs, strict=True)}

    return {
        "n": rnd.n,
        "seed": rnd.seed,
        "method": "每次再平衡從當期回測合格標的中均勻抽出與策略相同檔數，等權，同一成本模型",
        "cagr": dist(rnd.cagr),
        "sharpe": dist(rnd.sharpe),
        "max_drawdown": dist(rnd.max_drawdown),
        "strategy_percentile": {
            "cagr": pct(rnd.cagr, strategy.get("cagr")),
            "sharpe": pct(rnd.sharpe, strategy.get("sharpe")),
        },
    }


def _frequency_block(res: BacktestResult, fr: FrequencyResult) -> dict[str, Any]:
    metrics = metrics_table(res, fr)
    ic = fr.ic
    return {
        "frequency": fr.freq,
        "rebalances": len(fr.trade_idx),
        "first_trade": str(res.market.calendar[fr.trade_idx[0]].date()),
        "metrics": metrics,
        "split": split_metrics(res, fr),
        "random": _random_block(fr, metrics[STRATEGY]),
        "ic": {
            **ic_summary(fr),
            "series": [
                {"signal": str(s.date()), "ic": _r(a, 4), "rank_ic": _r(b, 4), "n": int(n)}
                for s, a, b, n in ic.itertuples(index=False)
            ],
        },
        "regimes": regime_table(res, fr),
        "capacity": fr.capacity,
        "monthly_returns": _monthly_block(fr),
        "series": _series_block(res, fr),
    }


def to_payload(res: BacktestResult, generated_at: datetime | None = None) -> dict[str, Any]:
    cfg = res.cfg
    stamp = (generated_at or datetime.now(UTC)).isoformat(timespec="seconds")
    years = (res.end - res.start).days / 365.25
    biases = list(BIASES)
    if res.shortened:
        biases.insert(
            0,
            f"回測期間縮短：要求自 {res.requested_start.date()} 起，但可用歷史只到 "
            f"{res.start.date()}（實際約 {years:.1f} 年）。",
        )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "backtest",
        "asof": str(res.end.date()),
        "generated_at": stamp,
        "disclaimer": DISCLAIMER,
        "headline": (
            "歷史模擬結果，不是預期報酬；請一併閱讀偏誤與限制。"
            "策略績效應與等權重 universe 與隨機基準比較，而非只看絕對報酬。"
        ),
        "period": {
            "start": str(res.start.date()),
            "end": str(res.end.date()),
            "years": years,
            "requested_start": str(res.requested_start.date()),
            "shortened": res.shortened,
            "in_sample_end": str(res.in_sample_end.date()),
        },
        "assumptions": {
            "signal": (
                "每週／每月第一個交易日收盤後，以當日（含）以前可得資料呼叫每日排名 rank_asof"
            ),
            "execution": "t+1 收盤成交；持有至下次成交，期間權重隨價格漂移",
            "weighting": "Top N 等權；不足 N 檔時等權持有實際入選檔數",
            "universe": "與每日排名相同的過濾，另排除歷史不足一年者（PLAN §5）",
            "costs": cfg.costs.describe(),
            "risk_free": res.market.rf_source,
            "cash": "未投入部位報酬 0",
            "primary_frequency": cfg.primary,
            "in_sample_years": cfg.in_sample_years,
            "parameters_fitted": False,
            "top_n": cfg.scoring.selection.top_n,
        },
        "series_labels": SERIES_LABELS,
        "frequencies": {f: _frequency_block(res, res.results[f]) for f in FREQUENCIES},
        "robustness": {
            "frequency": cfg.primary,
            "variants": variant_table(res) if res.variants else [],
            "deflated_sharpe": deflated(res) if res.variants else None,
            "note": (
                "變體只用來檢查結論對參數的敏感度；預設參數維持不變。"
                "「樣本內最佳」變體的樣本外表現用來示範選擇偏誤。"
            ),
        },
        "biases": biases,
    }
    cleaned: dict[str, Any] = _clean(payload)
    return cleaned


# --- Markdown -----------------------------------------------------------------------------


def _pct(x: Any, digits: int = 1) -> str:
    return "—" if x is None else f"{float(x) * 100:.{digits}f}%"


def _num(x: Any, digits: int = 2) -> str:
    return "—" if x is None else f"{float(x):.{digits}f}"


def _usd(x: Any) -> str:
    return "—" if x is None else f"${float(x) / 1e6:,.1f}M"


def _metrics_rows(metrics: dict[str, dict[str, Any]], labels: dict[str, str]) -> list[str]:
    head = "| 組合 | CAGR | 年化波動 | Sharpe | Sortino | MDD | Calmar | 年換手 | 年成本 |"
    rows = [head, "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in metrics.items():
        rows.append(
            f"| {labels.get(name, name)} | {_pct(m.get('cagr'))} | {_pct(m.get('ann_vol'))} | "
            f"{_num(m.get('sharpe'))} | {_num(m.get('sortino'))} | {_pct(m.get('max_drawdown'))} | "
            f"{_num(m.get('calmar'))} | {_num(m.get('turnover_annual'), 1)}× | "
            f"{_pct(m.get('cost_drag_annual'), 2)} |"
        )
    return rows


def render_markdown(p: dict[str, Any]) -> str:
    labels = p["series_labels"]
    per = p["period"]
    a = p["assumptions"]
    out = [
        "# 回測報告（自動產生）",
        "",
        f"> **{p['disclaimer']}** 僅供研究與學習，不構成投資建議。",
        f"> {p['headline']}",
        "",
        f"- 產生時間：{p['generated_at']}；資料截至 {p['asof']}；schema {p['schema_version']}",
        f"- 期間：{per['start']} ～ {per['end']}（約 {per['years']:.1f} 年）"
        + ("；**期間已縮短**" if per["shortened"] else ""),
        f"- 樣本內 / 樣本外切點：{per['in_sample_end']}（參數未以回測結果擬合）",
        f"- 主要頻率（事前選定，用於穩健性檢查）：{a['primary_frequency']}",
        "",
        "## 假設",
        "",
        f"- 訊號：{a['signal']}",
        f"- 成交：{a['execution']}",
        f"- 權重：{a['weighting']}（N = {a['top_n']}）",
        f"- Universe：{a['universe']}",
        "- 成本（單邊）："
        + "、".join(
            (f"ADV ≥ {_usd(t['min_adv_usd'])}" if t["min_adv_usd"] else "其餘")
            + f": {t['bps']:g} bps"
            for t in a["costs"]["tiers_bps"]
        )
        + f"；槓桿/反向/VIX ETP ×{a['costs']['complex_multiplier']:g}",
        f"- 無風險利率：{a['risk_free']}；{a['cash']}",
        "",
    ]
    for f, blk in p["frequencies"].items():
        out += [
            f"## {'每週' if f == 'weekly' else '每月'}再平衡（{blk['rebalances']} 次，"
            f"首次成交 {blk['first_trade']}）",
            "",
            *_metrics_rows(blk["metrics"], labels),
            "",
        ]
        rnd = blk.get("random") or {}
        if rnd:
            sp = rnd["strategy_percentile"]
            out += [
                f"**隨機基準**（{rnd['n']} 次，seed {rnd['seed']}）：隨機組合 CAGR 中位數 "
                f"{_pct(rnd['cagr']['p50'])}（5%–95%：{_pct(rnd['cagr']['p05'])} ～ "
                f"{_pct(rnd['cagr']['p95'])}）；策略 CAGR 位於第 {_pct(sp['cagr'], 0)} 百分位，"
                f"Sharpe 位於第 {_pct(sp['sharpe'], 0)} 百分位。",
                "",
            ]
        ic = blk["ic"]
        out += [
            f"**訊號品質**：平均 IC {_num(ic.get('mean_ic'), 3)}、平均 Rank IC "
            f"{_num(ic.get('mean_rank_ic'), 3)}（t = {_num(ic.get('rank_ic_t'))}，"
            f"正值比例 {_pct(ic.get('rank_ic_hit_rate'), 0)}，{ic.get('periods')} 期）。",
        ]
        dec = ic.get("deciles")
        if dec:
            ann = dec["ann_return"]
            out += [
                "",
                "| 分數十分位 | " + " | ".join(ann) + " |",
                "|---|" + "---:|" * len(ann),
                "| 年化報酬 | " + " | ".join(_pct(v) for v in ann.values()) + " |",
                "",
                f"最高減最低十分位每期平均 {_pct(dec['top_minus_bottom_mean_period'], 2)}"
                f"（t = {_num(dec['top_minus_bottom_t'])}）。",
            ]
        out += [
            "",
            "| Regime（前一日收盤） | 天數 | 策略年化 | 策略 Sharpe | SPY 年化 | SPY Sharpe |",
        ]
        out += ["|---|---:|---:|---:|---:|---:|"]
        for reg, row in blk["regimes"].items():
            s, b = row.get(STRATEGY, {}), row.get(SPY, {})
            out.append(
                f"| {reg} | {row['days']} | {_pct(s.get('ann_return'))} | "
                f"{_num(s.get('sharpe'))} | {_pct(b.get('ann_return'))} | {_num(b.get('sharpe'))} |"
            )
        sp = blk["split"]
        out += ["", "| 區段 | 策略 CAGR | 策略 Sharpe | SPY CAGR | SPY Sharpe | 等權 CAGR |"]
        out += ["|---|---:|---:|---:|---:|---:|"]
        for seg, name in (("in_sample", "樣本內"), ("out_of_sample", "樣本外")):
            m = sp[seg]
            out.append(
                f"| {name} | {_pct(m[STRATEGY]['cagr'])} | {_num(m[STRATEGY]['sharpe'])} | "
                f"{_pct(m.get(SPY, {}).get('cagr'))} | {_num(m.get(SPY, {}).get('sharpe'))} | "
                f"{_pct(m.get(EQUAL_WEIGHT, {}).get('cagr'))} |"
            )
        cap = blk["capacity"]
        out += [
            "",
            f"**容量（量級參考）**：每檔每次最多成交 60 日 ADV 的 {_pct(cap['participation'], 0)}，"
            f"可容納資金中位數約 {_usd(cap['median_aum_usd'])}"
            f"（最差一期 {_usd(cap['min_aum_usd'])}）；"
            f"持股 ADV 中位數 {_usd(cap['median_holding_adv_usd'])}。",
            "",
        ]
    rob = p["robustness"]
    if rob["variants"]:
        out += [
            f"## 穩健性（{rob['frequency']}）",
            "",
            rob["note"],
            "",
            "| 變體 | 類型 | CAGR | Sharpe | MDD | 年換手 | 樣本內 Sharpe | 樣本外 Sharpe |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for v in rob["variants"]:
            out.append(
                f"| {v['label']} | {v['kind']} | {_pct(v['cagr'])} | {_num(v['sharpe'])} | "
                f"{_pct(v['max_drawdown'])} | {_num(v['turnover_annual'], 1)}× | "
                f"{_num(v['sharpe_in_sample'])} | {_num(v['sharpe_out_of_sample'])} |"
            )
        ranked = [v for v in rob["variants"] if v["sharpe_in_sample"] is not None]
        if ranked:
            best = max(ranked, key=lambda v: v["sharpe_in_sample"])
            out += [
                "",
                f"樣本內 Sharpe 最高的是「{best['label']}」（{_num(best['sharpe_in_sample'])}），"
                f"其樣本外 Sharpe 為 {_num(best['sharpe_out_of_sample'])}"
                f"（預設參數：樣本內 {_num(rob['variants'][0]['sharpe_in_sample'])}、"
                f"樣本外 {_num(rob['variants'][0]['sharpe_out_of_sample'])}）。"
                "依樣本內結果挑選變體，樣本外不保證維持同樣的優勢。",
            ]
        ds = rob["deflated_sharpe"]
        if ds:
            out += [
                "",
                f"**Deflated Sharpe**：試驗數 {int(ds['n_trials'] or 0)}，預設參數的 PSR(SR>0) = "
                f"{_num(ds['psr_vs_zero'])}，考慮多重檢定後 DSR = {_num(ds['deflated_sharpe'])}"
                "（< 0.95 表示無法排除運氣）。",
            ]
        out.append("")
    out += ["## 偏誤與限制", ""] + [f"- {b}" for b in p["biases"]]
    out += ["", f"> {p['disclaimer']} 僅供研究與學習，不構成投資建議。", ""]
    return "\n".join(out)


# --- storage wiring ---------------------------------------------------------------------


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def holdings_frame(res: BacktestResult, fr: FrequencyResult) -> pd.DataFrame:
    rows = []
    cal = res.market.calendar
    for step, t in zip(fr.steps, fr.trade_idx, strict=True):
        n = len(step.selected)
        for rank, ticker in enumerate(step.selected, start=1):
            rows.append(
                (
                    step.signal,
                    cal[t],
                    ticker,
                    rank,
                    float(step.scores[ticker]),
                    1.0 / n,
                    step.regime,
                )
            )
    cols = ["signal_date", "trade_date", "ticker", "rank", "score", "weight", "regime"]
    return pd.DataFrame(rows, columns=cols)


def write_outputs(
    res: BacktestResult, out_dir: Path, report_path: Path | None = None, *, latest: bool = True
) -> dict[str, str]:
    payload = to_payload(res)
    day = payload["asof"]
    paths: dict[str, Path] = {"json": out_dir / f"backtest-{day}.json"}
    if latest:
        paths["latest"] = out_dir / "latest.json"
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for key in ("json", "latest"):
        if key in paths:
            _write_text(paths[key], text)
    md = render_markdown(payload)
    paths["report"] = out_dir / f"report-{day}.md"
    _write_text(paths["report"], md)
    if report_path is not None:
        paths["report_copy"] = report_path
        _write_text(report_path, md)
    store = ParquetStore(out_dir.parent)
    for f, fr in res.results.items():
        paths[f"holdings_{f}"] = store.write(out_dir.name, f"holdings-{f}", holdings_frame(res, fr))
        daily = pd.DataFrame({k: r.daily for k, r in fr.runs.items()}).dropna(how="all")
        paths[f"daily_{f}"] = store.write(
            out_dir.name, f"daily-{f}", daily.rename_axis("date").reset_index()
        )
    return {k: str(v) for k, v in paths.items()}


def run_stored_backtest(
    settings: Settings, cfg: BacktestConfig | None = None, report_path: Path | None = None
) -> dict[str, Any]:
    """Backtest from stored features + prices; write outputs. Returns a summary."""
    store = ParquetStore(settings.data_dir)
    factors = store.read("features", "factors")
    regime = store.read("features", "regime")
    panel = store.read("features", "macro_panel")
    if factors is None or regime is None or factors.empty:
        raise RuntimeError(f"no features under {settings.data_dir}; run `qrd features` first")
    market = Market.build(factors, regime, load_prices(store), panel)
    res = run_backtest(market, cfg)
    c = res.cfg
    paths = write_outputs(res, settings.backtest_dir, report_path, latest=c.end is None)
    prim = metrics_table(res, res.results[c.primary])
    return {
        "period": f"{res.start.date()}..{res.end.date()}",
        "shortened": res.shortened,
        "primary": c.primary,
        "rebalances": {f: len(r.trade_idx) for f, r in res.results.items()},
        "metrics": {
            name: {k: _r(m.get(k), 4) for k in ("cagr", "sharpe", "max_drawdown")}
            for name, m in prim.items()
        },
        "variants": len(res.variants),
        "paths": paths,
    }

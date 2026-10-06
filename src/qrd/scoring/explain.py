"""Human-readable explanations: selection reasons (top contributing factors) and main risks.

Risk labels are rule-based on the same point-in-time factors used for scoring. Texts are
Traditional Chinese for the dashboard; ``code`` is the stable machine key.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from qrd.scoring.config import FactorSpec

HIGH_VOL = 0.40
DEEP_DRAWDOWN = -0.30
HIGH_BETA = 1.5
LONG_DURATION = 10.0
LOW_ADV_USD = 20_000_000.0
MAX_RISKS = 3

SYSTEMATIC = {
    "equity": "個股與大盤同向下跌的市場風險",
    "equity_etf": "所追蹤市場／產業整體下跌的風險",
    "bond_etf": "利率上升或信用利差擴大的風險",
    "commodity_etf": "商品價格與期貨展期（roll）風險",
    "currency_etf": "匯率波動與央行政策風險",
    "volatility_etp": "波動率回落與期貨展期耗損",
}


def top_reasons(row: pd.Series, specs: tuple[FactorSpec, ...], n: int = 3) -> list[dict[str, Any]]:
    """The ``n`` factors with the largest positive contribution to the composite."""
    items = []
    for s in specs:
        contrib = float(row.get(f"contrib_{s.column}", 0.0))
        if contrib > 0:
            items.append((contrib, s))
    items.sort(key=lambda t: (-t[0], t[1].column))
    return [
        {
            "factor": s.column,
            "label": s.label,
            "group": s.group,
            "z": _num(row.get(f"z_{s.column}")),
            "contribution": round(contrib, 4),
        }
        for contrib, s in items[:n]
    ]


def main_risks(row: pd.Series) -> list[dict[str, str]]:
    """Up to ``MAX_RISKS`` risk labels, most severe first; always at least one."""
    risks: list[dict[str, str]] = []
    lev = float(row["leverage"])
    if row["asset_class"] == "volatility_etp":
        risks.append(
            {
                "code": "volatility_etp",
                "label": "波動率期貨 ETP：期貨展期（contango）長期侵蝕淨值，僅適合短期持有",
            }
        )
    if lev != 1:
        kind = "反向" if lev < 0 else "槓桿"
        risks.append(
            {
                "code": "leveraged_inverse",
                "label": f"{kind}產品（{lev:g}x，每日重設）：長期持有有波動耗損，持有期限宜短",
            }
        )
    vol = _float(row.get("vol_63"))
    if vol is not None and vol > HIGH_VOL:
        risks.append({"code": "high_volatility", "label": f"高波動：近 3 個月年化 {vol:.0%}"})
    dd = _float(row.get("max_dd_252"))
    if dd is not None and dd < DEEP_DRAWDOWN:
        risks.append({"code": "deep_drawdown", "label": f"過去一年最大回撤 {dd:.0%}"})
    beta = _float(row.get("beta_252"))
    if beta is not None and abs(beta) > HIGH_BETA:
        risks.append({"code": "high_beta", "label": f"對 SPY 的 beta {beta:.2f}"})
    dur = _float(row.get("rate_duration"))
    if row["asset_class"] == "bond_etf" and dur is not None and abs(dur) > LONG_DURATION:
        risks.append({"code": "rate_sensitive", "label": f"利率敏感：經驗存續期 {dur:.1f} 年"})
    adv = _float(row.get("adv_usd_60"))
    if adv is not None and adv < LOW_ADV_USD:
        risks.append(
            {"code": "low_liquidity", "label": f"流動性偏低：60 日平均成交額 ${adv / 1e6:.1f}M"}
        )
    short = row.get("short_history")
    if short is not None and not pd.isna(short) and bool(short):
        risks.append({"code": "short_history", "label": "歷史不足一年，因子信心低"})
    if not risks:
        risks.append(
            {"code": "systematic", "label": SYSTEMATIC.get(str(row["asset_class"]), "市場風險")}
        )
    return risks[:MAX_RISKS]


def _float(x: Any) -> float | None:
    """Finite float or None (NaN, None, non-numeric)."""
    if isinstance(x, bool) or not isinstance(x, int | float):
        return None
    return float(x) if math.isfinite(x) else None


def _num(x: Any, digits: int = 4) -> float | None:
    v = _float(x)
    return None if v is None else round(v, digits)

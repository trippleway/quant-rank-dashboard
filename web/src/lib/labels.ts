// UI labels for codes used in the pipeline JSON.

export const ASSET_CLASS: Record<string, string> = {
  equity: "個股",
  equity_etf: "股票 ETF",
  bond_etf: "債券 ETF",
  commodity_etf: "商品 ETF",
  currency_etf: "貨幣 ETF",
  volatility_etp: "波動率 ETP",
};

export const REGIME: Record<string, { label: string; icon: string; color: string }> = {
  risk_on: { label: "Risk-on", icon: "▲", color: "var(--status-good)" },
  neutral: { label: "Neutral", icon: "●", color: "var(--ink-muted)" },
  risk_off: { label: "Risk-off", icon: "▼", color: "var(--status-critical)" },
  unknown: { label: "Unknown", icon: "?", color: "var(--status-warning)" },
};

export const GROUP: Record<string, string> = {
  momentum: "動能",
  low_risk: "低風險",
  liquidity: "流動性",
  yield: "收益率",
  duration: "存續期",
};

export const MACRO: Record<string, { label: string; unit: string }> = {
  ust_3m: { label: "3 個月國庫券殖利率", unit: "%" },
  ust_2y: { label: "2 年期殖利率", unit: "%" },
  ust_5y: { label: "5 年期殖利率", unit: "%" },
  ust_10y: { label: "10 年期殖利率", unit: "%" },
  ust_30y: { label: "30 年期殖利率", unit: "%" },
  curve_10y2y: { label: "殖利率曲線 10Y−2Y", unit: "pp" },
  breakeven_10y: { label: "10 年平衡通膨", unit: "%" },
  hy_oas: { label: "高收益債利差 (HY OAS)", unit: "%" },
  ig_oas: { label: "投資級債利差 (IG OAS)", unit: "%" },
  vix: { label: "VIX", unit: "" },
  usd_broad: { label: "美元指數（廣義）", unit: "" },
  wti: { label: "WTI 原油", unit: "$/bbl" },
  gold: { label: "黃金", unit: "$/oz" },
  gdelt_tone_economy: { label: "GDELT 經濟新聞語調", unit: "" },
  gdelt_tone_geopolitics: { label: "GDELT 地緣政治語調", unit: "" },
};

export const REGIME_COMPONENT: Record<string, string> = {
  vix: "VIX 水準",
  hy_oas: "高收益債利差",
  credit_proxy: "信用代理（HYG/IEF）",
  spy_trend: "SPY 趨勢",
  curve: "殖利率曲線",
  usd_mom: "美元動能",
  oil_mom: "油價動能",
  gold_mom: "黃金動能",
  gdelt_economy: "GDELT 經濟語調",
  gdelt_geopolitics: "GDELT 地緣語調",
};

export const SERIES_ORDER = ["strategy", "spy", "sixty_forty", "equal_weight", "random_median"];

export const leverageTag = (lev: number | null | undefined): string | null => {
  if (lev == null || lev === 1) return null;
  return lev < 0 ? `反向 ${lev}x` : `槓桿 ${lev}x`;
};

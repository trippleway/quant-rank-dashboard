# ADR 0003：因子與 regime 設計

- 狀態：已採用
- 日期：2026-10-06
- 里程碑：M2

## 背景

PLAN.md §4 要求每個標的每日計算動能、風險、品質/價值、流動性與資產類別專屬因子，並用 VIX、信用利差、曲線、
美元與油價動能、GDELT 語調把總體環境分成 risk-on / neutral / risk-off，且 regime 只能用「當日以前」的資料。
M2 驗收：因子與 regime 有單元測試；用測試證明沒有 look-ahead。

限制（M1 已知）：資料只有日頻價量與宏觀序列；免費來源沒有 point-in-time 財報；
`hy_oas`／`ig_oas` 只有約 3 年；GDELT 只有約 3 個月且常被限流。

## 決定

### 1. 時間對齊（防 look-ahead 的核心規則）

- 價格因子在 t 日使用 t 日（含）以前的 K 棒，供 t+1 交易（PLAN §5）。所有視窗都是 trailing：`shift(正數)`、`rolling` 不置中。
- 宏觀與情緒一律以 `available_date <= t` 對齊（`merge_asof`，backward），**絕不以 `obs_date` join**。
  晚到的舊觀測不會覆蓋較新的值。超過 21 個日曆天沒更新的值視為缺值，避免來源掛掉時默默凍結。
- Regime 的標準化用「自己過去的分位數」（trailing 756 日 `rolling.rank`），不用全期間的平均／標準差。
- 經驗存續期：由觀測日 d 以前的 (報酬, Δ殖利率) 配對估出的值，要到 `available_date(d)` 才能使用。
- 驗證（`tests/test_lookahead.py`）：
  1. 截斷：在多個切點 t，只用 t 時可得的資料重算，t 以前的因子、宏觀面板、regime 必須**完全相等**。
  2. 竄改：把 t 之後的價格亂乘、成交量歸零、t 之後才公布的宏觀值改成 1e6，t 以前結果不變。
  3. 金絲雀：故意用 `obs_date` join、或用置中視窗，檢查器必須抓到（證明測試不是永遠通過）。

### 2. 價格因子（`qrd.features.factors`）

| 類別 | 因子 |
|---|---|
| 動能 | `mom_12_1`（t−252→t−21）、`mom_6m`、`mom_3m`、`trend_200`（vs 200 日均線） |
| 風險 | `vol_63`、`downside_63`（年化）、`max_dd_252`（只看視窗內的高點）、`beta_252`（vs SPY） |
| 流動性／成本代理 | `adv_usd_60`、`amihud_60` |
| 收益／價值代理 | `trailing_yield_252`：過去 12 個月總報酬 ÷ 價格報酬 − 1（配息率代理）。只有視窗內的配息會影響比值，Yahoo 事後回溯調整不會洩漏未來 |
| 債券專屬 | `rate_duration`：−100 × cov(r, Δy10) / var(Δy10)，252 日、最少 126 筆 |
| 信心 | `history_sessions`、`short_history`（< 252 日） |

- 歷史不足 → NaN，不是 0（M3 會降權，不當作中性值）。
- 報酬用 `adj_close`；該列缺值時退回 `close`（只在備援來源沒有調整價時發生，品質檢查會標出）。

### 3. 不做的因子與理由（降權而非假造）

- **品質／價值（財報型）**：免費來源（yfinance `.info`）只有「現在」的財報快照，拿來回測就是 look-ahead。
  M2 不提供財報型因子；個股的價值面只有 `trailing_yield_252` 這個價格衍生代理。M3 對缺少的因子以重新正規化權重處理（=降權）。
  若日後接 point-in-time 財報源（付費），透過新 adapter 加入。
- **商品／貨幣的期限結構**：沒有免費的期貨曲線，M2 不提供；這兩類以動能與風險因子為主，文件與 UI 要說明。
- **曲線位置**：以 macro panel 的 `curve_10y2y` 與 ETF 的 `category`（短／中／長天期）在 M3 組合，不另做因子。

### 4. Regime（`qrd.features.regime`）

| 成分 | 輸入 | 方向 | 權重 |
|---|---|---|---|
| `vix` | VIX 水準 | 高 = 壓力 | 1 |
| `hy_oas` | 高收益債 OAS（FRED，約 3 年） | 高 = 壓力 | 1 |
| `credit_proxy` | HYG 相對 IEF 的 63 日 log 報酬（補 OAS 歷史不足） | 低 = 壓力 | 1 |
| `spy_trend` | SPY vs 200 日均線 | 低 = 壓力 | 1 |
| `curve` | 10y−2y | 低／倒掛 = 壓力 | 0.5 |
| `usd_mom` | 廣義美元 63 日 log 變化 | 強 = 壓力 | 0.5 |
| `oil_mom` | WTI 63 日 log 變化 | 急漲 = 壓力 | 0.5 |
| `gold_mom` | 黃金 63 日 log 變化 | 急漲 = 避險需求 | 0.5 |
| `gdelt_economy` / `gdelt_geopolitics` | GDELT 平均語調 | 低 = 壓力 | 0.25 各（最少 60 筆） |

- 每個成分：trailing 756 日分位數 p（最少 252 筆），分數 = 方向 × (2p − 1) ∈ [−1, 1]。
- 綜合壓力 = 可用成分的加權平均（缺的成分權重重新分配；`contrib_*` 欄位加總即為原始壓力，供 UI 解釋），再做 span 5 的因果 EWM。
- ≥ 0.25 → `risk_off`；≤ −0.25 → `risk_on`；其餘 `neutral`；可用成分 < 3 → `unknown`（M3 對 unknown 使用 neutral 權重）。
- 選擇規則式而非 HMM／分群：可解釋、參數少、不需要擬合（降低過度擬合風險）。代價是門檻與權重是主觀設定，
  M4 必須做敏感度掃描。

**這些都是代理指標**：油價、黃金、美元、GDELT 語調只是「國際局勢」可計算的影子，不是局勢本身。UI 與文件必須明講。

## 實測（2026-10-06，本機快取資料）

- 566 檔中最後交易日有因子的 563 檔（3 檔為 M1 的 `stale` warn），12 個數值因子在最後一天覆蓋率 100%。
- 經驗存續期合理：SHY 1.7、IEF 7.0、TLT 12.7、EDV 18.3、TMF 37.2、TBT −25.6；SSO beta 1.99。
- Regime：2022 年 153 個交易日為 `risk_off`；2025-04 關稅衝擊期間為 `risk_off`；2024 年以 `risk_on`／`neutral` 為主。
- 價格資料從 2019-10 開始，分位數需要 252 筆暖機 → regime 從約 2020-10 起才有值（2020-03 COVID 期間為 `unknown`）。
  PLAN 的 5 年回測期（約 2021-10 起）不受影響。
- 每年 regime 切換約 10–17 次；M4 需評估換手成本，必要時加遲滯（hysteresis）。

## 後果

- M3 以 `regime` 選權重、以 `contrib_*` 解釋；因子缺值降權。
- M4 回測直接重用 `build_features` + `point_in_time`，不另寫一套特徵程式。
- 已知風險：FRED 資料會修訂，但我們只存最新版本（非 vintage），對 VIX、殖利率影響很小，對 OAS 可能稍大；寫入 M4 偏誤揭露。

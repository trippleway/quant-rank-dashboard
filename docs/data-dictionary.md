# 資料字典

> 僅供研究與學習，不構成投資建議。設計理由見 [ADR 0002](adr/0002-data-sources-and-storage.md)。

所有資料由 `qrd ingest` 寫入 `data/`（不進 git；可用 `QRD_DATA_DIR` 改位置）。

## 價格 `data/prices/<TICKER>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | datetime64 | 交易所當地的交易日（無時區） |
| `ticker` | str | Yahoo 代碼（例：`BRK-B`） |
| `open` `high` `low` `close` | float | 未調整股利、但已調整分割的價格（Yahoo 慣例） |
| `adj_close` | float | 股利與分割調整後收盤價；報酬計算用這欄。來源未提供時為 NaN |
| `volume` | float | 成交量（股） |
| `source` | str | `yfinance` / `yahoo_chart` |

- 主來源 yfinance，備援 Yahoo chart HTTP（同一上游）；都失敗時沿用快取（`degraded`）。
- 增量：每次重抓最後 14 天；重疊區間與快取不符時整段重抓（新除息/分割）。
- 紐約 17:00 前不寫入當日 K 棒。
- 已知限制：yfinance 調整價品質不保證（偶有錯誤 tick、遺漏股利）；標的清單為現有成分 → 存活者偏誤。

## 宏觀 `data/macro/<series>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `obs_date` | datetime64 | 觀測日 |
| `available_date` | datetime64 | **最早可使用日**（觀測日 + 發布延遲）。特徵必須以此對齊 |
| `series` | str | 序列 id（下表） |
| `value` | float | 數值 |
| `source` | str | `fred_api` / `fred_csv` / `yfinance_proxy` |
| `is_proxy` | bool | 是否為代理資料（單位/定義可能與 FRED 原序列不同） |

| series | FRED | 代理 | 延遲（營業日） | 說明 / 限制 |
|---|---|---|---|---|
| `ust_3m` | DGS3MO | ^IRX | 1 | 3 個月公債殖利率 (%) |
| `ust_2y` | DGS2 | — | 1 | 2 年 |
| `ust_5y` | DGS5 | ^FVX | 1 | 5 年 |
| `ust_10y` | DGS10 | ^TNX | 1 | 10 年 |
| `ust_30y` | DGS30 | ^TYX | 1 | 30 年 |
| `curve_10y2y` | T10Y2Y | — | 1 | 10y − 2y 利差 (pp) |
| `breakeven_10y` | T10YIE | — | 1 | 10 年損益兩平通膨 |
| `hy_oas` | BAMLH0A0HYM2 | — | 1 | 高收益債 OAS；**FRED 只提供約最近 3 年** |
| `ig_oas` | BAMLC0A0CM | — | 1 | 投資級公司債 OAS；**約最近 3 年** |
| `vix` | VIXCLS | ^VIX | 1 | VIX 收盤 |
| `usd_broad` | DTWEXBGS | DX-Y.NYB | 7 | Fed 廣義美元指數（週更新）；代理 DXY 定義不同 |
| `wti` | DCOILWTICO | CL=F | 7 | WTI 現貨（EIA 週更新）；代理為近月期貨 |
| `gold` | — | GC=F | 0 | 黃金近月期貨（FRED 無免費序列，yfinance 為主來源） |

代理資料**永遠不會覆蓋**已存在的 FRED 序列。

## 情緒 / 國際局勢代理 `data/sentiment/<name>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `obs_date` | datetime64 | UTC 日 |
| `available_date` | datetime64 | 次一營業日 |
| `series` | str | `gdelt_tone_economy` / `gdelt_tone_geopolitics` |
| `value` | float | GDELT DOC 2.0 平均語調（負值 = 負面報導多） |
| `source` | str | `gdelt_doc` |

- **這是代理指標**：衡量新聞用語的正負面，不等於「國際局勢」本身。
- DOC API 只涵蓋最近約 3 個月；歷史從開始執行起每日累積，回測期間大部分沒有此資料。
- API 限流嚴格；失敗只降級，不影響其他資料。

## 執行紀錄與品質報告

- `data/logs/ingest-<UTC 時間>.json`：每個標的/序列的狀態 `ok`（主來源）/ `fallback`（備援）/ `degraded`（沿用舊快取）/ `failed`（無資料），以及來源與訊息。
- `data/quality/quality-<UTC 時間>.json`：品質問題清單（`ticker`, `check`, `severity`, `detail`, `date`）。
  `severity=error` 的標的為 unusable，下游排除。檢查項目見 `src/qrd/ingest/quality.py` 模組說明。

## Universe `src/qrd/universe/seeds.csv`

| 欄位 | 說明 |
|---|---|
| `ticker` | Yahoo 代碼 |
| `asset_class` | `equity` / `equity_etf` / `bond_etf` / `commodity_etf` / `currency_etf` / `volatility_etp` |
| `category` | 個股為 GICS 產業；ETF 為子類別（如 `treasury_long`） |
| `leverage` | 槓桿倍數，反向為負（例：`SQQQ` = −3、`SVXY` = −0.5） |
| `instrument` | `stock` / `etf` / `etn` |

載入後另有衍生欄位 `leveraged_or_inverse`（`leverage != 1`）。

## 特徵 `data/features/*.parquet`（`qrd features` 產出）

設計與 look-ahead 規則見 [ADR 0003](adr/0003-features-and-regime.md)。`--asof YYYY-MM-DD` 只用當日以前可得的資料重算。

### `factors.parquet`（每標的每交易日一列）

| 欄位 | 說明 |
|---|---|
| `date` `ticker` `asset_class` `category` `leverage` | 鍵與 universe 屬性；品質報告為 unusable 的標的不輸出 |
| `mom_12_1` `mom_6m` `mom_3m` | 動能（簡單報酬） |
| `trend_200` | 價格 / 200 日均線 − 1 |
| `vol_63` `downside_63` | 年化已實現波動／下行偏差 |
| `max_dd_252` | 過去 252 日內最大回撤（≤ 0） |
| `beta_252` | 對 SPY 的 beta |
| `adv_usd_60` `amihud_60` | 60 日平均成交額（美元）／Amihud 非流動性 × 1e6 |
| `trailing_yield_252` | 過去 12 個月配息率代理（總報酬 ÷ 價格報酬 − 1） |
| `rate_duration` | 經驗存續期（年），對 10 年殖利率變動回歸；債券 ETF 最有意義 |
| `history_sessions` `short_history` | 累計 K 棒數；< 252 為 `short_history`（信心低） |

歷史不足時為 NaN（不是 0）。

### `macro_panel.parquet`

`date` + 每條宏觀／情緒序列一欄：當日已公布（`available_date <= date`）的最新值；超過 21 天未更新為 NaN。

### `regime.parquet`

| 欄位 | 說明 |
|---|---|
| `date` | 交易日（SPY 日曆） |
| `stress_raw` | 各成分加權平均壓力 ∈ [−1, 1]（正 = 壓力大） |
| `stress_score` | `stress_raw` 的 span 5 因果 EWM，用來分類 |
| `regime` | `risk_on` / `neutral` / `risk_off` / `unknown`（可用成分 < 3） |
| `n_components` | 當日可用成分數 |
| `contrib_<成分>` | 該成分對 `stress_raw` 的貢獻；加總 = `stress_raw` |

Regime 輸入是**代理指標**，不是國際局勢本身的量測。

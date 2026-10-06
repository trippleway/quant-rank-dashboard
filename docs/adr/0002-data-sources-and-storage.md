# ADR 0002：資料來源、備援鏈與儲存

- 狀態：已採用
- 日期：2026-10-06
- 里程碑：M1

## 背景

PLAN.md §2、§3 要求只用免費來源（yfinance、FRED、GDELT、公開 RSS），每個來源都要有 adapter 與備援，
失敗時降級而不是讓 pipeline 崩潰；儲存用 Parquet + DuckDB，不用外部資料庫。
M1 驗收：≥300 檔 universe 可抓取、快取、增量更新；來源失敗會降級並記錄；有資料品質檢查。

開發時實測（2026-10-06）：

| 來源 | 結果 |
|---|---|
| yfinance 1.7 | 可用（批次下載） |
| Yahoo v8 chart HTTP（直接呼叫） | 帶 User-Agent 可用；不帶會 429 |
| FRED `fredgraph.csv`（不需 key） | 可用 |
| Stooq CSV | 改為 JavaScript 驗證頁，**無法程式化使用** |
| GDELT DOC 2.0 | 可用但限流嚴格（約每 5 秒 1 次），被限流時回純文字或 429 |

## 決定

### 1. 價格：yfinance → Yahoo chart HTTP → 快取降級

- 主來源 yfinance（每批 50 檔、timeout 20 秒、重試 3 次、指數退避）。
- 備援是直接呼叫 Yahoo v8 chart endpoint：**同一個上游**，但不依賴 yfinance 套件，能扛過套件改版或解析錯誤。
  上游本身全面中斷時兩者會一起失敗——這是已知限制。Stooq 原本是首選的獨立備援，但目前無法程式化存取。
- 兩者都失敗：保留既有快取，狀態記為 `degraded`；沒有快取記為 `failed`。整個 run 一定跑完。
- 備援 adapter 若拿不到調整價，`adj_close` 留 NaN（由品質檢查標出），**不拿 close 冒充**。
- 預留介面：`PriceSource` Protocol；未來可加付費來源而不動 pipeline。

### 2. 宏觀：FRED API（有 key）→ FRED 公開 CSV → yfinance 代理

- 沒有 `FRED_API_KEY` 也能取得完整 FRED 序列（公開 CSV），所以 key 不是必要條件。
- yfinance 代理（`^TNX`、`^VIX`、`DX-Y.NYB`、`CL=F`…）標記 `is_proxy=True`。
- **代理永遠不覆蓋已存的 FRED 序列**（單位或定義不同，例如 DXY ≠ Fed 廣義美元指數），此時保留舊資料並記 `degraded`。
- 每列有 `available_date` = `obs_date` + 發布延遲（營業日）。H.15 殖利率、VIXCLS、ICE OAS 取 1 日；
  每週發布的廣義美元（H.10）與 EIA WTI 現貨保守取 7 日。M2 的特徵必須用 `available_date` 對齊，避免 look-ahead。
- 已知：FRED 上 ICE BofA 利差（`BAMLH0A0HYM2`、`BAMLC0A0CM`）因授權只提供最近約 3 年，
  5 年回測的前段沒有利差資料；M2 需處理缺值（或以 HYG/IEF 價格關係作代理），並在文件中揭露。

### 3. 國際局勢代理：GDELT DOC 2.0 平均語調

- 兩個查詢（經濟、地緣政治關鍵字），每日平均語調；當天（UTC）未結束的資料不存；`available_date` = 次一營業日。
- DOC API 只涵蓋最近約 3 個月：歷史靠每日累積，**沒有 5 年 GDELT 歷史可供回測**。M2/M4 的 regime 模型必須能在沒有此訊號時運作，並在 UI 明講。
- 請求間隔 ≥ 6 秒；失敗只降級（`degraded` / `failed`），不影響價格與宏觀。

### 4. 儲存：每檔一個 Parquet + DuckDB view

- `data/prices/<TICKER>.parquet`、`data/macro/<series>.parquet`、`data/sentiment/<name>.parquet`；
  特殊字元以 `_XX` 編碼（`^VIX` → `_5EVIX`）。寫入採暫存檔 + `os.replace`，中途失敗不會留下半個檔。
- `ParquetStore.connect()` 開 in-memory DuckDB，對各資料夾建立 `read_parquet(... union_by_name)` view。
- 不使用常駐資料庫；`data/` 不進 git（M6 再決定 CI 中的快取方式）。

### 5. 增量更新與調整價

- 有快取時只抓「最後一筆 − 14 天」之後的資料，覆蓋重疊區間，以吸收供應商修正。
- 若重疊區間的 `close` 或 `adj_close` 與快取不一致（相對誤差 > 1e-4，代表新除息/分割改變了整段調整基準），
  該檔**重抓完整歷史並整段取代**；重抓失敗則保留舊快取（`degraded`），絕不把兩種調整基準拼接在一起。
- 「今天」的 K 棒在紐約時間 17:00 前視為未完成，不寫入（避免把盤中價當收盤價）；宏觀的 yfinance 代理序列（如 gold、^VIX）套用同一規則。

### 6. Universe：版本化的靜態種子清單

- `src/qrd/universe/seeds.csv`：566 檔（2026-10-06 移除兩個來源皆 404 的 HOLX、MMC、BK、CTRA）（大中型股 + 股票/債券/商品/貨幣/波動率 ETF/ETN + 槓桿/反向），
  欄位含資產類別、類別、槓桿倍數。靜態清單可重現、可審查，不依賴爬取維基百科等易壞來源。
- 流動性過濾（60 日平均成交額、最低價格、最少歷史）在 `qrd.universe.liquidity_filter`，只使用 `asof` 當日以前資料。
- **存活者偏誤**：清單是 2026-10 的現有標的，回測時會高估報酬（下市、被併購者不在其中）。此偏誤必須在 M4 報告與 UI 揭露；
  免費來源沒有歷史成分股資料，這是本專案的結構性限制。

### 7. 資料品質檢查：只標記、不修改

缺值、交易日缺漏（以 SPY 交易日為參考日曆）、重複日期、非正價格、OHLC 不一致、異常跳動（門檻依槓桿倍數放大）、
跳動後隔日反轉（兩段皆超過 ×1.5／÷1.5 才視為壞 tick → `error`；較小的 V 形反轉如 2020-03 OKE、TRGP 的 −28%／+33% 為真實行情，只標 `warn`）、連續零成交量、資料過期。有 `error` 的標的列為 unusable，下游（M2+）排除。
每次執行輸出 `data/quality/quality-<時間>.json` 與 `data/logs/ingest-<時間>.json`。

## 取捨與後續

- 依賴版本以上下限約束（pyproject）；仍未產生鎖檔。CI 與本機用相同範圍，M6 建每日排程時再評估 `uv lock` 或 `pip-compile`。
- `qrd ingest` 在價格覆蓋率 < 90%（可調）時以 exit code 2 結束，讓 M6 的排程能發出警示，但資料仍會寫入。

> 僅供研究與學習，不構成投資建議。

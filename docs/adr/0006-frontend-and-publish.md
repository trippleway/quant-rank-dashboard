# ADR 0006：前端與發布格式（publish JSON、技術選型、無假資料）

- 狀態：已採用
- 日期：2026-10-06
- 里程碑：M5

## 背景

PLAN.md §6 要求七個功能分區的 Dashboard，讀取 pipeline 產出的靜態 JSON、可部署到 GitHub Pages，
深／淺色、等寬數字、一致色彩語意、載入與錯誤狀態，且不得以假資料冒充真實資料。M5 驗收：七頁可用、
以真實 pipeline 輸出運作、Lighthouse 可用性與無主控台錯誤。

## 決定

### 1. 新增 `qrd publish`，前端只讀 `web/public/data/`

| 選項 | 問題 |
|---|---|
| 前端直接讀 `data/rankings/`、`data/backtest/` | 前端要自己算 sparkline、異動、宏觀時間序列、單一標的回測；邏輯分散在 TypeScript，難以測試 look-ahead |
| **publish 階段整理成前端專用 JSON（採用）** | 多一個步驟，但所有計算都在 Python、有測試；前端只做呈現 |

- 每個檔案都帶 `schema_version`（1.0）、`asof`、`generated_at`、`disclaimer`；前端只接受主版本 1。
- `rankings.json` 就是已儲存的 `latest.json` 再加顯示用欄位（sparkline、前一日名次、1 日報酬）；**publish 不重算今日排名**。
- `changes.json`：前一交易日的排名用同一個 `rank_asof`、只用該日特徵重算（不讀可能過期的舊檔）；
  測試證明它與獨立執行 `qrd rank --asof <前一日>` 的 Top 50 相同。
- 單一標的回測（PLAN §6 Asset Detail）= 最近 5 年買進持有，只用 `<= asof` 的價格；不足 12 個月不回測。
  明確標示「不是排名策略」。測試：竄改 asof 之後的價格結果不變。
- 歷史排名：月度點來自回測持股（回測榜），每日點來自每日榜；UI 註明兩者差異。
- 只為「今日 Top 50 + 今日掉出者 + SPY/AGG」發布詳情檔，控制在約 4 MB。
- 輸出先寫到 `<out>.staging` 再整個換上；若目標資料夾存在但不是已發布的站（沒有 `manifest.json`）就拒絕覆蓋。
- 資料健康：每檔最後一根 K 線是否 = asof，加上最近 5 次 ingest 與品質報告（ingest 可能只跑部分標的，不能只看最後一次）。

### 2. 技術選型

- Vite + React 19 + TypeScript（strict）+ Tailwind 4 + ECharts 6（按需引入）；`HashRouter` + 相對 `base`，
  任何 GitHub Pages 子路徑都能直接用。
- 頁面以 `React.lazy` 分割；ECharts chunk 約 650 KB（gzip 約 217 KB），只在有圖表的頁面載入。
- 色彩：採用經過 CVD 驗證的參考色盤，深淺色各自選定；同一個實體（策略、SPY…）在所有圖表固定同一色槽。
  漲跌與風險**不只靠顏色**：▲▼ 符號、⚠ 圖示與文字標籤；宏觀變化（例如利差上升）只標方向不著「好壞」色。
- 不使用雙 y 軸：美元／油價／黃金以期初 = 100 指數化放在同一軸。
- 每張圖表有 `role="img"` 與 aria-label，並附「資料表檢視」。
- 數字一律等寬字型 + tabular figures（PLAN §6）。

### 3. 不使用假資料

前端沒有任何內建示範資料；JSON 缺失或版本不符時顯示錯誤狀態並提示執行 `make rank backtest publish`。
單元測試的 fixture 放在 `web/src/test/fixtures.ts` 並標示 FIXTURE，不會出現在 build 中（只被測試引用）。
`manifest.demo` 固定為 `false`；site check 會檢查非 DEMO 輸出不出現「DEMO」字樣。

### 4. 驗證方式

- `make web-lint`（ESLint + `tsc`）、`make web-test`（Vitest + Testing Library）、`make web-build`。
- `make web-check`：以 headless Chrome（puppeteer-core，使用本機 Chrome）開啟 build 後的八個路由 × 深淺兩種主題，
  檢查標題出現、無錯誤狀態、無 console error／warning、無失敗請求、主題正確。
- Lighthouse（accessibility、best-practices）由人工／agent 用 `npx lighthouse@12` 執行，未納入 CI（需要 Chrome 與網路）。

## 被拒絕的選項

- 前端直接讀 Parquet（duckdb-wasm）：bundle 大、看不到 schema 版本、仍需把計算邏輯搬到前端。
- 每檔標的都發布詳情：約 560 × 70 KB ≈ 40 MB，對 GitHub Pages 與首次載入都不划算；需要時可再擴充。
- Recharts：ECharts 的 heatmap、radar、markArea、dataZoom 一次到位，按需引入後體積可接受。

## 後果

- 前端與 pipeline 之間以 schema 1.x 為契約；改欄位需要同步修改 `web/src/lib/types.ts` 與 `docs/data-dictionary.md`。
- CI 新增 `web` job（Node 24：lint、test、build）；site check 與 Lighthouse 留在本機（M6 可評估在 Actions 中跑 Chrome）。

> 僅供研究與學習，不構成投資建議。

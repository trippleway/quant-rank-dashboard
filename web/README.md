# web/ — Dashboard 前端

Vite + React + TypeScript + Tailwind + ECharts 的靜態網站（PLAN.md §6）。只讀 `qrd publish`
產出的版本化 JSON（`web/public/data/`，不提交）；**沒有內建示範資料**，資料缺失時顯示錯誤狀態。
格式與取捨見 [`docs/adr/0006-frontend-and-publish.md`](../docs/adr/0006-frontend-and-publish.md)，
欄位見 [`docs/data-dictionary.md`](../docs/data-dictionary.md)。

> 僅供研究與學習，不構成投資建議。

## 頁面（左側固定導覽）

| 路由 | 頁面 | 內容 |
|---|---|---|
| `#/` | Overview 總覽 | 今日 regime 與成分貢獻、風險儀表（VIX、HY/IG 利差、曲線）、Top 10、資料更新與健康狀態 |
| `#/rankings` | Rankings 排名 | Top 50 表格：類別／產業篩選、代號搜尋、欄位排序、可展開的分數分解、sparkline、風險標籤、約束與未入選說明 |
| `#/asset/:ticker` | Asset Detail | 價格與 50/200 日均線、因子雷達圖、歷史排名、單獨回測（買進持有 vs SPY）、主要風險 |
| `#/macro` | Macro & Risk | 殖利率曲線、10Y−2Y、公債殖利率、信用利差、VIX、美元／油價／黃金（指數化）、GDELT 語調、regime 時間軸、來源與覆蓋 |
| `#/backtest` | Backtest | 每月／每週切換：權益曲線 vs 基準（含隨機區間）、指標表、回撤、滾動 Sharpe、月報酬熱力圖、IC 與十分位、樣本內外、regime 表現、穩健性與 DSR、參數假設、偏誤 |
| `#/changes` | Changes | 今日 vs 前一交易日：新進、掉出、大幅升降（附原因） |
| `#/methodology` | Methodology & Data | 方法摘要、資料來源、已知限制與偏誤、抓取與品質紀錄、免責聲明 |

## 開發

在 repo 根目錄：

```bash
make rank backtest publish   # 產生 web/public/data/
make web-install             # npm ci（第一次）
make web-dev                 # http://localhost:5173
make web-lint web-test       # ESLint + tsc、Vitest
make web-build               # web/dist/（含 data/ 複本）
make web-check               # headless Chrome 檢查 8 個路由 × 深淺色，無 console 錯誤
```

`make` 會優先使用 repo 內 `.tools/node/bin` 的 Node（gitignored），否則使用 PATH 上的 `npm`。
`web-check` 需要本機 Chrome／Chromium（或設定 `CHROME_PATH`）。

## 設計規則

- 深／淺色主題（記在 localStorage，預設跟隨系統）；色彩 token 在 `src/index.css`。
- 數字使用等寬字型與 tabular figures（`.num`）。
- 漲跌、風險不只靠顏色：▲▼ 符號、⚠ 圖示、文字標籤；同一實體在所有圖表使用固定色槽。
- 每張圖有 aria-label 與「資料表檢視」；不使用雙 y 軸。
- 每個資料載入都有載入中與錯誤狀態。

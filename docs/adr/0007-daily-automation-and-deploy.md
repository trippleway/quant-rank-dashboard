# ADR 0007：每日自動化與部署（GitHub Actions、資料快取、失敗通知）

- 狀態：已採用
- 日期：2026-10-06
- 里程碑：M6

## 背景

PLAN.md §3 要求每個美股交易日收盤後由 GitHub Actions 觸發整條 pipeline、產出 JSON 後部署前端，
本機也要能一行指令重跑（`make daily`）。M6 驗收：每日排程成功跑完並部署；失敗時有清楚的 log 與
issue／通知。限制：`data/` 不進 git；不使用外部資料庫或常駐伺服器；不依賴付費服務。

## 決定

### 1. `qrd daily` 是唯一的編排入口（本機與 CI 相同）

`ingest → features → rank → backtest（到期才跑）→ publish`，每步計時並寫進
`data/logs/daily-<stamp>.json`；`--markdown` 另輸出摘要表（CI 放進 job summary 與失敗 issue）。

| 情況 | 行為 |
|---|---|
| 任一步驟丟出例外 | 記錄完整 traceback，後續步驟標 `skipped`，exit 1 |
| 價格覆蓋率 < 90%（`--min-coverage`） | 視為 ingest 失敗：寧可不發布，也不發布殘缺的榜單 |
| 單一來源失敗（GDELT 429、FRED 等） | 沿用 M1 的降級：ingest 仍成功，publish 的資料健康與 UI 揭露 |
| 回測失敗但已有舊回測 | 標 `degraded`、沿用舊結果並寫警告（manifest 的 `backtest_asof` 會顯示舊日期） |
| 回測失敗且沒有舊回測 | 失敗 |
| 排名日期與上次相同 | 警告（休市日或資料源未更新），仍照常發布 |
| 排名日期距執行日 > 5 個日曆天（`--max-stale-days`） | publish 照跑，但整體判為失敗 → 不部署、開 issue |

在 CI 中，`qrd daily` 失敗 → pipeline job 失敗 → 不部署，網站維持上一次成功的版本（Pages 的既有部署不受影響）。

### 2. 回測頻率：到期才跑（預設 ≥ 7 天）

完整回測約 3.5 分鐘（1000 次隨機基準 + 敏感度 + ablation）。`--backtest auto` 在沒有已存回測、
或已存回測的 asof 比今日排名舊 7 天以上時才重跑，約每週一次；不依賴星期幾，所以快取遺失或
某天失敗也會自動補跑。手動觸發可選 `always`／`never`。回測報告寫到 `data/backtest/report-<日>.md`
並放進 run artifact；CI **不** 改寫 repo 內的 `docs/backtest-report.md`（排程不 commit）。

### 3. 資料保存：Actions cache，不 commit 資料

| 選項 | 問題 |
|---|---|
| 把 `data/` commit 回 repo 或另一個分支 | 違反「不提交 data/」；repo 每日膨脹約百 MB 等級的二進位 |
| 外部儲存（S3、R2…） | 需要帳號與憑證 |
| **Actions cache（採用）** | 7 天未使用會被清掉、可能被驅逐；但遺失時只是冷啟動 |

每次成功執行後以 `qrd-data-v1-<run_id>-<attempt>` 存新 cache，下次以前綴還原最新一份。
`data/` 約 130 MB。冷啟動（空資料夾）實測：ingest 107 秒（5 年以上完整歷史）、features 7 秒、
rank 1.4 秒，加上回測約 3.5 分鐘，因此冷快取的代價只是多幾分鐘，結果相同（ingest 與特徵都是確定性的，
只有資料源本身的調整價修訂可能不同，M1 已偵測並全量重抓）。只有 `qrd daily` 成功時才存 cache，
避免把半途失敗的狀態留給下一次。

### 4. 排程時間與交易日

`cron: "30 22 * * 1-5"`（UTC）= 美東夏令 18:30／冬令 17:30，都在 16:00 收盤之後，Yahoo 日線通常已更新。
不在 workflow 裡維護交易所假日表：假日照跑，排名日期不變時只出警告（見 §1），成本是每年約 9 次多餘的
執行。GitHub 排程可能延遲數分鐘到數十分鐘，對日頻資料沒有影響。

### 5. 工作流程結構

- `daily.yml`：`pipeline` job（安裝 → 還原 cache → `qrd daily` → 存 cache → 上傳 log artifact →
  `make web-build` → `make web-check`（headless Chrome，八個路由 × 深淺色，console error 即失敗）→
  上傳 Pages artifact）→ `deploy` → `notify`。
- `deploy.yml`：reusable workflow（`workflow_call`），只做 `actions/deploy-pages`。網站資料只存在於
  同一次 run 的 artifact，因此部署必須在同一個 run 內被呼叫，不能獨立觸發。
- `ci.yml` 不變（push／PR 的 lint、test、build）。
- 權限最小化：workflow 預設 `contents: read`；只有 deploy 取得 `pages: write`、`id-token: write`，
  只有 notify 取得 `issues: write`。`FRED_API_KEY` 以 repository secret 傳入（選用）。

### 6. 失敗通知：單一追蹤 issue

`notify` job 永遠執行（`if: always()`），由 `.github/scripts/daily-issue.sh` 決定：

- pipeline 或 deploy 不是 `success`（含 `cancelled`／逾時）→ 若已有開啟中的「daily pipeline failing」
  issue 就留言，否則開新 issue。內容：run 連結（完整 log）、各 job 結果、`qrd daily` 摘要表；
  若 pipeline 成功但部署失敗，附上「啟用 Pages」的提示。
- 全部成功且有開啟中的 issue → 留言「已恢復」並關閉。

選擇 issue 而非 email／Slack：GitHub 預設會通知 repo 擁有者，不需要額外帳號或 secret；同一問題只有
一個 issue，不會每天洗版。GitHub 本身也會對失敗的排程 workflow 寄信給設定排程的人。

## 後果與限制

- 部署需要使用者在 repo 設定啟用 GitHub Pages（Source：GitHub Actions）。私有 repo 的 Pages
  需要付費方案；公開 repo 則網站與原始碼都公開。這是使用者的決定，見 HANDOFF.md。
- 公開 repo 若 60 天沒有 commit，GitHub 會自動停用排程 workflow（會寄信通知）。
- 私有 repo 會消耗 Actions 分鐘數：熱快取一次約 5–8 分鐘（含安裝與 build），每月約 22 次。
- `ubuntu-latest` 預裝 Chrome；若 runner 映像改變而找不到 Chrome，`web-check` 會以 exit 2 失敗並開 issue，
  不會靜默略過。
- Actions cache 不是備份：要保存歷史快照仍需另外的儲存方案（backlog）。

> 僅供研究與學習，不構成投資建議。

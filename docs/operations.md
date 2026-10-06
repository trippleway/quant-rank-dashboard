# 營運手冊：每日 pipeline 與部署

設計理由見 [ADR 0007](adr/0007-daily-automation-and-deploy.md)。

## 本機

```bash
make daily                                   # ingest → features → rank →（到期）backtest → publish
.venv/bin/qrd daily --backtest always        # 強制重跑回測；never = 不跑
.venv/bin/qrd daily --markdown summary.md    # 另寫一份 Markdown 摘要（附加到檔尾）
make web-build web-check                     # 用剛發布的資料 build 並以 headless Chrome 檢查
```

每次執行的摘要寫在 `data/logs/daily-<UTC 時間>.json`（每一步的狀態、秒數、細節、錯誤與警告）；
ingest 的來源明細在 `data/logs/ingest-*.json`，資料品質在 `data/quality/`。
exit code：0 = 成功；1 = 有步驟失敗或資料過期。

## GitHub Actions

| Workflow | 觸發 | 內容 |
|---|---|---|
| `ci.yml` | push main、PR | Python lint／test（3.11、3.12）、前端 lint／test／build |
| `daily.yml` | 週一至週五 22:30 UTC、手動（Actions → daily → Run workflow） | `qrd daily` → build → `web-check` → 部署 → 通知 |
| `deploy.yml` | 只被 `daily.yml` 呼叫 | `actions/deploy-pages` |

### 第一次啟用（需要 repo 擁有者）

1. Settings → Pages → Build and deployment → Source 選 **GitHub Actions**。
   私有 repo 需要 GitHub 付費方案才能使用 Pages；否則須改為公開 repo。
2. （選用）Settings → Secrets and variables → Actions → 新增 `FRED_API_KEY`。沒有也能跑（FRED CSV → yfinance 代理）。
3. Actions → daily → Run workflow（`backtest: always`）跑第一次，確認 deploy job 顯示網址。

### 失敗時

- run 的 Summary 頁有 `qrd daily` 的步驟表；`daily-logs` artifact 有 JSON log、品質報告與回測報告。
- 會開（或留言在）標題為 **daily pipeline failing** 的 issue，附 run 連結與摘要；下一次成功時自動留言並關閉。
- 網站維持上一次成功的部署，不會發布失敗當天的資料。
- 常見原因：

| 症狀 | 處理 |
|---|---|
| ingest 失敗：`price coverage … below 90%` | Yahoo 暫時故障或限流；通常隔天自動恢復，或手動重跑 |
| `資料過期：排名日期 … 已 N 天` | 價格源多日沒有新資料；檢查 ingest log 的來源狀態 |
| backtest `degraded` | 沿用舊回測，網站顯示舊的 `backtest_asof`；看 log 修正後以 `backtest: always` 重跑 |
| deploy 失敗 | Pages 未啟用或 Source 不是 GitHub Actions（見上方第一次啟用） |
| `Chrome not found` | runner 映像變動；在 workflow 加裝 Chrome 或設定 `CHROME_PATH` |
| 想從頭重抓資料 | Actions → Caches 刪除 `qrd-data-v1-*`，下次執行會冷啟動（約多 2 分鐘 + 回測） |

> 僅供研究與學習，不構成投資建議。

# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M0 專案骨架
- 當前輪次：1 / 3
- 狀態：`CHANGES_REQUESTED`
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：2026-10-06（Reviewer）— M0 第 1 輪審查完成，要求修正 lint 範圍問題

## Needs human（需要使用者處理）

目前沒有。（已解決：使用者補上 PAT `workflow` scope 並完成 `gh auth login`，push 成功、CI 已確認通過）

（格式：`- [ ] 問題 / 需要的東西 / 為什麼需要 / 建議的預設做法`）

## 里程碑進度

| # | 里程碑 | 狀態 | 通過日期 |
|---|---|---|---|
| M0 | 專案骨架 | READY_FOR_REVIEW | |
| M1 | 資料層 | NOT_STARTED | |
| M2 | 特徵與 regime | NOT_STARTED | |
| M3 | 排名引擎 | NOT_STARTED | |
| M4 | 回測引擎 | NOT_STARTED | |
| M5 | 前端 | NOT_STARTED | |
| M6 | 自動化與發布 | NOT_STARTED | |
| M7 | 收尾 | NOT_STARTED | |

## 本輪紀錄（Lead 填寫）

### 目標

M0 第 1 輪：建立專案骨架，對應 PLAN.md §7 M0 驗收標準「`make test` `make lint` 可跑；CI 綠燈；目錄與工具鏈就位」。

拆分：
1. Python 套件骨架（`pyproject.toml`、`src/qrd/` 各子套件、`cli.py`）
2. 工具鏈：`Makefile`（install / test / lint / format / daily）、ruff、mypy（strict）、pytest
3. 煙霧測試（所有子套件可 import、CLI 可執行）
4. CI：`.github/workflows/ci.yml`（Python 3.11 / 3.12）
5. 目錄：`docs/`（含 ADR）、`web/`、`data/.gitkeep`、`.env.example`

### 改動摘要

- `pyproject.toml`：hatchling、src layout、套件 `qrd`、`requires-python >=3.11`；dev 依賴 pytest / pytest-cov / ruff / mypy；ruff 與 `mypy --strict` 設定。M0 不引入執行期依賴（M1 再加）。
- `Makefile`：`install`（建立 `.venv`）、`test`、`lint`（ruff check + format --check + mypy）、`format`、`daily`、`clean`。
- `src/qrd/`：`ingest` `universe` `features` `scoring` `backtest` `publish` 六個子套件（目前只有 docstring）、`cli.py`（`qrd version`、`qrd daily`）。`qrd daily` 在 pipeline 實作前**刻意回傳 exit 1**，避免假裝成功。
- `tests/test_smoke.py`：子套件可 import、CLI version 帶免責聲明、daily 失敗訊息、未知指令非零結束。
- `.github/workflows/ci.yml`：push main / PR 觸發，Python 3.11 與 3.12 矩陣跑 `make install` → `make lint` → `make test`；`permissions: contents: read`、timeout 15 分。
- `docs/README.md`、`docs/adr/0001-python-toolchain.md`（為何用 venv+pip 而非 uv）、`web/README.md`（M5 佔位）、`.env.example`（`FRED_API_KEY`）、README 快速開始。
- Commits：`8b08d50` `ec29434` `a7e39fe` 及本次 docs commit。

### 驗證結果

- `make test`：✅ 9 passed（本機 Python 3.14.8 與 3.12.15 兩個 venv 都跑過）
- `make lint`：✅ ruff check「All checks passed!」、ruff format「15 files already formatted」、mypy strict「Success: no issues found in 10 source files」（3.14 與 3.12 皆通過）
- CI：✅ run `37491659726`（commit `f04942e`）通過——`python (3.11)` 24s ✓、`python (3.12)` 24s ✓。https://github.com/trippleway/quant-rank-dashboard/actions/runs/37491659726
  - 註記（非錯誤）：`actions/checkout@v4`、`actions/setup-python@v5` 目標 Node.js 20 已 deprecated（被強制跑在 Node 24）；`ubuntu-latest` 將於 2026-10-19 起遷移到 Ubuntu 26。已列入 Backlog。
- 其他驗證：無（M0 沒有資料或特徵邏輯）

### 已知問題與限制

- 沒有依賴鎖檔（見 ADR 0001），M1 加入主要依賴時再處理。
- PLAN 目錄結構中的 `daily.yml`、`deploy.yml` 屬於 M6，本輪只建 `ci.yml`。
- `web/` 只有佔位 README：開發機沒有 Node，前端工具鏈在 M5 建立。若 Reviewer 認為 M0「工具鏈就位」必須包含前端骨架，請標 blocking，我會在 CI 中用 Node 建立並驗證。

### 下一步

M1 資料層：yfinance / FRED（無 key 退回 ^TNX 等）/ GDELT adapter（timeout、重試、快取、降級）、≥300 檔 universe、Parquet + DuckDB 儲存與增量更新、資料品質檢查（缺值、異常跳動）與測試；資料來源選擇寫 ADR。

## Review（Reviewer 填寫）

結論：`CHANGES_REQUESTED`

- [blocking] 實際執行 `make lint` 失敗（非網路／沙盒問題）：Ruff 會掃描整個 repo，而工作目錄中未追蹤的 `scripts/orchestrate.py` 產生 50 項錯誤。M0 驗收要求 `make lint` 可跑，故目前無法簽核。請將 lint 範圍明確限制在受版本控制的專案來源／測試檔，或將該腳本納入符合設定的檢查範圍；修正後以乾淨且含此工作目錄的狀態重新執行 `make lint`。
- [non-blocking] `make test` 實測通過（9 passed）。提供的 CI 狀態顯示 HEAD `985265b` 的 CI 成功；已檢查本輪提交與差異，提交內容僅為 M0 骨架、文件與 CI，未發現憑證、資料檔或與既有 stock-analysis-dashboard 的連結。M0 尚無資料、特徵、回測或前端實作，因此相應審查項目不適用於本輪。

## Lead 回應（針對 Review 意見）

（逐點回應：已修 / 不修與理由）

## Decisions（重大決定索引，細節在 docs/adr/）

- ADR 0001：Python 工具鏈採 venv + pip + hatchling，Makefile 為唯一入口

## Backlog（non-blocking 與未來想法）

- 升級 CI actions 至支援 Node 24 的版本（`actions/checkout`、`actions/setup-python`），消除 deprecation 警告
- 留意 `ubuntu-latest` 2026-10-19 遷移到 Ubuntu 26；必要時固定 runner 版本

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

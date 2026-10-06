# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M0 專案骨架
- 當前輪次：1 / 3
- 狀態：`NEEDS_HUMAN`（M0 實作完成、本機驗證通過，但無法 push，見下方）
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：2026-10-06（Lead）— 本機 5 個 commits 尚未推送

## Needs human（需要使用者處理）

- [ ] **push 被 GitHub 拒絕** / 錯誤訊息：`refusing to allow a Personal Access Token to create or update workflow .github/workflows/ci.yml without workflow scope` / 目前本機 git 使用的 PAT 沒有 `workflow` scope，無法推送 `.github/workflows/`；M0 要求 CI 綠燈，M6 也需要 workflow 檔 / 建議：在 GitHub 重新產生含 `repo` + `workflow` scope 的 PAT（或 fine-grained token 開啟 Workflows: Read and write），更新本機憑證後執行 `git push origin main`（或告訴 Lead 重試）。本機 commits 已備妥，未 push
- [ ] 確認 CI 綠燈 / repo 為 private 且本機沒有 `gh`，Lead 無法讀取 GitHub Actions 結果 / M0 驗收需要「CI 綠燈」/ 請到 repo 的 Actions 頁確認最新一次 `ci` 是否通過；或安裝 `gh` 後執行 `! gh auth login`，之後 Lead 可自行檢查（Reviewer 若能存取 Actions 也可代為確認）

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
- CI：⚠️ 已 push，但 Lead 無法讀取 private repo 的 Actions 結果（見 Needs human）。本機未用 3.11 測試（開發機沒有 3.11），由 CI 矩陣涵蓋。
- 其他驗證：無（M0 沒有資料或特徵邏輯）

### 已知問題與限制

- **CI 綠燈尚未由 Lead 親自確認**，這是 M0 驗收條件之一，需 Reviewer 或使用者確認。
- 沒有依賴鎖檔（見 ADR 0001），M1 加入主要依賴時再處理。
- PLAN 目錄結構中的 `daily.yml`、`deploy.yml` 屬於 M6，本輪只建 `ci.yml`。
- `web/` 只有佔位 README：開發機沒有 Node，前端工具鏈在 M5 建立。若 Reviewer 認為 M0「工具鏈就位」必須包含前端骨架，請標 blocking，我會在 CI 中用 Node 建立並驗證。

### 下一步

M1 資料層：yfinance / FRED（無 key 退回 ^TNX 等）/ GDELT adapter（timeout、重試、快取、降級）、≥300 檔 universe、Parquet + DuckDB 儲存與增量更新、資料品質檢查（缺值、異常跳動）與測試；資料來源選擇寫 ADR。

## Review（Reviewer 填寫）

結論：`APPROVED` / `CHANGES_REQUESTED`

- [blocking] …
- [non-blocking] …
- [question] …

## Lead 回應（針對 Review 意見）

（逐點回應：已修 / 不修與理由）

## Decisions（重大決定索引，細節在 docs/adr/）

- ADR 0001：Python 工具鏈採 venv + pip + hatchling，Makefile 為唯一入口

## Backlog（non-blocking 與未來想法）

（列表）

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

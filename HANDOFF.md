# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M0 專案骨架
- 當前輪次：3 / 3
- 狀態：`APPROVED`
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：2026-10-06（Reviewer）— M0 第 3 輪審查通過

## Needs human（需要使用者處理）

目前沒有。（已解決：使用者補上 PAT `workflow` scope 並完成 `gh auth login`，push 成功、CI 已確認通過）

（格式：`- [ ] 問題 / 需要的東西 / 為什麼需要 / 建議的預設做法`）

## 里程碑進度

| # | 里程碑 | 狀態 | 通過日期 |
|---|---|---|---|
| M0 | 專案骨架 | APPROVED | 2026-10-06 |
| M1 | 資料層 | NOT_STARTED | |
| M2 | 特徵與 regime | NOT_STARTED | |
| M3 | 排名引擎 | NOT_STARTED | |
| M4 | 回測引擎 | NOT_STARTED | |
| M5 | 前端 | NOT_STARTED | |
| M6 | 自動化與發布 | NOT_STARTED | |
| M7 | 收尾 | NOT_STARTED | |

## 本輪紀錄（Lead 填寫）

### 目標

M0 第 3 輪：處理第 2 輪 Review 的 blocking（需要本輪修正 commit 的 CI 綠燈結果）。

### 改動摘要

- 無程式碼變更。第 2 輪的 lint 範圍修正（`4125dba`）已隨 `ef12224` 推送並跑完 CI，本輪只記錄 CI 結果。
- Commit：本次 docs commit。

### 驗證結果

- CI：✅ run `37507144210`（commit `ef12224`，含 `4125dba` 的 Makefile 修正）通過——`python (3.11)` 21s ✓、`python (3.12)` 28s ✓。https://github.com/trippleway/quant-rank-dashboard/actions/runs/37507144210
  - 另有 run `37506669187`（commit `e838fae`）失敗：那是 lint 修正**之前**的 commit，`make lint` 掃到 `scripts/orchestrate.py` 失敗，正是第 1 輪 blocking 的問題，`4125dba` 後已不再發生。
  - run `37507378663`（commit `fcfecce`，Reviewer auto-commit，僅改 HANDOFF.md）在本輪寫紀錄時仍為 queued；與 `ef12224` 相比沒有程式碼差異。
  - 註記（非錯誤）：Node.js 20 deprecation 與 `ubuntu-latest` → Ubuntu 26 遷移警告，已在 Backlog。
- `make test`：✅ 9 passed（本機，HEAD `fcfecce`）
- `make lint`：✅ ruff check `src tests`「All checks passed!」、ruff format「10 files already formatted」、mypy strict「Success: no issues found in 10 source files」

### 已知問題與限制

- 同前：沒有依賴鎖檔（M1 處理）、`web/` 僅佔位（M5）、新增 Python 目錄需加進 `LINT_PATHS`。

### 下一步

這是 M0 的第 3 輪（最後一輪）。Reviewer 簽核後進入 M1 資料層；若仍有 blocking，依規則設為 `NEEDS_HUMAN`。

## Review（Reviewer 填寫）

結論：`APPROVED`

- [non-blocking] 已實際執行 `make test`：9 passed；`make lint`：ruff check、ruff format --check、strict mypy 均通過（10 source files）。測試涵蓋套件匯入、CLI 版本與免責聲明、未實作的 daily 指令明確失敗、未知指令非零結束；以 M0 骨架範圍而言足以驗證工具鏈，且結果未受網路或沙盒限制。
- [non-blocking] 已檢查 `git log` 與差異：本輪 `a38c052` 相對 `fcfecce` 僅修改 `HANDOFF.md`；從上一個已通過 CI 的基線至目前，產品程式碼唯一變更為 `4125dba` 將 ruff 範圍收斂至與 pyproject 一致的 `src tests`。未發現憑證、追蹤的資料檔、空白錯誤或與既有 stock-analysis-dashboard 的連結；`.env` 與 `data/` 的忽略規則也存在。
- [non-blocking] M0 所需 CI 已有含 `4125dba` 的 `ef12224` run `37507144210` 成功（Python 3.11、3.12）。最新 `a38c052` 的 CI 目前 queued，但此提交只有交接文件，未改動受 CI 驗證的程式碼或設定，故不構成簽核阻礙。
- [non-blocking] M0 尚未實作資料、特徵、排名、回測或 Dashboard；look-ahead、回測成本／基準／樣本外、外部資料降級與前端狀態等審查項目留待對應里程碑。CLI 與專案文件均保留「僅供研究與學習，不構成投資建議」的免責聲明。

## Lead 回應（針對 Review 意見）

針對第 2 輪 Review：

1. [blocking] 需要本輪修正（`4125dba`）的 CI 綠燈結果 → **已處理**。`ef12224`（包含 `4125dba`）的 CI run `37507144210` 已完成且成功（3.11、3.12 皆 ✓），結果記錄於上方「驗證結果」。之後的 `fcfecce` 只改 HANDOFF.md，沒有程式碼差異。
2. [non-blocking] 本機 `make test` / `make lint` 通過、`LINT_PATHS` 與 pyproject 一致 → 知悉，無需動作。本輪重跑仍通過。
3. [non-blocking] diff 無憑證、資料檔或對既有 repo 的連結 → 知悉，無需動作。
4. [non-blocking] 免責聲明 → 知悉；所有輸出（含 CLI）維持「僅供研究與學習，不構成投資建議」。

## Decisions（重大決定索引，細節在 docs/adr/）

- ADR 0001：Python 工具鏈採 venv + pip + hatchling，Makefile 為唯一入口

## Backlog（non-blocking 與未來想法）

- 若 `scripts/` 要納入 lint，需由維護編排流程的人決定（目前刻意排除）
- 升級 CI actions 至支援 Node 24 的版本（`actions/checkout`、`actions/setup-python`），消除 deprecation 警告
- 留意 `ubuntu-latest` 2026-10-19 遷移到 Ubuntu 26；必要時固定 runner 版本

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

### M0 第 2 輪 — Lead 紀錄

#### 目標

M0 第 2 輪：處理第 1 輪 Review 的 blocking（`make lint` 掃到 `scripts/orchestrate.py` 而失敗）。

#### 改動摘要

- `Makefile`：新增 `LINT_PATHS := src tests`，`lint` 與 `format` 的 ruff 指令改為只掃 `$(LINT_PATHS)`，不再用 `.` 掃整個 repo。mypy 原本就只檢查 `src`、`tests`（`pyproject.toml` 的 `files`），不需改。
- 不修改 `scripts/orchestrate.py`：它是外部自動化流程（Lead/Reviewer 輪替）的工具，由 `e838fae` auto-commit 進 repo，不屬於產品程式碼，也不是 Lead 實作的範圍。
- Commit：`4125dba`（fix）及本次 docs commit。

#### 驗證結果

- `make lint`：✅ ruff check `src tests`「All checks passed!」、ruff format「10 files already formatted」、mypy strict「Success: no issues found in 10 source files」。於含 `scripts/orchestrate.py` 的工作目錄執行（修正前同一指令重現 50 項錯誤）。
- `make test`：✅ 9 passed
- CI：本輪未 push（由外部流程推送），待推送後確認。

#### 已知問題與限制

- 同第 1 輪：沒有依賴鎖檔（M1 處理）、`web/` 僅佔位（M5）。
- 新增的 Python 程式碼目錄（若未來有）需要加進 `LINT_PATHS`，否則不會被 lint。

#### 下一步

Reviewer 簽核 M0 後進入 M1 資料層。

### M0 第 2 輪 — Review

結論：`CHANGES_REQUESTED`

- [blocking] M0 驗收要求 CI 綠燈。提供的最新 CI 中，對目前 HEAD `ef12224` 的 `ci` 仍為 `queued`，尚無本輪（包含 `4125dba` 的 Makefile lint 範圍修正）成功結果可供簽核；先前 `985265b` 的成功結果不能驗證這項新修改。請待本輪 CI 完成且成功後，於下一輪記錄結果並設為 `READY_FOR_REVIEW`。
- [non-blocking] 實際執行 `make test`：9 passed；`make lint`：ruff check、ruff format --check、mypy 均通過（10 source files）。`LINT_PATHS := src tests` 與 pyproject.toml 的 ruff/mypy 專案範圍一致，已修正第 1 輪 blocking。此驗證未受網路或沙盒限制。
- [non-blocking] 已檢查 `git log`、本輪自 `e838fae` 至 `ef12224` 的 diff 與工作目錄差異；產品程式碼變更僅將 ruff lint/format 範圍限定為 `src tests`，其餘為 HANDOFF 紀錄。未發現憑證、資料檔或與既有 stock-analysis-dashboard 的連結。M0 尚未實作資料、特徵、排名、回測或前端，對應的正確性／資料洩漏／回測／UI 審查項目本輪不適用。
- [non-blocking] 本審查與專案輸出僅供研究與學習，不構成投資建議。

### M0 第 2 輪 — Lead 回應（針對第 1 輪 Review）

針對第 1 輪 Review：

1. [blocking] `make lint` 掃到 `scripts/orchestrate.py` 失敗 → **已修**（`4125dba`）。採 Reviewer 建議的第一個選項：把 ruff 範圍明確限制為 `src tests`。理由：`scripts/orchestrate.py` 是外部編排工具，非本專案產品程式碼，Lead 不應改寫它；且 ruff/mypy 範圍與 `pyproject.toml` 的 `src = ["src", "tests"]`、mypy `files` 一致。已在含該腳本的工作目錄重跑 `make lint` 通過。
2. [non-blocking] `make test` 通過、提交內容無憑證／資料檔 → 知悉，無需動作。

### M0 第 1 輪 — Lead 紀錄

#### 目標

M0 第 1 輪：建立專案骨架，對應 PLAN.md §7 M0 驗收標準「`make test` `make lint` 可跑；CI 綠燈；目錄與工具鏈就位」。

拆分：
1. Python 套件骨架（`pyproject.toml`、`src/qrd/` 各子套件、`cli.py`）
2. 工具鏈：`Makefile`（install / test / lint / format / daily）、ruff、mypy（strict）、pytest
3. 煙霧測試（所有子套件可 import、CLI 可執行）
4. CI：`.github/workflows/ci.yml`（Python 3.11 / 3.12）
5. 目錄：`docs/`（含 ADR）、`web/`、`data/.gitkeep`、`.env.example`

#### 改動摘要

- `pyproject.toml`：hatchling、src layout、套件 `qrd`、`requires-python >=3.11`；dev 依賴 pytest / pytest-cov / ruff / mypy；ruff 與 `mypy --strict` 設定。M0 不引入執行期依賴（M1 再加）。
- `Makefile`：`install`（建立 `.venv`）、`test`、`lint`（ruff check + format --check + mypy）、`format`、`daily`、`clean`。
- `src/qrd/`：`ingest` `universe` `features` `scoring` `backtest` `publish` 六個子套件（目前只有 docstring）、`cli.py`（`qrd version`、`qrd daily`）。`qrd daily` 在 pipeline 實作前**刻意回傳 exit 1**，避免假裝成功。
- `tests/test_smoke.py`：子套件可 import、CLI version 帶免責聲明、daily 失敗訊息、未知指令非零結束。
- `.github/workflows/ci.yml`：push main / PR 觸發，Python 3.11 與 3.12 矩陣跑 `make install` → `make lint` → `make test`；`permissions: contents: read`、timeout 15 分。
- `docs/README.md`、`docs/adr/0001-python-toolchain.md`（為何用 venv+pip 而非 uv）、`web/README.md`（M5 佔位）、`.env.example`（`FRED_API_KEY`）、README 快速開始。
- Commits：`8b08d50` `ec29434` `a7e39fe` 及本次 docs commit。

#### 驗證結果

- `make test`：✅ 9 passed（本機 Python 3.14.8 與 3.12.15 兩個 venv 都跑過）
- `make lint`：✅ ruff check「All checks passed!」、ruff format「15 files already formatted」、mypy strict「Success: no issues found in 10 source files」（3.14 與 3.12 皆通過）
- CI：✅ run `37491659726`（commit `f04942e`）通過——`python (3.11)` 24s ✓、`python (3.12)` 24s ✓。https://github.com/trippleway/quant-rank-dashboard/actions/runs/37491659726
  - 註記（非錯誤）：`actions/checkout@v4`、`actions/setup-python@v5` 目標 Node.js 20 已 deprecated（被強制跑在 Node 24）；`ubuntu-latest` 將於 2026-10-19 起遷移到 Ubuntu 26。已列入 Backlog。
- 其他驗證：無（M0 沒有資料或特徵邏輯）

#### 已知問題與限制

- 沒有依賴鎖檔（見 ADR 0001），M1 加入主要依賴時再處理。
- PLAN 目錄結構中的 `daily.yml`、`deploy.yml` 屬於 M6，本輪只建 `ci.yml`。
- `web/` 只有佔位 README：開發機沒有 Node，前端工具鏈在 M5 建立。若 Reviewer 認為 M0「工具鏈就位」必須包含前端骨架，請標 blocking，我會在 CI 中用 Node 建立並驗證。

#### 下一步

M1 資料層：yfinance / FRED（無 key 退回 ^TNX 等）/ GDELT adapter（timeout、重試、快取、降級）、≥300 檔 universe、Parquet + DuckDB 儲存與增量更新、資料品質檢查（缺值、異常跳動）與測試；資料來源選擇寫 ADR。

### M0 第 1 輪 — Review

結論：`CHANGES_REQUESTED`

- [blocking] 實際執行 `make lint` 失敗（非網路／沙盒問題）：Ruff 會掃描整個 repo，而工作目錄中未追蹤的 `scripts/orchestrate.py` 產生 50 項錯誤。M0 驗收要求 `make lint` 可跑，故目前無法簽核。請將 lint 範圍明確限制在受版本控制的專案來源／測試檔，或將該腳本納入符合設定的檢查範圍；修正後以乾淨且含此工作目錄的狀態重新執行 `make lint`。
- [non-blocking] `make test` 實測通過（9 passed）。提供的 CI 狀態顯示 HEAD `985265b` 的 CI 成功；已檢查本輪提交與差異，提交內容僅為 M0 骨架、文件與 CI，未發現憑證、資料檔或與既有 stock-analysis-dashboard 的連結。M0 尚無資料、特徵、回測或前端實作，因此相應審查項目不適用於本輪。

# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M0 專案骨架
- 當前輪次：0 / 3
- 狀態：`NOT_STARTED`
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：（agent 填寫日期時間）

## Needs human（需要使用者處理）

目前沒有。

（格式：`- [ ] 問題 / 需要的東西 / 為什麼需要 / 建議的預設做法`）

## 里程碑進度

| # | 里程碑 | 狀態 | 通過日期 |
|---|---|---|---|
| M0 | 專案骨架 | NOT_STARTED | |
| M1 | 資料層 | NOT_STARTED | |
| M2 | 特徵與 regime | NOT_STARTED | |
| M3 | 排名引擎 | NOT_STARTED | |
| M4 | 回測引擎 | NOT_STARTED | |
| M5 | 前端 | NOT_STARTED | |
| M6 | 自動化與發布 | NOT_STARTED | |
| M7 | 收尾 | NOT_STARTED | |

## 本輪紀錄（Lead 填寫）

### 目標

（這一輪要達成什麼，對應 PLAN.md 哪個驗收標準）

### 改動摘要

（做了什麼、動了哪些主要檔案）

### 驗證結果

- `make test`：
- `make lint`：
- 其他驗證（例如 look-ahead 測試、資料抽查）：

### 已知問題與限制

（誠實列出）

### 下一步

（Reviewer 通過後要做什麼）

## Review（Reviewer 填寫）

結論：`APPROVED` / `CHANGES_REQUESTED`

- [blocking] …
- [non-blocking] …
- [question] …

## Lead 回應（針對 Review 意見）

（逐點回應：已修 / 不修與理由）

## Decisions（重大決定索引，細節在 docs/adr/）

（列表）

## Backlog（non-blocking 與未來想法）

（列表）

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

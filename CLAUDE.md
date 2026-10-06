# CLAUDE.md — Lead agent 規則

你是這個專案的 **Lead（總指揮）**。完整規格在 `PLAN.md`，必須先讀它；協作格式在 `HANDOFF.md`；與 Reviewer 共用的規則在 `AGENTS.md`。

## 工作方式

1. 開工前先讀 `PLAN.md`、`AGENTS.md`、`HANDOFF.md`（含最新進度與 Reviewer 的意見）。
2. 一次只做一個里程碑（M0 → M7 依序）。開始前在 HANDOFF.md 寫下本輪目標與拆分。
3. 實作完成後，跑 `make test` 和 `make lint`，結果寫進 HANDOFF.md，然後請 Reviewer 審查。
4. Reviewer 提出的 **blocking** 意見必須處理或寫出有理由的反駁；**non-blocking** 可排進 backlog。
5. 里程碑驗收標準（PLAN.md 第 7 節）全部滿足，才能標記完成並進入下一個。

## 與 Reviewer 討論的規則

- 每個里程碑最多 **3 輪**「實作 → 審查 → 修正」。第 3 輪仍有 blocking 問題，就把分歧點寫進 HANDOFF.md 的 `Blocked / Needs human`，**停止並等待使用者**，不要硬做或硬吵。
- 設計上的重大決定（資料源、儲存、因子取捨、回測假設）寫成 `docs/adr/NNNN-title.md`，說明選項、取捨、結論。
- 雙方意見衝突時，優先順序：正確性與無 look-ahead > 可重現 > 可解釋 > UI 美觀 > 效能。

## 工程準則

- 先寫測試再寫關鍵邏輯（尤其是特徵、回測、排名約束）。
- 回測與特徵相關的程式碼，必須有測試證明沒有 look-ahead bias。
- 所有外部資料呼叫都要有 timeout、重試、快取與降級路徑；不許讓單一來源失敗讓整條 pipeline 崩潰。
- 不要假造資料。測試與前端示範可以用 fixture，但必須標示為 DEMO / fixture，不得出現在正式輸出裡。
- 不要吹噓回測結果。報告一律附偏誤與限制說明。
- 小步提交（conventional commits：`feat:` `fix:` `test:` `docs:` `chore:`），每個提交只做一件事。
- 不要提交 `data/`、`.env`、API key、任何憑證。需要的環境變數寫進 `.env.example`。

## 停止條件（遇到就停下並寫進 HANDOFF.md）

- 需要使用者提供的東西：API key、GitHub Pages 設定、付費資料源決定
- 同一個問題嘗試 3 次仍失敗
- 需要修改 `PLAN.md` 的範圍或驗收標準（先提出，不要自己改）
- 任何會影響使用者既有 repo 或帳號的操作（本專案與既有 stock-analysis-dashboard 完全分離，不得參照或修改它）
- 破壞性操作（刪除大量檔案、force push、改寫歷史）

## 每次收工前

更新 `HANDOFF.md`：做了什麼、驗證結果、下一步、卡住的點。格式見該檔案。

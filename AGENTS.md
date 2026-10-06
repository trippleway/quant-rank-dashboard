# AGENTS.md — 所有 agent 的共用規則

適用於本 repo 內的每一個 agent（Lead 與 Reviewer）。Lead 另外請讀 `CLAUDE.md`。
規格來源是 `PLAN.md`；進度與交接只寫在 `HANDOFF.md`。

## 角色

| 角色 | 責任 | 不可以做 |
|---|---|---|
| **Lead** | 規劃、實作、跑測試、更新 HANDOFF.md、處理審查意見 | 自己宣布里程碑通過而沒有 Reviewer 簽核 |
| **Reviewer** | 審查程式碼、測試、回測方法、UI；用獨立視角找問題；簽核里程碑 | 直接大改 Lead 的實作（只提意見，小型 typo 修正除外） |

## Reviewer 的審查清單

1. **正確性**：特徵、排名、回測邏輯是否正確；有沒有 look-ahead、資料洩漏、對齊錯誤（交易日曆、調整價、時區）
2. **回測嚴謹度**：成本、換手、基準、樣本外切分、偏誤揭露是否符合 PLAN.md 第 5 節；有沒有過度擬合的跡象
3. **測試**：關鍵邏輯是否有測試；測試是否真的會失敗（不是永遠通過）
4. **韌性**：外部資料失敗、缺值、極端值時的行為
5. **前端**：功能分區是否符合 PLAN.md 第 6 節；有無假資料冒充真實資料；錯誤與載入狀態
6. **文件**：方法論與限制是否誠實、是否能讓第三者重現
7. **安全**：沒有提交憑證；依賴來源合理

審查意見一律標記嚴重度：

- `[blocking]` 不修不能過關
- `[non-blocking]` 建議改，可進 backlog
- `[question]` 需要 Lead 解釋

## 討論流程（自動化）

1. Lead 在 HANDOFF.md 開新一輪：寫目標、改動摘要、驗證結果，狀態設為 `READY_FOR_REVIEW`。
2. Reviewer 讀取後在同一份 HANDOFF.md 的 `Review` 區塊寫意見，狀態設為 `CHANGES_REQUESTED` 或 `APPROVED`。
3. 若是 `CHANGES_REQUESTED`，Lead 修正後回到步驟 1（輪數 +1）。
4. 每個里程碑最多 3 輪。超過就設為 `NEEDS_HUMAN`，停止。
5. `APPROVED` 後 Lead 才能進下一個里程碑。

## 共通規範

- 語言：程式碼、識別字、commit 用英文；文件（docs、HANDOFF.md、討論）用繁體中文，技術名詞可保留英文。
- 不修改 `PLAN.md` 的範圍與驗收標準，要改就在 HANDOFF.md 提案並等使用者決定。
- 本專案與使用者既有的 stock-analysis-dashboard 完全分離，不得連結、複製或修改它。
- 不提交 secrets、`data/`、`.env`。不 force push。不改寫已推送的歷史。
- 所有輸出都要帶免責聲明：僅供研究與學習，不構成投資建議。

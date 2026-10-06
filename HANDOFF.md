# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M2 特徵與 regime
- 當前輪次：1 / 3
- 狀態：`READY_FOR_REVIEW`
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：2026-10-06（Lead）— M2 第 1 輪實作完成，待審查

## Needs human（需要使用者處理）

目前沒有。（已解決：使用者補上 PAT `workflow` scope 並完成 `gh auth login`，push 成功、CI 已確認通過）

（格式：`- [ ] 問題 / 需要的東西 / 為什麼需要 / 建議的預設做法`）

## 里程碑進度

| # | 里程碑 | 狀態 | 通過日期 |
|---|---|---|---|
| M0 | 專案骨架 | APPROVED | 2026-10-06 |
| M1 | 資料層 | APPROVED | 2026-10-06 |
| M2 | 特徵與 regime | READY_FOR_REVIEW | |
| M3 | 排名引擎 | NOT_STARTED | |
| M4 | 回測引擎 | NOT_STARTED | |
| M5 | 前端 | NOT_STARTED | |
| M6 | 自動化與發布 | NOT_STARTED | |
| M7 | 收尾 | NOT_STARTED | |

## 本輪紀錄（Lead 填寫）

### 目標

M2 第 1 輪：特徵與 regime。對應 PLAN.md §7 M2 驗收標準「因子與 regime 有單元測試；用測試證明沒有 look-ahead（把未來資料截掉結果不變）」。

拆分：
1. 價格因子（每標的每日）：動能 12-1／6m／3m、趨勢（vs 200 日均線）、已實現波動、下行偏差、最大回撤、beta、流動性與成本代理
2. 資產類別專屬：債券的經驗利率存續期（對 10y 殖利率變動的回歸，宏觀以 `available_date` 對齊）、過去 12 個月配息率代理
3. 宏觀 point-in-time 面板（每個交易日只看 `available_date <= t` 的觀測）
4. Regime：VIX、信用（OAS 與 HYG/IEF 代理）、曲線、美元、油價、黃金、SPY 趨勢、GDELT 語調 → risk-on / neutral / risk-off
5. Look-ahead 測試：截斷未來資料、竄改未來資料，過去結果必須完全不變
6. CLI `qrd features`、ADR 0003（因子與 regime 設計取捨）、資料字典更新

### 改動摘要

- **價格因子**（`src/qrd/features/factors.py`，`0047c4f`）：每標的每日 `mom_12_1`、`mom_6m`、`mom_3m`、`trend_200`、`vol_63`、`downside_63`、`max_dd_252`（只計視窗內高點，精確計算）、`beta_252`（vs SPY，以標的自身交易日對齊）、`adv_usd_60`、`amihud_60`、`trailing_yield_252`（配息率代理）、`history_sessions`／`short_history`。全部 trailing 視窗；歷史不足為 NaN 而非 0。
- **債券專屬**：`compute_rate_duration` 經驗存續期 = −100·cov(r, Δy10)/var(Δy10)；由觀測日 d 以前的配對估出的值要到 `available_date(d)` 才可用（有測試：5 日延遲的值等於 1 日延遲版本晚 4 個交易日的值）。
- **宏觀 panel**（`features/macro.py`，`4fd3600`）：以 `available_date` 做 `merge_asof`；晚到的舊觀測不覆蓋新值；> 21 日曆天未更新視為缺值；欄位固定為全部已知序列（schema 不隨歷史長度改變）。
- **Regime**（`features/regime.py`）：10 個成分（VIX、HY OAS、HYG/IEF 信用代理、SPY 趨勢、曲線、美元、油、黃金、GDELT ×2），各以 trailing 756 日分位數轉成 [−1, 1] 壓力分數，可用成分加權平均 + span 5 因果 EWM；±0.25 為門檻；可用成分 < 3 為 `unknown`。輸出 `contrib_*`（加總 = 原始壓力）供 UI 解釋。
- **Pipeline 與 CLI**（`features/build.py`、`cli.py`，`54a9611`）：`build_features`（純函式）、`point_in_time`（價格 `date <= t`、宏觀 `available_date <= t`）、`qrd features [--data-dir] [--asof]` / `make features`，寫入 `data/features/{factors,macro_panel,regime}.parquet`；排除最新品質報告中 `error` 的標的；無資料時 exit 1 並提示先 ingest。
- **Look-ahead 測試**（`tests/test_lookahead.py`，`803947f`）：700 日 FIXTURE（含晚上市、缺一日、週頻序列、7 日延遲、HY OAS 晚開始），4 個切點截斷後重算，t 以前的 factors／panel／regime **完全相等**；2 個切點把未來價格亂乘、量歸零、t 後才公布的宏觀值改為 1e6，結果不變；2 個金絲雀（以 `obs_date` join、置中視窗）證明檢查器會失敗；另有一個測試確保晚切點各因子與 9 個 regime 成分都真的有值（非空測試）。
- **文件**（`8173ac3`）：`docs/adr/0003-features-and-regime.md`（對齊規則、因子清單、不做財報型品質/價值與期限結構的理由、regime 設計與取捨、實測）、`docs/data-dictionary.md` 新增特徵三個檔案的欄位說明；README／Makefile 加 `make features`。

### 驗證結果

- `make test`：✅ 112 passed、1 skipped（skipped 為需 `QRD_RUN_NETWORK=1` 的網路測試）。本輪新增 30 個測試（factors 9、regime 9、look-ahead 9、CLI 3），全部離線、使用標示為 FIXTURE 的合成資料。
- `make lint`：✅ ruff check「All checks passed!」、ruff format「36 files already formatted」、mypy strict「Success: no issues found in 36 source files」
- **真實資料**（本機 M1 快取，`qrd features`，約 8.6 秒）：
  - asof 2026-10-05；563 檔有當日因子（AVB、EA、EQR 最後 K 棒在 2026-08，即 M1 的 `stale` warn），排除 0 檔；12 個數值因子當日覆蓋率 100%。
  - 合理性：經驗存續期 SHY 1.7、IEF 7.0、TLT 12.7、EDV 18.3、TMF 37.2、TBT −25.6；beta SSO 1.99、SQQQ −4.26（−3 × QQQ，而 QQQ 對 SPY 的 beta 約 1.3–1.4）；配息率 HYG 6.1%、TLT 4.6%。
  - Regime：2026-10-05 為 `neutral`（stress −0.047，8 個成分；GDELT 無資料、ig_oas 未使用）。2022 年 153 日 `risk_off`、0 日 `risk_on`；2025-04 關稅衝擊整月 `risk_off`（峰值 0.545）；2024 年 `risk_on` 121 日。
- CI：本輪未 push（由外部流程推送），待推送後確認。

### 已知問題與限制

- **沒有財報型品質/價值因子**：免費來源沒有 point-in-time 財報，用現在的快照回測就是 look-ahead；改以缺值降權（ADR 0003 §3）。個股價值面只有 `trailing_yield_252` 代理。這符合 PLAN §4「資料不足時降權而非當作 0」，但若 Reviewer 認為需要更多，請提出。
- **商品／貨幣期限結構**：沒有免費期貨曲線，未提供。
- **Regime 暖機**：價格從 2019-10 開始、分位數需 252 筆 → 約 2020-10 以前為 `unknown`（含 2020-03）。5 年回測（約 2021-10 起）不受影響。
- Regime 門檻與權重是主觀設定（規則式、無擬合）；每年切換 10–17 次，M4 需做敏感度掃描並評估換手，必要時加遲滯。
- FRED 只存最新版本（非 vintage），修訂風險在 M4 偏誤揭露。
- `stale` 標的（AVB、EA、EQR）仍會輸出到其最後一日的因子；M3 選股須以「當日有因子」為條件排除。
- 品質排除依「最新一份」品質報告；若最近一次 ingest 只跑部分標的（`--tickers`），報告也只涵蓋那些標的。M6 每日排程跑全量時不影響；必要時 M3 改為在 features 階段重跑品質檢查。
- `rate_duration` 對所有標的都計算，但只對債券 ETF 有直接解釋力（股票的值是利率敏感度，不是存續期）。

### 下一步

Reviewer 審查 M2。通過後進入 M3（排名引擎：橫斷面 winsorize + z-score（按資產類別）、regime 權重、風險與集中度懲罰、Top 50 約束、分數分解、`docs/methodology.md`）。

## Review（Reviewer 填寫）

（M2 第 1 輪，尚未審查）

## Lead 回應（針對 Review 意見）

（M2 第 1 輪，尚無）

## Decisions（重大決定索引，細節在 docs/adr/）

- ADR 0001：Python 工具鏈採 venv + pip + hatchling，Makefile 為唯一入口
- ADR 0002：資料來源（yfinance → Yahoo chart → 快取；FRED API → FRED CSV → yfinance 代理；GDELT DOC）與儲存（Parquet + DuckDB view、增量 + 調整基準偵測）
- ADR 0003：因子與 regime（`available_date` 對齊、trailing 分位數、規則式 regime、不做財報型品質/價值）

## Backlog（non-blocking 與未來想法）

- 若 `scripts/` 要納入 lint，需由維護編排流程的人決定（目前刻意排除）
- 升級 CI actions 至支援 Node 24 的版本（`actions/checkout`、`actions/setup-python`），消除 deprecation 警告
- 留意 `ubuntu-latest` 2026-10-19 遷移到 Ubuntu 26；必要時固定 runner 版本
- GDELT 若長期 429：評估 GDELT ngrams 資料集或公開 RSS 標題情緒作為替代
- 依賴鎖檔（`uv lock` / `pip-compile`），M6 評估
- Regime 遲滯（hysteresis）或最短持續天數，視 M4 換手結果決定
- 若日後有 point-in-time 財報源（付費），以新 adapter 加入品質/價值因子

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

### M1 第 1 輪 — Lead 紀錄

#### 目標

M1 第 1 輪：資料層。對應 PLAN.md §7 M1 驗收標準「至少 300 檔 universe 可抓取、快取、增量更新；來源失敗會降級並記錄；有資料品質檢查（缺值、異常跳動）與測試」。

拆分：
1. Universe 種子清單（≥300 檔，含資產類別／槓桿標記）與流動性過濾
2. 價格 adapter：yfinance（主）→ Yahoo chart HTTP（備援）→ 既有快取（降級）；timeout、重試
3. 宏觀 adapter：FRED API（有 key）→ FRED 公開 CSV → yfinance 代理（^TNX 等）
4. GDELT 語調 adapter（失敗降級為空並記錄）
5. Parquet 儲存 + DuckDB view、增量更新（含調整價改變偵測）
6. 資料品質檢查（缺值、異常跳動、OHLC 一致性、重複日期、過期資料）
7. CLI `qrd ingest`、執行紀錄 JSON、ADR 0002（資料來源與儲存）、`docs/data-dictionary.md`

#### 改動摘要

主體實作在前一次 Lead 執行中完成，被外部流程以 `c76697d`（auto-commit）提交；本次執行做端到端實測，並修正實測發現的 3 個問題。

- **Universe**（`src/qrd/universe/`）：`seeds.csv` 566 檔（equity 412、equity_etf 91、bond_etf 31、commodity_etf 19、currency_etf 8、volatility_etp 5；槓桿/反向 39），含資產類別、類別、槓桿倍數、商品型態；載入時驗證欄位／重複／類別。`liquidity_filter`（60 日 ADV、最低價、最少歷史）只看 `asof` 以前的資料（有測試）。
- **價格 adapter**（`ingest/prices.py`）：yfinance 批次（主）→ Yahoo v8 chart HTTP（備援）→ 保留快取（`degraded`）。全部有 timeout、指數退避重試；adapter 的非預期例外也不會中斷整個 run。紐約時間 17:00 前，當日 K 棒不寫入。
- **宏觀 adapter**（`ingest/macro.py`）：13 條序列；FRED API（有 key）→ FRED 公開 CSV → yfinance 代理（`is_proxy`）。每列有 `available_date` = `obs_date` + 發布延遲，供 M2 防 look-ahead。代理資料不會覆蓋已存的 FRED 序列。
- **GDELT**（`ingest/gdelt.py`）：timelinetone 每日平均，`available_date` = 次一營業日；有限流間隔；失敗時降級，不中斷。
- **儲存**（`storage.py`）：每檔一個 Parquet，原子寫入；DuckDB in-memory view（`prices`／`macro`／`sentiment`）。
- **增量更新**（`ingest/pipeline.py`）：從快取最後一天往回重疊 14 天重抓；重疊區價格不一致（除息／分割改變調整基準）時重抓完整歷史並整段取代，絕不拼接。
- **資料品質**（`ingest/quality.py`）：缺值、交易日缺漏（以 SPY 日曆為參考）、重複日期、非正價格、OHLC 不一致、異常跳動（門檻依槓桿放大）、隔日反轉、連續零量、過期。只標記不修改；有 `error` 的標的為 unusable。
- **CLI**：`qrd ingest [--full --limit --tickers --no-macro --no-sentiment --min-coverage]`、`qrd universe`；每次執行寫 `data/logs/ingest-*.json`、`data/quality/quality-*.json`；覆蓋率 < 90% 時 exit 2。
- **文件**：`docs/adr/0002-data-sources-and-storage.md`、`docs/data-dictionary.md`、`.env.example`（`FRED_API_KEY` 選填）。
- **本次執行的修正**（實測發現）：
  - `db0e288` fix：OKE、TRGP 在 2020-03-18/19 的 −28%／+33% 是 COVID 崩盤的真實行情（OHLC 一致、量大），卻被判成壞 tick（error），導致整檔 unusable。現在兩段都超過 ×1.5／÷1.5 才算 `error`，較小的 V 形反轉只標 `warn`。已補回歸測試（含 ÷2 壞 tick 仍為 error）。
  - `52afc64` fix：宏觀代理（例：gold `GC=F`）在盤中執行時，會把今天的盤中價寫進序列（`available_date` = 今天）→ look-ahead 風險。現在套用和價格相同的 `session_cutoff`；先寫測試（盤中 vs 收盤後）。
  - `7769e35` chore：HOLX、MMC、BK、CTRA 在 yfinance 與 Yahoo chart 都回 404（代碼已下市或變更），從種子清單移除（570 → 566），並在 CSV 註記。沒有自行猜測替代代碼。

#### 驗證結果

- `make test`：✅ 82 passed、1 skipped（skipped 為網路測試，需 `QRD_RUN_NETWORK=1`）。測試全部離線，使用標示為 FIXTURE 的假資料源。
- `make lint`：✅ ruff check「All checks passed!」、ruff format「28 files already formatted」、mypy strict「Success: no issues found in 28 source files」
- **真實資料端到端**（本機，2026-10-06 約 14:15–14:21 EDT，無 `FRED_API_KEY`）：
  - 第 1 次 `qrd ingest`（已有快取，增量）：570 檔，覆蓋率 99.3%；4 檔失敗（上述 404，記錄為 `failed`，未中斷）；macro 13/13 ok（FRED CSV）；GDELT 2/2 `failed`（HTTP 429 限流 → 依設計降級並記錄）；2 檔 unusable（OKE、TRGP 誤判，已修）。耗時 2 分 25 秒。
  - 修正後第 2 次 `qrd ingest --no-sentiment`：566 檔，**覆蓋率 100%**，0 unusable，`refetched_full` 空；增量耗時 29 秒。品質報告：`abnormal_jump` warn 14、`stale` warn 3、`spike_reversal` warn 2。
  - DuckDB view：`prices` 566 檔、987,346 列、2019-10-07 至 2026-10-05（10-06 盤中未寫入，符合規則）；`macro` 13 條序列皆可查詢。
  - 修正 `52afc64` 後重跑：`gold` 最大 `obs_date` 由 2026-10-06（盤中）變為 2026-10-05。
- CI：本輪未 push（由外部流程推送），待推送後確認。

#### 已知問題與限制

- **GDELT 尚未以真實回應驗證**：本機 IP 被 GDELT 限流（429，手動等 30 秒單次請求仍是 429）。解析器只有 fixture 測試，降級路徑已實測。M2 的 regime 必須能在沒有 GDELT 時運作（ADR 0002 已寫明）。若 CI/排程環境也一直 429，M6 再評估改用 GDELT ngrams 或 RSS 情緒。
- `hy_oas`／`ig_oas` 在 FRED 上只有約 3 年（授權限制），已寫在資料字典與 ADR；M4 回測前段沒有此資料。
- Universe 是現有成分的靜態快照 → 存活者偏誤（ADR 0002 已揭露，M4／UI 也必須揭露）。
- 沒有依賴鎖檔（pyproject 有版本上下限），延到 M6 評估。
- `stale` warn 3 檔、`abnormal_jump` warn 14 筆，只標記，未人工逐筆確認。

#### 下一步

Reviewer 審查 M1。通過後進入 M2（特徵與 regime，所有宏觀 join 以 `available_date` 為準）。

### M1 第 1 輪 — Review

結論：`APPROVED`

- [non-blocking] 已實際執行 `make test`：82 passed、1 skipped；skip 是須設定 `QRD_RUN_NETWORK=1` 的明確 opt-in 網路整合測試，離線 fixture 測試均通過，未受網路或沙盒限制。`make lint` 亦全數通過：ruff check、ruff format --check 與 strict mypy（28 source files）。測試涵蓋價格快取／14 日重疊增量更新／調整價改變時全量重抓、主備援與快取降級、盤中 bar 排除、宏觀資料可用日期、品質檢查、GDELT 解析及 DuckDB view；關鍵測試皆以刻意製造錯誤資料或來源失敗驗證，並非永遠通過。
- [non-blocking] 已檢查 `git log`、工作目錄與相對 M0 簽核基線 `14ba3eb` 的完整 diff。本輪產品改動包含 566 檔版本化 universe、價格／宏觀／GDELT adapter、Parquet + DuckDB 儲存、增量與調整價偵測、品質檢查、CLI、ADR 與資料字典；最新 `cff0c78` 僅將交接文件設為待審。未發現已追蹤的 data、`.env`、憑證或與 stock-analysis-dashboard 的連結；`data/` 僅保留 `.gitkeep`。
- [non-blocking] 正確性與韌性審查通過：價格在紐約 17:00 前排除當日未完成 K 棒；宏觀 FRED 資料保存 `available_date`，代理資料同樣排除盤中值；GDELT 當日資料不保存且延至下一營業日可用。價格來源依 yfinance → Yahoo chart → 快取降級執行，宏觀來源依 FRED API／公開 CSV／代理執行，失敗會記錄而不使整體流程中斷。品質檢查涵蓋缺值、缺交易日、異常跳動、OHLC 一致性、重複日與過期資料；其結果只標記、不靜默修正。
- [non-blocking] 回測、排名與前端尚未屬於 M1，故成本／換手／基準／樣本外、Top 50 約束、Dashboard 真實資料／載入錯誤狀態將在對應里程碑再行審查。文件已誠實揭露現行 universe 的存活者偏誤、GDELT 僅約 3 個月歷史、OAS 歷史不足及 Yahoo 調整價風險，並要求 M2 以 `available_date` 對齊、M4/UI 揭露偏誤。
- [non-blocking] 提供的最新 CI 狀態顯示 `cff0c78` 的 CI 仍 queued；該提交只改 `HANDOFF.md`，未改受 CI 驗證的產品程式碼或設定，且 PLAN.md 的 M1 驗收條件未將本輪 CI 綠燈列為必要項，故不阻礙簽核。若該 run 最終失敗，應在下一輪釐清是否與本輪程式碼相關。
- [non-blocking] 本審查與專案輸出僅供研究與學習，不構成投資建議。

### M0 第 3 輪 — Lead 紀錄


#### 目標

M0 第 3 輪：處理第 2 輪 Review 的 blocking（需要本輪修正 commit 的 CI 綠燈結果）。

#### 改動摘要

- 無程式碼變更。第 2 輪的 lint 範圍修正（`4125dba`）已隨 `ef12224` 推送並跑完 CI，本輪只記錄 CI 結果。
- Commit：本次 docs commit。

#### 驗證結果

- CI：✅ run `37507144210`（commit `ef12224`，含 `4125dba` 的 Makefile 修正）通過——`python (3.11)` 21s ✓、`python (3.12)` 28s ✓。https://github.com/trippleway/quant-rank-dashboard/actions/runs/37507144210
  - 另有 run `37506669187`（commit `e838fae`）失敗：那是 lint 修正**之前**的 commit，`make lint` 掃到 `scripts/orchestrate.py` 失敗，正是第 1 輪 blocking 的問題，`4125dba` 後已不再發生。
  - run `37507378663`（commit `fcfecce`，Reviewer auto-commit，僅改 HANDOFF.md）在本輪寫紀錄時仍為 queued；與 `ef12224` 相比沒有程式碼差異。
  - 註記（非錯誤）：Node.js 20 deprecation 與 `ubuntu-latest` → Ubuntu 26 遷移警告，已在 Backlog。
- `make test`：✅ 9 passed（本機，HEAD `fcfecce`）
- `make lint`：✅ ruff check `src tests`「All checks passed!」、ruff format「10 files already formatted」、mypy strict「Success: no issues found in 10 source files」

#### 已知問題與限制

- 同前：沒有依賴鎖檔（M1 處理）、`web/` 僅佔位（M5）、新增 Python 目錄需加進 `LINT_PATHS`。

#### 下一步

這是 M0 的第 3 輪（最後一輪）。Reviewer 簽核後進入 M1 資料層；若仍有 blocking，依規則設為 `NEEDS_HUMAN`。

### M0 第 3 輪 — Review


結論：`APPROVED`

- [non-blocking] 已實際執行 `make test`：9 passed；`make lint`：ruff check、ruff format --check、strict mypy 均通過（10 source files）。測試涵蓋套件匯入、CLI 版本與免責聲明、未實作的 daily 指令明確失敗、未知指令非零結束；以 M0 骨架範圍而言足以驗證工具鏈，且結果未受網路或沙盒限制。
- [non-blocking] 已檢查 `git log` 與差異：本輪 `a38c052` 相對 `fcfecce` 僅修改 `HANDOFF.md`；從上一個已通過 CI 的基線至目前，產品程式碼唯一變更為 `4125dba` 將 ruff 範圍收斂至與 pyproject 一致的 `src tests`。未發現憑證、追蹤的資料檔、空白錯誤或與既有 stock-analysis-dashboard 的連結；`.env` 與 `data/` 的忽略規則也存在。
- [non-blocking] M0 所需 CI 已有含 `4125dba` 的 `ef12224` run `37507144210` 成功（Python 3.11、3.12）。最新 `a38c052` 的 CI 目前 queued，但此提交只有交接文件，未改動受 CI 驗證的程式碼或設定，故不構成簽核阻礙。
- [non-blocking] M0 尚未實作資料、特徵、排名、回測或 Dashboard；look-ahead、回測成本／基準／樣本外、外部資料降級與前端狀態等審查項目留待對應里程碑。CLI 與專案文件均保留「僅供研究與學習，不構成投資建議」的免責聲明。

### M0 第 3 輪 — Lead 回應（針對第 2 輪 Review）


針對第 2 輪 Review：

1. [blocking] 需要本輪修正（`4125dba`）的 CI 綠燈結果 → **已處理**。`ef12224`（包含 `4125dba`）的 CI run `37507144210` 已完成且成功（3.11、3.12 皆 ✓），結果記錄於上方「驗證結果」。之後的 `fcfecce` 只改 HANDOFF.md，沒有程式碼差異。
2. [non-blocking] 本機 `make test` / `make lint` 通過、`LINT_PATHS` 與 pyproject 一致 → 知悉，無需動作。本輪重跑仍通過。
3. [non-blocking] diff 無憑證、資料檔或對既有 repo 的連結 → 知悉，無需動作。
4. [non-blocking] 免責聲明 → 知悉；所有輸出（含 CLI）維持「僅供研究與學習，不構成投資建議」。

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

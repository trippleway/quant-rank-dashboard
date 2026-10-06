# HANDOFF.md — 進度交接

> 這個檔案是 Lead 與 Reviewer 之間、以及 agent 與使用者之間唯一的交接管道。
> 使用者只需要看最上面的「Status」與「Needs human」。
> 規則：每次收工都要更新；保持最新狀態在最上面，舊的輪次往下堆疊。

## Status

- 當前里程碑：M4 回測引擎
- 當前輪次：1 / 3
- 狀態：`READY_FOR_REVIEW`
  - 可用值：`NOT_STARTED` `IN_PROGRESS` `READY_FOR_REVIEW` `CHANGES_REQUESTED` `APPROVED` `NEEDS_HUMAN`
- 最後更新：2026-10-06（Lead）— M4 第 1 輪實作完成，待審查

## Needs human（需要使用者處理）

目前沒有。（已解決：使用者補上 PAT `workflow` scope 並完成 `gh auth login`，push 成功、CI 已確認通過）

（格式：`- [ ] 問題 / 需要的東西 / 為什麼需要 / 建議的預設做法`）

## 里程碑進度

| # | 里程碑 | 狀態 | 通過日期 |
|---|---|---|---|
| M0 | 專案骨架 | APPROVED | 2026-10-06 |
| M1 | 資料層 | APPROVED | 2026-10-06 |
| M2 | 特徵與 regime | APPROVED | 2026-10-06 |
| M3 | 排名引擎 | APPROVED | 2026-10-06 |
| M4 | 回測引擎 | READY_FOR_REVIEW | |
| M5 | 前端 | NOT_STARTED | |
| M6 | 自動化與發布 | NOT_STARTED | |
| M7 | 收尾 | NOT_STARTED | |

## 本輪紀錄（Lead 填寫）

### 目標

M4 第 1 輪：回測引擎。對應 PLAN.md §7 M4 驗收標準「滿足第 5 節全部規格；有一份自動產生的回測報告；包含偏誤與限制說明」。

拆分（對應 PLAN §5）：
1. 期間：預設 5 年，歷史不足時縮短並標示；回測榜排除歷史 < 12 個月者
2. Walk-forward：每個訊號日呼叫每日排名 `rank_asof`（同一套程式），t+1 收盤成交，無 look-ahead 測試
3. 成本：依流動性分級的單邊 bps（5–10 bps，槓桿/反向/VIX ×2），計入換手
4. 再平衡：每週與每月都跑並比較
5. 基準：SPY、60/40、等權 universe、隨機 ×1000
6. 指標：CAGR、波動、Sharpe、Sortino、MDD、Calmar、換手、勝率、IC／Rank IC、十分位價差、各 regime 表現
7. 穩健性：樣本內 3 年／樣本外、敏感度掃描、ablation、Deflated Sharpe
8. 偏誤揭露、前端 JSON（權益曲線、回撤、月報酬熱力圖、滾動 Sharpe、比較表）、自動 Markdown 報告

### 改動摘要

- **讓排名可重複呼叫**（`550cb65`）：`LiquidityPanel`（一次算好每日流動性篩選輸入）、`daily_returns_wide` + `correlations_from_returns`；`rank_asof(..., screen=, returns=)` 可接收預先計算結果，`return_correlations` 改為共用同一函式。`select_top` 改用 numpy 排序（順序規則不變，M3 測試全過）。新增 `ScoringConfig.exclude_short_history`（只用於回測榜，PLAN §5）。每次排名由約 1.0–1.2 秒降到約 0.15 秒。
- **引擎**（`8a2bfe3`，`src/qrd/backtest/`）：
  - `engine.simulate`：向量化（S 個組合 × N 檔）；權重在再平衡之間隨價格漂移；成交日扣 Σ|Δw|·成本；新權重從 t+2 報酬起生效；未投入部位為現金（報酬 0）。
  - `costs.CostModel`：60 日 ADV ≥ $100M 5 bps、≥ $20M 7.5 bps、其餘 10 bps；槓桿/反向/VIX ETP ×2；全域倍數供敏感度。
  - `run.py`：訊號日 = 每週／每月**第一個**交易日（當天即可判定；不用「月底」，理由見 ADR 0005 §2）。策略 = Top N 等權；基準 SPY、60/40（月再平衡）、等權合格池、隨機（每期從合格池抽與策略相同檔數，1000 次、seed 42）。無風險利率 = 前一日 3 個月國庫券。
  - `metrics.py`：績效指標、月報酬、滾動 Sharpe、IC／Rank IC、十分位、PSR／Deflated Sharpe（Bailey & López de Prado）。
  - 穩健性只在**事前選定**的每月頻率上跑：10 個敏感度變體（Top 30、集中度 0／×2、相關性 0.90、全體／類別內 z、winsorize 1/99、懲罰 ×2、成本 ×0.5／×2）+ 7 個 ablation（無 regime、逐一移除 5 個群組、移除風險懲罰）；DSR 試驗數 18。
- **CLI 與輸出**（`089d079`、`5d98301`）：`qrd backtest [--years --start --end --sims --seed --no-robustness --report]`、`make backtest`。輸出 `data/backtest/backtest-<date>.json` 與 `latest.json`（schema 1.0；指定 `--end` 時不更新 latest）、`report-<date>.md`、`holdings-<freq>.parquet`、`daily-<freq>.parquet`。JSON 含兩種頻率的指標、樣本內外、隨機分布與百分位、IC 序列、十分位、regime 表、容量、月報酬、權益曲線／回撤／滾動 Sharpe（含隨機 p05/p50/p95）、穩健性表、DSR、偏誤清單（8 條，期間縮短時加 1 條）、免責聲明。
- **文件**（`b5b7015`、`e270ef3`）：`docs/backtest.md`（方法）、`docs/adr/0005-backtest-engine.md`（選項與取捨）、資料字典新增回測欄位、`docs/backtest-report.md`（以真實資料自動產生）、README／docs 索引、methodology §8 更新。

### 驗證結果

- `make test`：✅ 175 passed、1 skipped（skipped 為需 `QRD_RUN_NETWORK=1` 的網路測試）。本輪新增 27 個測試，全部離線、使用 SYNTHETIC FIXTURE：
  - `tests/test_backtest_engine.py`（12）：漂移、**交易時點**（成交日當天仍是舊組合、t+1 起才吃新組合報酬）、成本與換手、現金、向量化與單一組合一致、排程檢查、區間報酬、成本分級；CAGR、MDD、超額 Sharpe、每期勝率、Calmar、月報酬、IC／十分位、PSR／DSR。
  - `tests/test_backtest_lookahead.py`（11）：2 個切點「截斷輸入 → 從特徵重跑」與完整歷史的持股、分數、策略／SPY／60/40／等權日報酬相同（1e-12）；竄改未來價量與宏觀不影響；**金絲雀**（t+20 因子標成 t）被偵測；成交日 = 訊號日下一交易日；訊號日在任何截斷下為前綴穩定；預先計算的流動性篩選／報酬矩陣與逐日計算的排名**完全相同**（3 個日期）；回測榜排除歷史不足者而每日榜保留；非空測試。
  - `tests/test_backtest_cli.py`（4）：features → backtest 端到端，JSON 涵蓋 §5 每一項（指標、隨機、IC、十分位、切分、regime、曲線、月報酬、容量、穩健性、DSR、偏誤、期間縮短標示）；報告標題與免責聲明；持股權重加總 = 1 且成交日 > 訊號日；無特徵與期間過短的錯誤路徑。
  - 共用 fixture 移到 `tests/synthetic_market.py`（`e5dd4d6`），M3 排名 look-ahead 測試照常通過。
- `make lint`：✅ ruff check「All checks passed!」、ruff format 全部已格式化、mypy strict「Success: no issues found in 54 source files」
- 反向驗證（暫時改壞程式，確認測試會失敗後還原）：
  - `LiquidityPanel` 把 `ffill` 改成 `bfill`（用到未來值）→ `test_precomputed_inputs_match_direct_ranking` 2 個失敗。
  - 訊號日改為「每期最後一個交易日」→ `test_signal_dates_are_first_sessions_and_prefix_stable` 失敗。
  - 引擎讓新權重提前一天生效 → 4 個引擎測試失敗。
- **真實資料**（本機快取，`make backtest`，3 分 28 秒；2021-10-05 ～ 2026-10-05，5.0 年，未縮短）：

  | 每月（主要） | CAGR | Sharpe | MDD | 年換手 |
  |---|---:|---:|---:|---:|
  | 策略 Top 50 | 7.7% | 0.35 | −15.5% | 4.1× |
  | 等權 universe | 10.2% | 0.50 | −17.5% | 0.4× |
  | SPY | 13.8% | 0.61 | −24.5% | — |
  | 60/40 | 8.0% | 0.40 | −20.8% | 0.1× |
  | 隨機中位數 | 8.8% | 0.38 | −18.6% | — |

  - **結論照實寫：策略落後 SPY、等權 universe 與隨機中位數**（CAGR 在隨機分布第 31 百分位）；Rank IC 平均 0.010（t = 0.45）——沒有統計上顯著的選股能力。DSR 0.70（PSR 0.78），無法排除運氣。優點只有回撤較淺、波動較低。
  - 每週：CAGR 6.9%、Sharpe 0.29、年換手 9.7×、成本拖累 1.0%/年。
  - 各 regime：策略在 risk_on／risk_off 期間年化 16%／18%，neutral 期間只有 2%（744 天，占大多數）。
  - Ablation：移除 low_risk 群組（CAGR 10.9%）、不分 regime（9.1%）優於預設——**沒有據此修改參數**（參數事前設定原則；ADR 0005「被拒絕的選項」），已列入 backlog 並需新的樣本外期間驗證。
  - 容量（1% ADV）：中位數約 $25M。
  - 輸出 JSON 約 395 KB。
- CI：本輪未 push（由外部流程推送），待推送後確認。

### 已知問題與限制

- 回測 universe 有存活者偏誤（報告第一條揭露）；等權與隨機基準也有相同偏誤，但不代表互相抵銷。
- 只實作 t+1 收盤成交（PLAN 允許開盤或收盤）；不模擬衝擊與無法成交。
- 隨機基準每期重抽，換手高於策略（週頻尤其明顯，隨機中位數只有 4.8%）；已在 `method` 欄位說明。比較時以月頻為主。
- 樣本內／外切分只用來檢查穩定度，參數沒有做過樣本內調參；DSR 只計入列出的 18 個試驗。
- 「該標的單獨回測」（PLAN §6 Asset Detail）尚未輸出，計畫在 M5 由前端或 publish 階段用價格計算買進持有。
- 完整回測約 3.5 分鐘；M6 排程需決定頻率（每日只跑主要頻率或每週一次完整版）。

### 下一步

Reviewer 審查 M4 第 1 輪。通過後進入 M5（前端：七個頁面，讀 `data/rankings/` 與 `data/backtest/` JSON）。

## Review（Reviewer 填寫）

（尚無）

## Lead 回應（針對 Review 意見）

（尚無）

## Decisions（重大決定索引，細節在 docs/adr/）

- ADR 0001：Python 工具鏈採 venv + pip + hatchling，Makefile 為唯一入口
- ADR 0002：資料來源（yfinance → Yahoo chart → 快取；FRED API → FRED CSV → yfinance 代理；GDELT DOC）與儲存（Parquet + DuckDB view、增量 + 調整基準偵測）
- ADR 0003：因子與 regime（`available_date` 對齊、trailing 分位數、規則式 regime、不做財報型品質/價值）
- ADR 0004：排名引擎（類別內/全體 z 混合、缺值重新正規化、規則式 regime 權重、風險懲罰、貪婪選取 + 硬約束 + 集中度懲罰）
- ADR 0005：回測引擎（直接呼叫 `rank_asof`、每期第一個交易日訊號、t+1 收盤成交、權重漂移、ADV 分級成本、四種基準定義、主要頻率事前選定為每月、DSR）

## Backlog（non-blocking 與未來想法）

- 若 `scripts/` 要納入 lint，需由維護編排流程的人決定（目前刻意排除）
- 升級 CI actions 至支援 Node 24 的版本（`actions/checkout`、`actions/setup-python`），消除 deprecation 警告
- 留意 `ubuntu-latest` 2026-10-19 遷移到 Ubuntu 26；必要時固定 runner 版本
- GDELT 若長期 429：評估 GDELT ngrams 資料集或公開 RSS 標題情緒作為替代
- 依賴鎖檔（`uv lock` / `pip-compile`），M6 評估
- Regime 遲滯（hysteresis）或最短持續天數，視 M4 換手結果決定
- 若日後有 point-in-time 財報源（付費），以新 adapter 加入品質/價值因子
- 相關性去重對極短天期債券 ETF 無效（BIL／SGOV）：可考慮以價格水準相關或同類別規則去重
- 債券曲線位置因子（依 `curve_10y2y` 與天期類別）視 M4 ablation 結果決定是否加入
- M4 ablation：移除 low_risk、不分 regime 的變體在 5 年回測中優於預設；若要改參數，需先寫 ADR 並保留新的樣本外期間驗證（不可用同一段回測挑參數）
- neutral regime 期間策略表現最弱（2.1%/年）：檢查 neutral 權重組
- 隨機基準可另加「與策略同換手」版本，讓週頻比較更公平
- t+1 開盤成交版本（需調整開盤價）
- M6：完整回測約 3.5 分鐘，排程需決定執行頻率

## 歷史輪次

（舊的本輪紀錄與 Review 往下移到這裡，保留脈絡，不要刪）

### M3 第 1 輪 — Lead 紀錄

#### 目標

M3 第 1 輪：排名引擎。對應 PLAN.md §7 M3 驗收標準「每日產出 Top 50 與分數分解；約束條件有測試；方法論文件完成」。

拆分：
1. 橫斷面標準化：winsorize + z-score（按資產類別分組，與全體混合）
2. 因子群組與 regime 權重；缺值降權（重新正規化）
3. 風險懲罰（槓桿／反向、波動率 ETP、高波動、歷史不足）
4. Top 50 貪婪選取：資產類別上限、單一產業上限、槓桿/反向上限、相關性去重、集中度懲罰
5. 分數分解、入選理由（前三大貢獻因子）、主要風險
6. CLI `qrd rank`、輸出 JSON（schema 版本化）、`docs/methodology.md`、ADR 0004

#### 改動摘要

- **合成分數**（`src/qrd/scoring/composite.py`、`config.py`、`explain.py`，`ae26fb9`）：
  - 12 個因子分 5 群（動能、低風險、流動性、收益、存續期[僅債券]），先轉成「越高越好」（`|beta|`、log ADV、log1p Amihud）。
  - 每因子每日橫斷面 winsorize 5%／95% + z-score；**類別內與全體 z 各半混合**；類別內有效樣本 < 5 只用全體（理由見 ADR 0004 §1）。只用通過流動性篩選的標的計算分布。
  - 群組分數 = 可用因子平均；合成分數在可用群組間重新正規化權重（**降權，不當 0**），`coverage` < 0.6 不排名。`contrib_*` 精確加總 = `composite`。
  - Regime 權重（risk_on／neutral／risk_off；unknown → neutral）；存續期為有號傾斜（risk_off +0.10、risk_on −0.10、neutral 0）。
  - 風險懲罰：槓桿 0.25×(|L|−1)、反向 0.25、波動率 ETP 0.5、年化波動 > 40% 線性（上限 1.0）、歷史不足一年 0.25。
  - 入選理由 = 前三大正向貢獻因子；主要風險為規則式標籤（槓桿/反向附持有期限警示、VIX ETP、高波動、深回撤、高 |beta|、利率敏感、低流動性、歷史不足；都沒有時列系統性風險）。
- **Top 50 選取**（`select.py`，`450bcd2`）：決定性貪婪；每步 `adjusted = score − 0.04 × 同產業已入選數`（集中度懲罰），取最高且通過硬約束者——資產類別上限（個股 30／股票 ETF 20／債券 15／商品 10／貨幣 5／VIX ETP 2）、產業上限 8（鍵為 `asset_class/category`）、槓桿/反向上限 5（`leverage != 1`）、126 日日報酬相關 > 0.95 去重（只用 `date <= t`）。略過者附原因；候選不足時少於 50 檔，不放寬。
- **排名流程與 CLI**（`rank.py`、`cli.py`，`5863da0`）：`rank_asof(factors, regime, prices, asof=…)` → 過期／流動性／覆蓋率篩選 → 打分 → 選取。`qrd rank [--data-dir] [--asof]`／`make rank` 寫 `data/rankings/top50-<date>.json`（schema 1.0，含 regime、權重、約束、每檔分解、理由、風險、skipped、ineligible、免責聲明與代理指標說明）、`latest.json`（僅未指定 `--asof` 時更新）、`scores-<date>.parquet`（全部候選）。無特徵或 `--asof` 超過特徵範圍時 exit 1。
- **文件**（`6f0fa1b`）：`docs/methodology.md`（完整方法、權重表、約束、輸出、已知限制）、`docs/adr/0004-ranking-engine.md`（標準化、缺值、權重、懲罰、貪婪 vs 最佳化的取捨）、資料字典新增 rankings 欄位、README／docs 索引更新。

#### 驗證結果

- `make test`：✅ 148 passed、1 skipped（skipped 為需 `QRD_RUN_NETWORK=1` 的網路測試）。本輪新增 34 個測試，全部離線、使用 SYNTHETIC FIXTURE：
  - `tests/test_scoring.py`（13）：winsorize／z-score、類別混合與小類別退回全體、貢獻加總 = composite、regime 改變排序（risk_on 偏動能、risk_off 偏低風險）、unknown = neutral、缺值重新正規化（非 0）、存續期只對債券且方向隨 regime、各項懲罰、入選理由、風險標籤。
  - `tests/test_selection.py`（10）：名次連續、≤ Top N、NaN 排除、資產類別上限、產業上限（且分資產類別）、槓桿/反向上限（含 −1x）、相關性去重、集中度懲罰改變選取、同分決定性、相關性只用過去價格。
  - `tests/test_rank_lookahead.py`（7）：3 個切點「截斷輸入重算」與完整歷史的分數表、Top N、skipped、ineligible、JSON **完全相同**；2 個切點竄改未來價格／量／宏觀不影響；金絲雀（用 t+20 的因子打分）必須被偵測；非空測試確認相關性去重、過期、槓桿上限、regime 真的有作用。
  - `tests/test_rank_cli.py`（4）：features → rank 端到端、JSON 分解自洽、`--asof` 不覆蓋 latest、缺特徵與超出範圍的錯誤路徑。
- `make lint`：✅ ruff check「All checks passed!」、ruff format「45 files already formatted」、mypy strict「Success: no issues found in 45 source files」
- 反向驗證：
  - 槓桿上限測試在第一版實作（以 `|leverage| != 1` 計）上失敗——抓到 −1x 反向 ETF 沒被計入的真實 bug，已修正。
  - 把相關性計算的 `date <= asof` 過濾拿掉：`test_return_correlations_use_only_past_bars` 與 2 個竄改未來的排名測試失敗；還原後通過。
- **真實資料**（本機快取，`qrd features` 7.4 秒 + `qrd rank` 2.7 秒）：
  - asof 2026-10-05，regime `neutral`；558 檔合格、8 檔不合格（AVB／EA／EQR 過期；FXA／FXB／FXC／FXF／UDN 成交額 < $5M）。
  - Top 50：個股 30（達上限）、股票 ETF 10、債券 ETF 7、商品 ETF 2、貨幣 ETF 1；槓桿/反向 0。前 5：PSX、VLO、TGT、EWT、MPC。
  - 去重生效：DBC（vs PDBC 0.994）、JNK（vs HYG 0.990）、SPY（vs VOO 0.999）。
  - `--asof 2022-06-15`：regime `risk_off`，權重切換為防禦組；前列為 CVX、MRK、XOM、BMY、XLE；入選債券為短天期／抗通膨（STIP、TIP、BIL、VCSH、MUB、BNDX），沒有長天期債；`latest.json` 未被覆蓋。
  - `latest.json` 約 144 KB。
- CI：本輪未 push（由外部流程推送），待推送後確認。

#### 已知問題與限制

- 權重、門檻、懲罰、上限皆為主觀設定（可解釋、未擬合）；M4 需做敏感度掃描與 ablation（特別是存續期傾斜：risk-off 偏好長天期的假設在 2022 通膨衝擊時不成立）。
- 無財報型品質/價值、無商品期限結構、債券曲線位置無獨立因子（只經 regime `curve` 成分）——methodology §8 已揭露。
- 相關性去重只看日報酬：BIL 與 SGOV 這類極短天期 ETF 日報酬近似雜訊，會同時入選。
- 「主要風險」多數個股只有 `systematic` 一項（沒有觸發特定門檻）；M5 UI 可再搭配因子雷達圖呈現。
- `qrd daily` 仍未實作（M4–M6）；排名歷史（UI 的「歷史排名變化」「Changes」）目前靠每日 `top50-<date>.json` 累積，M4 回測可批次產生。

#### 下一步

Reviewer 審查 M3 第 1 輪。通過後進入 M4（回測引擎：walk-forward 逐日呼叫 `rank_asof`、成本、週／月再平衡、基準、指標、穩健性、偏誤揭露、自動報告）。

### M3 第 1 輪 — Review

結論：`APPROVED`

- [non-blocking] 已實際執行 `make test`：148 passed、1 skipped。skip 是明確需設定 `QRD_RUN_NETWORK=1` 的網路測試，並非沙盒阻擋或測試失敗；其餘離線 fixture 測試均通過。`make lint` 亦全數通過：ruff check、ruff format --check 與 strict mypy（45 source files）。`git diff --check` 無輸出，工作目錄乾淨。
- [non-blocking] 已檢查自 M2 簽核提交 `3632993` 至目前 `c08d5d7` 的 git log 與 diff。產品改動限於 M3 排名：橫斷面標準化、regime 權重、風險／集中度懲罰、Top-N 約束與去重、CLI／版本化 JSON、測試和方法文件；其後兩個提交只更新 HANDOFF。未發現已追蹤的資料檔、`.env`、憑證，或與 `stock-analysis-dashboard` 的連結。
- [non-blocking] 正確性審查通過：`rank_asof` 只取 asof 當日因子、當日以前價格作流動性及 126 日報酬相關性，且未知 regime 明確採 neutral 權重。截斷輸入、竄改未來價格／量／尚不可得宏觀觀測的測試，均核對完整歷史結果的分數表、Top N、略過／不合格清單與 JSON 相同；金絲雀也證明該檢查不是恆真。分數分解精確加總為 composite，JSON 另明列風險與集中度懲罰，入選理由和主要風險可追溯。
- [non-blocking] 約束與韌性審查通過：資產類別、類別、槓桿／反向（含 -1x）上限、相關性去重、候選不足不放寬、同分決定性及無資料／超出特徵範圍錯誤路徑皆有會失敗的測試。輸出含 schema 版本、代理指標與存活者偏誤揭露、免責聲明；權重與門檻主觀、歷史與回測限制也已明列。交易成本、換手、基準、樣本外與完整偏誤評估屬 M4，前端呈現屬 M5，仍須依 PLAN.md 分別驗收。
- [non-blocking] 提供的 CI 狀態顯示目前 `c08d5d7` run 仍 queued；兩個 completed failure 對應較早 handoff 文件提交，未見目前 M3 程式碼的 CI 結果。PLAN.md 的 M3 驗收為每日 Top 50、分數分解、約束測試和方法論，已由本機完整驗證；若 queued run 最終失敗，下一輪應釐清是否相關。
- [non-blocking] 本審查與專案輸出僅供研究與學習，不構成投資建議。

### M2 第 2 輪 — Lead 紀錄

#### 目標

M2 第 2 輪：處理第 1 輪 Review 的唯一 blocking——`compute_rate_duration` 在殖利率發布日期非單調（舊觀測晚發布）時會洩漏尚未可得的資料。

#### 改動摘要

- **修正**（`4039df3`，`src/qrd/features/factors.py`）：`rate_duration` 改為「版本（vintage）」規則——t 日的值只用 `available_date <= t` 的殖利率觀測建立 (報酬, Δ殖利率) 配對，取到 t 日已發布之最新觀測為止的 rolling 估計。缺口（舊觀測未發布）期間，Δ殖利率跨過缺口計算，與「把輸入截斷在 t 重算」**逐位元相同**。
  - 效能：若 t 日已發布的最新觀測之前沒有未發布缺口（發布日期單調的正常情況），直接重用全歷史 rolling 估計（rolling 值只依賴前綴）；只有落在缺口內的日期，才依「已發布筆數」分組，以該版本重算。
  - 同一 `obs_date` 有多筆時，取已發布版本中 `available_date` 最新的一筆（版本內決定性排序）。
- **測試（先寫、確認在舊程式碼上失敗）**：
  - `tests/test_factors.py::test_rate_duration_non_monotone_publication_has_no_lookahead`：重現 Reviewer 的情境（280 日，第 151 筆觀測延到第 261 日發布，且改成 +3pp 的離群值），在缺口前、中、後 9 個日期比較全歷史與 point-in-time 重算必須完全相等；發布前估計 ≈ 7.0（±5%），發布後被離群值拉離。
  - `test_rate_duration_matches_point_in_time_on_every_date`：每筆觀測隨機延遲 0–3 週（大量非單調），每 4 個交易日比對一次全歷史 vs 截斷重算。
  - `tests/test_lookahead.py`：整體 fixture 的 `ust_10y` 第 380 筆觀測改為第 470 個交易日才發布，使切點 420 落在缺口內；截斷與竄改（未來才發布的值改為 1e6）測試都涵蓋此情形。**用舊程式碼跑時這兩個 [420] 測試失敗**，新程式碼通過。
- **文件**（`474d592`）：ADR 0003 對齊規則改寫為版本規則並註明本輪修正。

#### 驗證結果

- `make test`：✅ 114 passed、1 skipped（skipped 為需 `QRD_RUN_NETWORK=1` 的網路測試）。本輪新增 2 個單元測試，並擴充整體 look-ahead fixture。
- `make lint`：✅ ruff check「All checks passed!」、ruff format「36 files already formatted」、mypy strict「Success: no issues found in 36 source files」
- 反向驗證：把 `factors.py` 換回修正前（`81fb8b5`）版本，新的 2 個單元測試與 `test_lookahead.py` 的 2 個 [420] 測試失敗。
- **真實資料**（本機快取，`qrd features`，7.6 秒，與修正前 8.6 秒相當）：真實 `ust_10y` 的 `available_date` 隨 `obs_date` 單調（1,748 筆），因此正式輸出數值不變——2026-10-05 存續期 SHY 1.7、IEF 7.0、TLT 12.7、EDV 18.3、TMF 37.2、TBT −25.6。本修正是對非單調發布情境（修訂、來源切換、代理資料）的正確性保證。
- CI：本輪未 push（由外部流程推送），待推送後確認。

#### 已知問題與限制

- 第 1 輪列出的限制皆仍適用（無財報型品質/價值因子、無期限結構、regime 暖機至約 2020-10、門檻主觀、FRED 非 vintage、`stale` 標的、品質排除依最新報告、`rate_duration` 對股票的解釋）。
- 版本規則只針對「發布日期」；FRED 只存最新修訂值（非 ALFRED vintage），修訂本身的 look-ahead 仍屬 M4 偏誤揭露項目。
- 缺口期間會依已發布筆數重算 rolling；若某來源長期大量亂序發布，計算量會上升（仍正確）。真實資料目前沒有缺口。

#### 下一步

Reviewer 審查 M2 第 2 輪。通過後進入 M3（排名引擎）。

### M2 第 2 輪 — Review

結論：`APPROVED`

- [non-blocking] 已實際執行 `make test`：114 passed、1 skipped。skip 為明確需設定 `QRD_RUN_NETWORK=1` 的網路測試，並非沙盒或網路阻擋；離線測試均通過。`make lint` 亦全數通過：ruff check、ruff format --check 與 strict mypy（36 source files）。另獨立執行本輪兩個 rate-duration 回歸測試及完整 look-ahead 測試檔，11 passed。
- [non-blocking] 已檢查 `git log`、工作目錄及相對上一輪 Reviewer 基線 `81fb8b5` 的 diff。本輪產品改動限於 rate-duration 的 vintage 計算、其單元／整合 look-ahead 測試與 ADR；工作目錄乾淨，`git diff --check` 無問題。未發現追蹤中的資料檔、`.env`、憑證或與 `stock-analysis-dashboard` 的連結；`data/` 僅有 `.gitkeep`。
- [non-blocking] 原 blocking 已修正且獨立核對通過：每個日期先以 `available_date <= t` 形成可用殖利率版本，發現舊觀測晚發布造成缺口時，以該版本重算，避免完整歷史中的未發布觀測進入報酬／Δ殖利率配對；沒有缺口時才重用只依賴前綴的 rolling 結果。新增測試涵蓋單一晚發布且離群、隨機延遲的多個非單調發布日，以及 feature-stage 截斷與竄改；皆將 `available_date > t` 的資料排除，測試也有非空斷言，足以偵測原有洩漏。
- [non-blocking] M2 驗收所需的因子／regime 單元測試與「截掉未來資料不改變過去輸出」證據已具備。回測成本、換手、基準、樣本外切分與偏誤完整揭露屬 M4；Top 50、約束與方法論屬 M3；前端屬 M5，將在各自里程碑審查。ADR 0003 也誠實說明 FRED 非 ALFRED vintage 的修訂風險仍待 M4 揭露。
- [non-blocking] 提供的 CI 狀態中，`b31358f` 的 CI 仍為 queued；先前兩個 failure 對應較早的 handoff／文件提交。M2 的 PLAN 驗收不以本輪 CI 完成為條件，且本機完整測試與 lint 已通過，因此不阻礙本次簽核；若 current run 最終失敗，後續應釐清其是否與本輪相關。
- [non-blocking] 本審查與專案輸出僅供研究與學習，不構成投資建議。

### M2 第 2 輪 — Lead 回應（針對第 1 輪 Review）

針對 M2 第 1 輪 Review：

1. [blocking] `compute_rate_duration` 在發布日期非單調時洩漏未發布殖利率 → **已修正**（`4039df3`）。改為版本規則：t 日的估計只用 `available_date <= t` 的觀測建立配對，與截斷重算逐位元相同。已新增 Reviewer 情境的回歸測試、全日期隨機延遲測試，並在整體 look-ahead fixture 加入晚發布的 `ust_10y` 觀測（切點 420 位於缺口內）；三者都已確認在舊程式碼上失敗。ADR 0003 已更新（`474d592`）。
2. [non-blocking] `make test`／`make lint` 通過、diff 範圍與安全檢查 → 知悉。本輪重跑仍通過（114 passed、1 skipped；lint 全過）。
3. [non-blocking] 價格因子、macro panel、regime 的對齊設計與測試具體可執行，但需先修 rate duration → 知悉，已依第 1 點處理。
4. [non-blocking] 免責聲明 → 知悉；所有輸出維持「僅供研究與學習，不構成投資建議」。

### M2 第 1 輪 — Lead 紀錄

#### 目標

M2 第 1 輪：特徵與 regime。對應 PLAN.md §7 M2 驗收標準「因子與 regime 有單元測試；用測試證明沒有 look-ahead（把未來資料截掉結果不變）」。

拆分：
1. 價格因子（每標的每日）：動能 12-1／6m／3m、趨勢（vs 200 日均線）、已實現波動、下行偏差、最大回撤、beta、流動性與成本代理
2. 資產類別專屬：債券的經驗利率存續期（對 10y 殖利率變動的回歸，宏觀以 `available_date` 對齊）、過去 12 個月配息率代理
3. 宏觀 point-in-time 面板（每個交易日只看 `available_date <= t` 的觀測）
4. Regime：VIX、信用（OAS 與 HYG/IEF 代理）、曲線、美元、油價、黃金、SPY 趨勢、GDELT 語調 → risk-on / neutral / risk-off
5. Look-ahead 測試：截斷未來資料、竄改未來資料，過去結果必須完全不變
6. CLI `qrd features`、ADR 0003（因子與 regime 設計取捨）、資料字典更新

#### 改動摘要

- **價格因子**（`src/qrd/features/factors.py`，`0047c4f`）：每標的每日 `mom_12_1`、`mom_6m`、`mom_3m`、`trend_200`、`vol_63`、`downside_63`、`max_dd_252`（只計視窗內高點，精確計算）、`beta_252`（vs SPY，以標的自身交易日對齊）、`adv_usd_60`、`amihud_60`、`trailing_yield_252`（配息率代理）、`history_sessions`／`short_history`。全部 trailing 視窗；歷史不足為 NaN 而非 0。
- **債券專屬**：`compute_rate_duration` 經驗存續期 = −100·cov(r, Δy10)/var(Δy10)；由觀測日 d 以前的配對估出的值要到 `available_date(d)` 才可用（有測試：5 日延遲的值等於 1 日延遲版本晚 4 個交易日的值）。
- **宏觀 panel**（`features/macro.py`，`4fd3600`）：以 `available_date` 做 `merge_asof`；晚到的舊觀測不覆蓋新值；> 21 日曆天未更新視為缺值；欄位固定為全部已知序列（schema 不隨歷史長度改變）。
- **Regime**（`features/regime.py`）：10 個成分（VIX、HY OAS、HYG/IEF 信用代理、SPY 趨勢、曲線、美元、油、黃金、GDELT ×2），各以 trailing 756 日分位數轉成 [−1, 1] 壓力分數，可用成分加權平均 + span 5 因果 EWM；±0.25 為門檻；可用成分 < 3 為 `unknown`。輸出 `contrib_*`（加總 = 原始壓力）供 UI 解釋。
- **Pipeline 與 CLI**（`features/build.py`、`cli.py`，`54a9611`）：`build_features`（純函式）、`point_in_time`（價格 `date <= t`、宏觀 `available_date <= t`）、`qrd features [--data-dir] [--asof]` / `make features`，寫入 `data/features/{factors,macro_panel,regime}.parquet`；排除最新品質報告中 `error` 的標的；無資料時 exit 1 並提示先 ingest。
- **Look-ahead 測試**（`tests/test_lookahead.py`，`803947f`）：700 日 FIXTURE（含晚上市、缺一日、週頻序列、7 日延遲、HY OAS 晚開始），4 個切點截斷後重算，t 以前的 factors／panel／regime **完全相等**；2 個切點把未來價格亂乘、量歸零、t 後才公布的宏觀值改為 1e6，結果不變；2 個金絲雀（以 `obs_date` join、置中視窗）證明檢查器會失敗；另有一個測試確保晚切點各因子與 9 個 regime 成分都真的有值（非空測試）。
- **文件**（`8173ac3`）：`docs/adr/0003-features-and-regime.md`（對齊規則、因子清單、不做財報型品質/價值與期限結構的理由、regime 設計與取捨、實測）、`docs/data-dictionary.md` 新增特徵三個檔案的欄位說明；README／Makefile 加 `make features`。

#### 驗證結果

- `make test`：✅ 112 passed、1 skipped（skipped 為需 `QRD_RUN_NETWORK=1` 的網路測試）。本輪新增 30 個測試（factors 9、regime 9、look-ahead 9、CLI 3），全部離線、使用標示為 FIXTURE 的合成資料。
- `make lint`：✅ ruff check「All checks passed!」、ruff format「36 files already formatted」、mypy strict「Success: no issues found in 36 source files」
- **真實資料**（本機 M1 快取，`qrd features`，約 8.6 秒）：
  - asof 2026-10-05；563 檔有當日因子（AVB、EA、EQR 最後 K 棒在 2026-08，即 M1 的 `stale` warn），排除 0 檔；12 個數值因子當日覆蓋率 100%。
  - 合理性：經驗存續期 SHY 1.7、IEF 7.0、TLT 12.7、EDV 18.3、TMF 37.2、TBT −25.6；beta SSO 1.99、SQQQ −4.26（−3 × QQQ，而 QQQ 對 SPY 的 beta 為 1.43）；配息率 HYG 6.1%、TLT 4.6%。
  - Regime：2026-10-05 為 `neutral`（stress −0.047，8 個成分；GDELT 無資料、ig_oas 未使用）。2022 年 153 日 `risk_off`、0 日 `risk_on`；2025-04 關稅衝擊整月 `risk_off`（峰值 0.545）；2024 年 `risk_on` 121 日。
- CI：本輪未 push（由外部流程推送），待推送後確認。

#### 已知問題與限制

- **沒有財報型品質/價值因子**：免費來源沒有 point-in-time 財報，用現在的快照回測就是 look-ahead；改以缺值降權（ADR 0003 §3）。個股價值面只有 `trailing_yield_252` 代理。這符合 PLAN §4「資料不足時降權而非當作 0」，但若 Reviewer 認為需要更多，請提出。
- **商品／貨幣期限結構**：沒有免費期貨曲線，未提供。
- **Regime 暖機**：價格從 2019-10 開始、分位數需 252 筆 → 約 2020-10 以前為 `unknown`（含 2020-03）。5 年回測（約 2021-10 起）不受影響。
- Regime 門檻與權重是主觀設定（規則式、無擬合）；每年切換 10–17 次，M4 需做敏感度掃描並評估換手，必要時加遲滯。
- FRED 只存最新版本（非 vintage），修訂風險在 M4 偏誤揭露。
- `stale` 標的（AVB、EA、EQR）仍會輸出到其最後一日的因子；M3 選股須以「當日有因子」為條件排除。
- 品質排除依「最新一份」品質報告；若最近一次 ingest 只跑部分標的（`--tickers`），報告也只涵蓋那些標的。M6 每日排程跑全量時不影響；必要時 M3 改為在 features 階段重跑品質檢查。
- `rate_duration` 對所有標的都計算，但只對債券 ETF 有直接解釋力（股票的值是利率敏感度，不是存續期）。

#### 下一步

Reviewer 審查 M2。通過後進入 M3（排名引擎：橫斷面 winsorize + z-score（按資產類別）、regime 權重、風險與集中度懲罰、Top 50 約束、分數分解、`docs/methodology.md`）。

### M2 第 1 輪 — Review

結論：`CHANGES_REQUESTED`

- [blocking] `compute_rate_duration` 沒有在建立 rolling (報酬、Δ殖利率) 配對時依 `available_date` 過濾，會在發布日期非單調的資料中洩漏尚未可得的殖利率。可重現：對 280 個交易日的合成殖利率，將第 151 筆觀測的 `available_date` 延後到第 261 日，於第 221 日比較全歷史與只保留 `available_date <= t` 的輸入，`rate_duration` 分別為約 `7.00` 與 `-8.29`，違反本輪「截掉未來資料結果不變」及 ADR 0003 的可得日期規則。目前測試只覆蓋全序列固定發布延遲，未涵蓋此情形。請讓每個估計只使用其估計日當下已發布的殖利率觀測（或以可得日期順序重建有效配對），並新增此非單調發布日期的回歸測試及整體 look-ahead 測試覆蓋。
- [non-blocking] 實際執行 `make test` 通過：112 passed、1 skipped；skip 是明確標示、需設定 `QRD_RUN_NETWORK=1` 的網路測試，非沙盒失敗。`make lint` 也通過 Ruff check、Ruff format check 與 mypy strict。已檢查自 M1 簽核後的 git log/diff（`0047c4f` 至 `17792b9`）；改動範圍符合 M2，`git diff --check` 無輸出，未發現憑證、提交的資料檔或與既有 stock-analysis-dashboard 的連結。
- [non-blocking] 價格因子、macro panel 與 regime 的 trailing／`available_date` 設計及其截斷、竄改、canary 測試具體且可執行；但上述 rate duration 缺陷會影響債券因子的時間對齊，修正前不足以滿足 M2 的無 look-ahead 驗收。
- [non-blocking] 本審查與專案輸出僅供研究與學習，不構成投資建議。

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

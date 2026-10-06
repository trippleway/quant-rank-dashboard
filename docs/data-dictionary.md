# 資料字典

> 僅供研究與學習，不構成投資建議。設計理由見 [ADR 0002](adr/0002-data-sources-and-storage.md)。

所有資料由 `qrd ingest` 寫入 `data/`（不進 git；可用 `QRD_DATA_DIR` 改位置）。

## 價格 `data/prices/<TICKER>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | datetime64 | 交易所當地的交易日（無時區） |
| `ticker` | str | Yahoo 代碼（例：`BRK-B`） |
| `open` `high` `low` `close` | float | 未調整股利、但已調整分割的價格（Yahoo 慣例） |
| `adj_close` | float | 股利與分割調整後收盤價；報酬計算用這欄。來源未提供時為 NaN |
| `volume` | float | 成交量（股） |
| `source` | str | `yfinance` / `yahoo_chart` |

- 主來源 yfinance，備援 Yahoo chart HTTP（同一上游）；都失敗時沿用快取（`degraded`）。
- 增量：每次重抓最後 14 天；重疊區間與快取不符時整段重抓（新除息/分割）。
- 紐約 17:00 前不寫入當日 K 棒。
- 已知限制：yfinance 調整價品質不保證（偶有錯誤 tick、遺漏股利）；標的清單為現有成分 → 存活者偏誤。

## 宏觀 `data/macro/<series>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `obs_date` | datetime64 | 觀測日 |
| `available_date` | datetime64 | **最早可使用日**（觀測日 + 發布延遲）。特徵必須以此對齊 |
| `series` | str | 序列 id（下表） |
| `value` | float | 數值 |
| `source` | str | `fred_api` / `fred_csv` / `yfinance_proxy` |
| `is_proxy` | bool | 是否為代理資料（單位/定義可能與 FRED 原序列不同） |

| series | FRED | 代理 | 延遲（營業日） | 說明 / 限制 |
|---|---|---|---|---|
| `ust_3m` | DGS3MO | ^IRX | 1 | 3 個月公債殖利率 (%) |
| `ust_2y` | DGS2 | — | 1 | 2 年 |
| `ust_5y` | DGS5 | ^FVX | 1 | 5 年 |
| `ust_10y` | DGS10 | ^TNX | 1 | 10 年 |
| `ust_30y` | DGS30 | ^TYX | 1 | 30 年 |
| `curve_10y2y` | T10Y2Y | — | 1 | 10y − 2y 利差 (pp) |
| `breakeven_10y` | T10YIE | — | 1 | 10 年損益兩平通膨 |
| `hy_oas` | BAMLH0A0HYM2 | — | 1 | 高收益債 OAS；**FRED 只提供約最近 3 年** |
| `ig_oas` | BAMLC0A0CM | — | 1 | 投資級公司債 OAS；**約最近 3 年** |
| `vix` | VIXCLS | ^VIX | 1 | VIX 收盤 |
| `usd_broad` | DTWEXBGS | DX-Y.NYB | 7 | Fed 廣義美元指數（週更新）；代理 DXY 定義不同 |
| `wti` | DCOILWTICO | CL=F | 7 | WTI 現貨（EIA 週更新）；代理為近月期貨 |
| `gold` | — | GC=F | 0 | 黃金近月期貨（FRED 無免費序列，yfinance 為主來源） |

代理資料**永遠不會覆蓋**已存在的 FRED 序列。

## 情緒 / 國際局勢代理 `data/sentiment/<name>.parquet`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `obs_date` | datetime64 | UTC 日 |
| `available_date` | datetime64 | 次一營業日 |
| `series` | str | `gdelt_tone_economy` / `gdelt_tone_geopolitics` |
| `value` | float | GDELT DOC 2.0 平均語調（負值 = 負面報導多） |
| `source` | str | `gdelt_doc` |

- **這是代理指標**：衡量新聞用語的正負面，不等於「國際局勢」本身。
- DOC API 只涵蓋最近約 3 個月；歷史從開始執行起每日累積，回測期間大部分沒有此資料。
- API 限流嚴格；失敗只降級，不影響其他資料。

## 執行紀錄與品質報告

- `data/logs/ingest-<UTC 時間>.json`：每個標的/序列的狀態 `ok`（主來源）/ `fallback`（備援）/ `degraded`（沿用舊快取）/ `failed`（無資料），以及來源與訊息。
- `data/quality/quality-<UTC 時間>.json`：品質問題清單（`ticker`, `check`, `severity`, `detail`, `date`）。
  `severity=error` 的標的為 unusable，下游排除。檢查項目見 `src/qrd/ingest/quality.py` 模組說明。

## Universe `src/qrd/universe/seeds.csv`

| 欄位 | 說明 |
|---|---|
| `ticker` | Yahoo 代碼 |
| `asset_class` | `equity` / `equity_etf` / `bond_etf` / `commodity_etf` / `currency_etf` / `volatility_etp` |
| `category` | 個股為 GICS 產業；ETF 為子類別（如 `treasury_long`） |
| `leverage` | 槓桿倍數，反向為負（例：`SQQQ` = −3、`SVXY` = −0.5） |
| `instrument` | `stock` / `etf` / `etn` |

載入後另有衍生欄位 `leveraged_or_inverse`（`leverage != 1`）。

## 特徵 `data/features/*.parquet`（`qrd features` 產出）

設計與 look-ahead 規則見 [ADR 0003](adr/0003-features-and-regime.md)。`--asof YYYY-MM-DD` 只用當日以前可得的資料重算。

### `factors.parquet`（每標的每交易日一列）

| 欄位 | 說明 |
|---|---|
| `date` `ticker` `asset_class` `category` `leverage` | 鍵與 universe 屬性；品質報告為 unusable 的標的不輸出 |
| `mom_12_1` `mom_6m` `mom_3m` | 動能（簡單報酬） |
| `trend_200` | 價格 / 200 日均線 − 1 |
| `vol_63` `downside_63` | 年化已實現波動／下行偏差 |
| `max_dd_252` | 過去 252 日內最大回撤（≤ 0） |
| `beta_252` | 對 SPY 的 beta |
| `adv_usd_60` `amihud_60` | 60 日平均成交額（美元）／Amihud 非流動性 × 1e6 |
| `trailing_yield_252` | 過去 12 個月配息率代理（總報酬 ÷ 價格報酬 − 1） |
| `rate_duration` | 經驗存續期（年），對 10 年殖利率變動回歸；債券 ETF 最有意義 |
| `history_sessions` `short_history` | 累計 K 棒數；< 252 為 `short_history`（信心低） |

歷史不足時為 NaN（不是 0）。

### `macro_panel.parquet`

`date` + 每條宏觀／情緒序列一欄：當日已公布（`available_date <= date`）的最新值；超過 21 天未更新為 NaN。

### `regime.parquet`

| 欄位 | 說明 |
|---|---|
| `date` | 交易日（SPY 日曆） |
| `stress_raw` | 各成分加權平均壓力 ∈ [−1, 1]（正 = 壓力大） |
| `stress_score` | `stress_raw` 的 span 5 因果 EWM，用來分類 |
| `regime` | `risk_on` / `neutral` / `risk_off` / `unknown`（可用成分 < 3） |
| `n_components` | 當日可用成分數 |
| `contrib_<成分>` | 該成分對 `stress_raw` 的貢獻；加總 = `stress_raw` |

Regime 輸入是**代理指標**，不是國際局勢本身的量測。

## 排名 `data/rankings/`（`qrd rank` 產出）

方法見 [methodology.md](methodology.md)、設計取捨見 [ADR 0004](adr/0004-ranking-engine.md)。
`--asof YYYY-MM-DD` 對過去某日排名（需該日已有特徵），此時不更新 `latest.json`。

### `top50-YYYY-MM-DD.json` / `latest.json`（schema_version `1.0`）

| 欄位 | 說明 |
|---|---|
| `asof` `generated_at` | 排名日（資料截止的交易日）與產生時間（UTC） |
| `disclaimer` `notes` | 免責聲明；代理指標、缺少因子、存活者偏誤等說明 |
| `regime` | `label`、`stress_score`、`n_components`、`contributions`（各成分）、`weights_regime`（實際採用的權重組；`unknown` → `neutral`） |
| `weights` | 當日各因子群組權重 |
| `constraints` | Top N、資產類別上限、產業上限、槓桿/反向上限、相關性門檻、集中度懲罰、最低覆蓋率 |
| `universe` | `candidates` / `eligible` / `ineligible` 檔數 |
| `counts` | 入選者的資產類別分布與槓桿/反向檔數 |
| `top[]` | 見下表 |
| `skipped[]` | 因約束被略過的候選：`ticker` `score` `reason` |
| `ineligible[]` | 不參與排名者：`ticker` `reason`（過期、流動性、覆蓋率不足） |

`top[]` 每一筆：

| 欄位 | 說明 |
|---|---|
| `rank` `ticker` `asset_class` `category` `leverage` | 排名與 universe 屬性 |
| `score` | 最終分數 = `composite` − `risk_penalty` − `concentration_penalty` |
| `composite` | regime 加權後的合成分數（z-score 單位）；= 所有 `factors[].contribution` 之和 |
| `risk_penalty` `penalties` | 風險懲罰總和與明細（`leverage` `inverse` `volatility_etp` `high_vol` `short_history`，只列 > 0） |
| `concentration_penalty` | 選取時因同產業已入選而扣的分數 |
| `coverage` | 有資料的群組權重占適用權重的比例 |
| `short_history` | 歷史不足一年（信心低） |
| `groups.<群組>` | `score`（群組平均 z）、`weight`（重新正規化後的實際權重）、`contribution` |
| `factors[]` | `factor` `label` `group` `value`（原始值）`z` `contribution` |
| `reasons[]` | 入選理由：貢獻最大的前三個正向因子 |
| `risks[]` | 主要風險（最多 3 項）：`code` `label` |

### `scores-YYYY-MM-DD.parquet`

當日所有通過流動性篩選的候選：原始因子、`z_*`、`grp_*`、`w_*`、`contrib_*`、`composite`、`coverage`、
`pen_*`、`risk_penalty`、`score`（覆蓋率不足者為 NaN）。供回測與前端使用。

## 回測 `data/backtest/`（`qrd backtest` 產出）

方法見 [backtest.md](backtest.md)、設計取捨見 [ADR 0005](adr/0005-backtest-engine.md)。
指定 `--end` 時不更新 `latest.json`。

### `backtest-YYYY-MM-DD.json` / `latest.json`（schema_version `1.0`）

| 欄位 | 說明 |
|---|---|
| `asof` `generated_at` `disclaimer` `headline` | 資料截止日、產生時間（UTC）、免責聲明、閱讀提醒 |
| `period` | `start` `end` `years` `requested_start` `shortened`（期間是否因歷史不足縮短）`in_sample_end` |
| `assumptions` | 訊號、成交、權重、合格池、成本分級（`costs.tiers_bps`）、無風險利率來源、主要頻率、`parameters_fitted`（固定為 false）、`top_n` |
| `series_labels` | 各組合鍵（`strategy` `spy` `sixty_forty` `equal_weight` `random_median`）的中文名稱 |
| `frequencies.weekly` / `frequencies.monthly` | 見下表 |
| `robustness` | `variants[]`（`name` `kind`=base/sensitivity/ablation `label` `cagr` `sharpe` `max_drawdown` `turnover_annual` `sharpe_in_sample` `sharpe_out_of_sample`）、`deflated_sharpe`（`n_trials` `psr_vs_zero` `deflated_sharpe` `expected_max_sharpe_daily` `skew` `kurtosis` 等） |
| `biases[]` | 偏誤與限制說明（中文） |

`frequencies.<freq>`：

| 欄位 | 說明 |
|---|---|
| `rebalances` `first_trade` | 再平衡次數、首次成交日 |
| `metrics.<組合>` | `cagr` `total_return` `ann_vol` `sharpe` `sortino` `max_drawdown` `calmar` `win_rate_daily` `win_rate_periods` `turnover_annual` `cost_drag_annual` `days` |
| `split.in_sample` / `split.out_of_sample` | 同上指標（各組合），以 `period.in_sample_end` 切分 |
| `random` | `n` `seed` `method`；`cagr` `sharpe` `max_drawdown` 的 p05/p25/p50/p75/p95；`strategy_percentile.cagr` / `.sharpe` |
| `ic` | `periods` `mean_ic` `mean_rank_ic` `rank_ic_std` `rank_ic_t` `rank_ic_ir_annual` `rank_ic_hit_rate`；`deciles`（`mean_period_return` `ann_return`，鍵 1–10，10 = 分數最高；`top_minus_bottom_mean_period` `top_minus_bottom_t`）；`series[]`（`signal` `ic` `rank_ic` `n`） |
| `regimes.<label>` | `days` 與各組合的 `ann_return` `ann_vol` `sharpe`（以前一交易日 regime 分組） |
| `capacity` | `participation` `median_aum_usd` `min_aum_usd` `median_holding_adv_usd` |
| `monthly_returns.strategy` / `.spy` | `[{year, month, ret}]`（月報酬熱力圖） |
| `series` | `dates[]` 與等長陣列：`equity.<組合>`（含 `random_p05` `random_p50` `random_p95`，起點 = 1）、`drawdown.<組合>`、`rolling_sharpe.<組合>`（`rolling_window` 日，暖機期為 null） |

### 其他檔案

| 檔案 | 內容 |
|---|---|
| `report-YYYY-MM-DD.md` | 自動產生的 Markdown 報告（`make backtest` 另寫到 `docs/backtest-report.md`） |
| `holdings-<weekly\|monthly>.parquet` | 每次再平衡的持股：`signal_date` `trade_date` `ticker` `rank` `score` `weight` `regime` |
| `daily-<weekly\|monthly>.parquet` | 各組合每日報酬（扣成本後）：`date` `strategy` `spy` `sixty_forty` `equal_weight` |

## 前端發布 `web/public/data/`（`qrd publish` 產出，不提交）

所有檔案：`schema_version`（1.0）、`kind`、`asof`、`generated_at`（UTC ISO）、`disclaimer`。缺值為 `null`（不寫 0）。

| 檔案 | 主要欄位 |
|---|---|
| `manifest.json` | `demo`（恆為 false）、`files`、`assets[]`（ticker、file、in_top、asset_class、category、leverage）、`ranking_asof`、`backtest_asof`、`features_end`、`health`、`warnings[]`、`notes[]` |
| `manifest.health` | `status`（ok／degraded）、`status_rule`、`prices`（tickers、fresh、stale[ticker,last_bar]）、`ingest_runs[]`（最近 5 次：started_at、summary、problems_total、problems）、`quality_reports[]`（最近 5 份：issues、by_check、errors） |
| `rankings.json` | 與 `data/rankings/latest.json` 相同，`top[]` 另加 `prev_rank`（前一交易日名次或 null）、`sparkline`（最近 63 日調整後收盤）、`ret_1d`；另有 `group_labels`、`ranking_generated_at` |
| `changes.json` | `prev_asof`、`regime{prev,cur}`、`regime_changed`、`threshold`（5）、`entered[]`／`exited[]`／`movers[]`（ticker、rank、prev_rank、change＝昨名次−今名次、score_prev、score、reasons[]）、`unchanged` |
| `macro.json` | `dates`（最近 5 年，交易日曆）、`series{<series>: [...]}`（以 available_date 對齊）、`sources{<series>: description, source, is_proxy, last_obs, last_value, coverage}`、`curves[]`（今日／1 個月前／1 年前：tenor、value）、`regime{dates,label,stress_score,segments[regime,start,end,days]}` |
| `backtest.json` | `data/backtest/latest.json` 原樣複製 |
| `assets/<KEY>.json` | ticker、asset_class、category、leverage、`in_top`、`ranking`（Top 50 條目或 null）、`score`、`factors[]`（label、group、value、z、percentile＝今日合格池中的分位，已依因子方向調整）、`price{dates,close,ma50,ma200}`（調整後，最近 5 年）、`rank_history[]`（date、rank 或 null、source＝backtest_monthly／daily）、`backtest`（買進持有：available、start、end、years、shortened、metrics、benchmark_metrics（SPY）、series{dates,equity,drawdown,benchmark}（週頻）） |

# quant-rank-dashboard

每天自動從美股、美債、ETF 與衍生性金融產品（ETF/ETN 形式）中，依總體環境、市場行情與風險，選出並排名 Top 50 標的，並附上專業 Dashboard 與嚴謹的 3–5 年回測。

> **免責聲明**：本專案僅供研究與學習，不構成任何投資建議。回測結果不代表未來表現，且受存活者偏誤、資料品質與交易成本假設影響。

## 狀態

開發中（M1 資料層）。規格見 [`PLAN.md`](PLAN.md)，進度見 [`HANDOFF.md`](HANDOFF.md)。

## 快速開始

需要 Python 3.11+ 與 `make`。

```bash
make install   # 建立 .venv 並安裝套件與開發工具
make test      # pytest
make lint      # ruff check + ruff format --check + mypy --strict
```

選用：複製 `.env.example` 為 `.env` 並填入 `FRED_API_KEY`（沒有也能跑，會走備援來源）。

抓取資料（寫入 `data/`，不進 git）：

```bash
make ingest                                  # 全 universe 增量更新（價格 + 宏觀 + GDELT）
.venv/bin/qrd ingest --tickers SPY,TLT --no-sentiment   # 只抓部分標的
make features                                # 計算因子、宏觀面板與 regime（需先 ingest）
.venv/bin/qrd universe                       # 查看 universe 組成
```

資料來源、欄位與限制見 [`docs/data-dictionary.md`](docs/data-dictionary.md)。

## 文件導覽

| 檔案 | 用途 |
|---|---|
| `PLAN.md` | 目標、架構、排名方法、回測規格、Dashboard 規格、里程碑 |
| `CLAUDE.md` | Lead agent 的工作規則 |
| `AGENTS.md` | Lead 與 Reviewer 共用規則與審查清單 |
| `HANDOFF.md` | 進度交接與討論紀錄 |

## 如何用 agent 自動開發

1. 在本 repo 根目錄開一個 Lead（Claude Code），讓它讀 `CLAUDE.md`。
2. 開另一個 Reviewer agent，讓它讀 `AGENTS.md`。
3. 兩者依 `AGENTS.md` 的「討論流程」透過 `HANDOFF.md` 交接，每個里程碑最多 3 輪。
4. 看到 `HANDOFF.md` 的狀態是 `NEEDS_HUMAN` 時，回來處理「Needs human」清單。

建議給 Lead 的第一句話：

> 請閱讀 PLAN.md、CLAUDE.md、AGENTS.md、HANDOFF.md，從 M0 開始，依規則自動推進，遇到停止條件就停下並更新 HANDOFF.md。

## 授權

尚未指定。

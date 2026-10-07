# ADR 0001：Python 工具鏈與專案結構

- 狀態：已採用
- 日期：2026-10-06
- 里程碑：M0

## 背景

PLAN.md §3 指定 Python 3.11+、`uv` 或 `pip`、`pytest`、`ruff` + `mypy`，並要求本機能一行指令重跑。
開發機目前沒有安裝 `uv`；CI 使用 GitHub Actions。

## 選項

1. **`uv` + `uv.lock`**：快、可鎖版本；但需要使用者另外安裝 `uv`，且開發機目前沒有。
2. **標準 `venv` + `pip` + `pyproject.toml`（hatchling）**：零額外安裝，CI 與本機行為一致；沒有鎖檔。
3. Poetry / PDM：額外工具，對本專案沒有明顯好處。

## 結論

採用選項 2。`Makefile` 是唯一入口（`make install / test / lint / format / daily`），
建立 `.venv` 後一律以 `.venv/bin/python -m <tool>` 執行，避免使用到系統工具。

- 套件採 `src/` layout（`src/qrd/`），避免測試意外 import 到未安裝的原始碼。
- `mypy --strict` 涵蓋 `src` 與 `tests`；`ruff` 同時負責 lint 與 format。
- CI 矩陣：Python 3.11（最低支援）與 3.12。

## 取捨與後續

- 沒有鎖檔 → 可重現性較弱。M1 引入 pandas / pyarrow / duckdb 等主要依賴時，
  會設下限版本，並評估加入 `requirements.lock`（`pip freeze` 產生）或改用 `uv`，屆時另寫 ADR。
- 前端（`web/`）的 Node 工具鏈在 M5 建立；開發機目前沒有 Node，前端建置以 CI 為準。

> 僅供研究與學習，不構成投資建議。

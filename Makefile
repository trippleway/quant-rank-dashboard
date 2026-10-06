# quant-rank-dashboard — local + CI entry points.
# Usage: make install && make test && make lint

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
# Lint/format only project code; scripts/ holds external orchestration tooling.
LINT_PATHS := src tests

.PHONY: help install test lint format ingest features rank backtest publish daily clean

help:
	@echo "install  建立 $(VENV) 並安裝套件與開發工具"
	@echo "test     執行 pytest"
	@echo "lint     ruff check + ruff format --check + mypy"
	@echo "format   ruff 自動修正與格式化"
	@echo "ingest   抓取/增量更新價格、宏觀與 GDELT 資料到 data/"
	@echo "features 由 data/ 計算因子、宏觀面板與 regime"
	@echo "rank     由特徵計算分數並選出 Top 50（輸出 data/rankings/）"
	@echo "backtest walk-forward 回測（輸出 data/backtest/ 與 docs/backtest-report.md）"
	@echo "publish  輸出前端用的靜態 JSON（web/public/data/）"
	@echo "daily    執行每日 pipeline（M6 實作）"

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip

install: $(BIN)/python
	$(BIN)/python -m pip install -e ".[dev]"

test: $(BIN)/python
	$(BIN)/python -m pytest

lint: $(BIN)/python
	$(BIN)/python -m ruff check $(LINT_PATHS)
	$(BIN)/python -m ruff format --check $(LINT_PATHS)
	$(BIN)/python -m mypy

format: $(BIN)/python
	$(BIN)/python -m ruff check --fix $(LINT_PATHS)
	$(BIN)/python -m ruff format $(LINT_PATHS)

ingest: $(BIN)/python
	$(BIN)/qrd ingest

features: $(BIN)/python
	$(BIN)/qrd features

rank: $(BIN)/python
	$(BIN)/qrd rank

backtest: $(BIN)/python
	$(BIN)/qrd backtest --report docs/backtest-report.md

publish: $(BIN)/python
	$(BIN)/qrd publish

daily: $(BIN)/python
	$(BIN)/qrd daily

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist

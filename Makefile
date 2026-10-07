# quant-rank-dashboard — local + CI entry points.
# Usage: make install && make test && make lint

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
# Lint/format only project code; scripts/ holds external orchestration tooling.
LINT_PATHS := src tests
# Frontend: use a project-local Node in .tools/node if present (gitignored), else PATH.
NODE_DIR := $(wildcard $(CURDIR)/.tools/node/bin)
NPM := $(if $(NODE_DIR),PATH="$(NODE_DIR):$$PATH" npm,npm)
WEB := --prefix web

.PHONY: help install test lint format ingest features rank backtest publish daily clean \
	web-install web-lint web-test web-build web-check web-screenshots web-dev

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
	@echo "daily    每日 pipeline：ingest → features → rank →（到期）backtest → publish"
	@echo "web-install / web-lint / web-test / web-build  前端（web/，需要 Node 20+）"
	@echo "web-check 以 headless Chrome 檢查 build 後的七個頁面（需先 publish + web-build）"
	@echo "web-screenshots 同 web-check，並更新 README 用的 docs/screenshots/*.webp"
	@echo "web-dev  前端開發伺服器（讀 web/public/data/）"

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

web-install:
	$(NPM) $(WEB) ci

web-lint:
	$(NPM) $(WEB) run lint

web-test:
	$(NPM) $(WEB) test

web-build:
	$(NPM) $(WEB) run build

web-check:
	$(NPM) $(WEB) run check:site

web-screenshots:
	$(NPM) $(WEB) run screenshots

web-dev:
	$(NPM) $(WEB) run dev

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist

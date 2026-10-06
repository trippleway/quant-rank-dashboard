# quant-rank-dashboard — local + CI entry points.
# Usage: make install && make test && make lint

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin

.PHONY: help install test lint format daily clean

help:
	@echo "install  建立 $(VENV) 並安裝套件與開發工具"
	@echo "test     執行 pytest"
	@echo "lint     ruff check + ruff format --check + mypy"
	@echo "format   ruff 自動修正與格式化"
	@echo "daily    執行每日 pipeline（M1–M4 實作）"

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip

install: $(BIN)/python
	$(BIN)/python -m pip install -e ".[dev]"

test: $(BIN)/python
	$(BIN)/python -m pytest

lint: $(BIN)/python
	$(BIN)/python -m ruff check .
	$(BIN)/python -m ruff format --check .
	$(BIN)/python -m mypy

format: $(BIN)/python
	$(BIN)/python -m ruff check --fix .
	$(BIN)/python -m ruff format .

daily: $(BIN)/python
	$(BIN)/qrd daily

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist

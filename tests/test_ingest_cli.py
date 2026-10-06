"""End-to-end ingest wiring with fake sources, CLI behaviour, and opt-in network tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qrd.cli import EXIT_LOW_COVERAGE, main
from qrd.config import Settings, load_settings
from qrd.ingest import pipeline
from qrd.ingest.pipeline import IngestSummary, PriceUpdate, run_ingest
from qrd.ingest.resilience import RunLog, Status
from qrd.universe import load_universe
from tests.helpers import FakePriceSource, make_bars

NOW = datetime(2024, 12, 31, 22, 0, tzinfo=UTC)


def test_run_ingest_writes_log_and_quality_report(tmp_path: Path) -> None:
    uni = load_universe()
    uni = uni[uni["ticker"].isin(["AAPL", "TLT", "TQQQ"])]
    data = {t: make_bars(t, periods=260, seed=i) for i, t in enumerate(["SPY", "AAPL", "TLT"])}
    settings = Settings(data_dir=tmp_path, fred_api_key=None)

    summary = run_ingest(
        settings,
        uni,
        now=NOW,
        price_sources=[FakePriceSource("p", data)],
        include_macro=False,
        include_sentiment=False,
    )

    report = summary.to_dict()
    assert report["tickers"] == 4  # 3 + SPY added as the calendar reference
    assert summary.prices.statuses["TQQQ"] == Status.FAILED
    assert report["price_coverage"] == 0.75
    log = json.loads(Path(summary.log_path).read_text())
    assert log["summary"]["prices"]["failed"] == 1
    assert Path(summary.quality_path).is_file()


def test_load_settings_reads_dotenv_without_overriding_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("FRED_API_KEY='from-file'\nQRD_DATA_DIR=/tmp/x\n")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("QRD_DATA_DIR", raising=False)
    assert load_settings(dotenv=env).fred_api_key == "from-file"
    monkeypatch.setenv("FRED_API_KEY", "from-env")
    s = load_settings(dotenv=env)
    assert s.fred_api_key == "from-env"
    assert s.data_dir == Path("/tmp/x")


def test_cli_universe(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["universe"]) == 0
    out = capsys.readouterr().out
    assert "universe:" in out
    assert "Not investment advice" in out


def test_cli_ingest_rejects_unknown_ticker(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ingest", "--tickers", "NOT_A_TICKER"]) == 1
    assert "not in universe" in capsys.readouterr().err


@pytest.mark.parametrize(("coverage_ok", "code"), [(True, 0), (False, EXIT_LOW_COVERAGE)])
def test_cli_ingest_exit_code_follows_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coverage_ok: bool, code: int
) -> None:
    def fake_run(settings: Settings, uni: object, **kwargs: object) -> IngestSummary:
        prices = PriceUpdate(
            statuses={"A": Status.OK, "B": Status.OK if coverage_ok else Status.FAILED}
        )
        return IngestSummary(prices, RunLog(), "log.json", "quality.json")

    monkeypatch.setattr(pipeline, "run_ingest", fake_run)
    args = ["ingest", "--data-dir", str(tmp_path), "--limit", "2", "--min-coverage", "0.9"]
    assert main(args) == code


@pytest.mark.network
def test_network_live_fetch_small_subset(tmp_path: Path) -> None:
    """Real yfinance + FRED CSV round trip; run with QRD_RUN_NETWORK=1."""
    uni = load_universe()
    uni = uni[uni["ticker"].isin(["AAPL", "TLT", "GLD"])]
    summary = run_ingest(Settings(tmp_path, None), uni, include_sentiment=False)
    assert summary.prices.coverage() == 1.0
    assert summary.run_log.counts("macro")["failed"] == 0

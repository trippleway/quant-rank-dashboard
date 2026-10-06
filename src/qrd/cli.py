"""Command-line entry point: ``qrd <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from qrd import DISCLAIMER, __version__

# Exit code when ingest finished but too few tickers have any data to be useful.
EXIT_LOW_COVERAGE = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qrd", description="quant-rank-dashboard pipeline")
    parser.add_argument("--version", action="version", version=f"qrd {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print version and disclaimer")
    sub.add_parser("daily", help="run the full daily pipeline (ingest → publish)")
    sub.add_parser("universe", help="print universe composition by asset class")

    ingest = sub.add_parser("ingest", help="fetch/update prices, macro and sentiment data")
    ingest.add_argument(
        "--data-dir", type=Path, default=None, help="default: $QRD_DATA_DIR or data/"
    )
    ingest.add_argument("--full", action="store_true", help="ignore cache and refetch full history")
    ingest.add_argument("--limit", type=int, default=None, help="only the first N tickers (debug)")
    ingest.add_argument("--tickers", default=None, help="comma-separated subset of the universe")
    ingest.add_argument("--no-macro", action="store_true", help="skip macro series")
    ingest.add_argument("--no-sentiment", action="store_true", help="skip GDELT tone")
    ingest.add_argument(
        "--min-coverage",
        type=float,
        default=0.9,
        help="exit 2 if the share of tickers with any data falls below this",
    )

    feats = sub.add_parser("features", help="compute factors, macro panel and regime from data/")
    feats.add_argument(
        "--data-dir", type=Path, default=None, help="default: $QRD_DATA_DIR or data/"
    )
    feats.add_argument(
        "--asof",
        default=None,
        help="YYYY-MM-DD: only use bars dated and macro data available on or before this day",
    )

    rank = sub.add_parser("rank", help="score the universe and select the Top 50 from features")
    rank.add_argument("--data-dir", type=Path, default=None, help="default: $QRD_DATA_DIR or data/")
    rank.add_argument(
        "--asof",
        default=None,
        help="YYYY-MM-DD: rank on this day (default: last day with features)",
    )

    bt = sub.add_parser("backtest", help="walk-forward backtest of the ranking (PLAN §5)")
    bt.add_argument("--data-dir", type=Path, default=None, help="default: $QRD_DATA_DIR or data/")
    bt.add_argument("--years", type=float, default=5.0, help="requested length (default 5)")
    bt.add_argument("--start", default=None, help="YYYY-MM-DD (overrides --years)")
    bt.add_argument("--end", default=None, help="YYYY-MM-DD (default: last session with data)")
    bt.add_argument("--sims", type=int, default=1000, help="random-portfolio simulations")
    bt.add_argument("--seed", type=int, default=42, help="seed for the random benchmark")
    bt.add_argument(
        "--no-robustness", action="store_true", help="skip sensitivity sweep and ablation"
    )
    bt.add_argument(
        "--report", type=Path, default=None, help="also write the Markdown report to this path"
    )
    pub = sub.add_parser("publish", help="write versioned static JSON for the web frontend")
    pub.add_argument("--data-dir", type=Path, default=None, help="default: $QRD_DATA_DIR or data/")
    pub.add_argument(
        "--out", type=Path, default=Path("web/public/data"), help="default: web/public/data"
    )
    return parser


def _cmd_publish(args: argparse.Namespace) -> int:
    from qrd.config import load_settings  # noqa: PLC0415
    from qrd.publish import run_publish  # noqa: PLC0415

    settings = load_settings(args.data_dir)
    try:
        summary = run_publish(settings, args.out)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(DISCLAIMER)
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    import pandas as pd  # noqa: PLC0415

    from qrd.backtest.report import run_stored_backtest  # noqa: PLC0415
    from qrd.backtest.run import BacktestConfig  # noqa: PLC0415
    from qrd.config import load_settings  # noqa: PLC0415

    settings = load_settings(args.data_dir)
    cfg = BacktestConfig(
        years=args.years,
        start=pd.Timestamp(args.start) if args.start else None,
        end=pd.Timestamp(args.end) if args.end else None,
        n_random=args.sims,
        seed=args.seed,
        robustness=not args.no_robustness,
    )
    try:
        summary = run_stored_backtest(settings, cfg, args.report)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("historical simulation, not expected returns; read the bias disclosures in the report")
    print(DISCLAIMER)
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    import pandas as pd  # noqa: PLC0415

    from qrd.config import load_settings  # noqa: PLC0415
    from qrd.scoring.rank import run_rank  # noqa: PLC0415

    settings = load_settings(args.data_dir)
    asof = pd.Timestamp(args.asof) if args.asof else None
    try:
        summary = run_rank(settings, asof=asof)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("regime inputs are proxies for macro / geopolitical conditions, not measurements")
    print(DISCLAIMER)
    return 0


def _cmd_features(args: argparse.Namespace) -> int:
    import pandas as pd  # noqa: PLC0415

    from qrd.config import load_settings  # noqa: PLC0415
    from qrd.features.build import run_features  # noqa: PLC0415
    from qrd.universe import load_universe  # noqa: PLC0415

    settings = load_settings(args.data_dir)
    asof = pd.Timestamp(args.asof) if args.asof else None
    try:
        summary = run_features(settings, load_universe(), asof=asof)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary.to_dict(), indent=2))
    print("regime inputs are proxies for macro / geopolitical conditions, not measurements")
    print(DISCLAIMER)
    return 0


def _cmd_universe() -> int:
    from qrd.universe import load_universe  # noqa: PLC0415 — keep `qrd version` import-light

    uni = load_universe()
    print(f"universe: {len(uni)} tickers")
    print(uni.groupby("asset_class").size().to_string())
    print(f"leveraged/inverse: {int(uni['leveraged_or_inverse'].sum())}")
    print(DISCLAIMER)
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    from qrd.config import load_settings  # noqa: PLC0415
    from qrd.ingest.pipeline import run_ingest  # noqa: PLC0415
    from qrd.universe import load_universe  # noqa: PLC0415

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # failures are logged by us
    settings = load_settings(args.data_dir)
    uni = load_universe()
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        unknown = wanted - set(uni["ticker"])
        if unknown:
            print(f"not in universe: {sorted(unknown)}", file=sys.stderr)
            return 1
        uni = uni[uni["ticker"].isin(wanted)]
    if args.limit is not None:
        uni = uni.head(args.limit)

    summary = run_ingest(
        settings,
        uni,
        full=args.full,
        include_macro=not args.no_macro,
        include_sentiment=not args.no_sentiment,
    )
    report = summary.to_dict()
    print(json.dumps(report, indent=2))
    print(DISCLAIMER)
    if summary.prices.coverage() < args.min_coverage:
        print(
            f"price coverage {summary.prices.coverage():.1%} below {args.min_coverage:.0%}",
            file=sys.stderr,
        )
        return EXIT_LOW_COVERAGE
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "version":
        print(f"qrd {__version__}")
        print(DISCLAIMER)
        return 0
    commands: dict[str, Callable[[], int]] = {
        "universe": _cmd_universe,
        "ingest": lambda: _cmd_ingest(args),
        "features": lambda: _cmd_features(args),
        "rank": lambda: _cmd_rank(args),
        "backtest": lambda: _cmd_backtest(args),
        "publish": lambda: _cmd_publish(args),
    }
    if args.command in commands:
        return commands[args.command]()
    if args.command == "daily":
        # Fail loudly rather than pretend success until the pipeline exists (M2–M4).
        print(
            "daily pipeline is not implemented yet (ingest exists: `qrd ingest`; "
            "features: `qrd features`; ranking: `qrd rank`; backtest: `qrd backtest`; "
            "publish: `qrd publish`; scheduling planned for M6)",
            file=sys.stderr,
        )
        return 1
    raise AssertionError(f"unhandled command: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())

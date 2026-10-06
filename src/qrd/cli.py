"""Command-line entry point: ``qrd <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
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
    return parser


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
    if args.command == "universe":
        return _cmd_universe()
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "daily":
        # Fail loudly rather than pretend success until the pipeline exists (M2–M4).
        print(
            "daily pipeline is not implemented yet (ingest exists: `qrd ingest`; "
            "features/scoring/publish planned for M2–M4)",
            file=sys.stderr,
        )
        return 1
    raise AssertionError(f"unhandled command: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())

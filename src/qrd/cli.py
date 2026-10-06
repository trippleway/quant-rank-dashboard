"""Command-line entry point: ``qrd <command>``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from qrd import DISCLAIMER, __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qrd", description="quant-rank-dashboard pipeline")
    parser.add_argument("--version", action="version", version=f"qrd {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print version and disclaimer")
    sub.add_parser("daily", help="run the full daily pipeline (ingest → publish)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "version":
        print(f"qrd {__version__}")
        print(DISCLAIMER)
        return 0
    if args.command == "daily":
        # Fail loudly rather than pretend success until the pipeline exists (M1–M4).
        print("daily pipeline is not implemented yet (planned for M1–M4)", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())

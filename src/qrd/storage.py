"""Parquet storage (one file per ticker / series) plus DuckDB views for querying.

Layout under ``data/``::

    prices/<KEY>.parquet      daily bars, one file per ticker
    macro/<series>.parquet    macro series (observation + availability dates)
    sentiment/<name>.parquet  GDELT tone series

Writes are atomic (temp file + ``os.replace``) so a crash mid-run never leaves a
half-written cache behind.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import duckdb
import pandas as pd

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def file_key(name: str) -> str:
    """Filesystem-safe, reversible-enough key (``^VIX`` → ``_5EVIX``, ``BRK-B`` → ``BRK-B``)."""
    return _UNSAFE.sub(lambda m: f"_{ord(m.group()):02X}", name)


class ParquetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, kind: str, name: str) -> Path:
        return self.root / kind / f"{file_key(name)}.parquet"

    def read(self, kind: str, name: str) -> pd.DataFrame | None:
        path = self._path(kind, name)
        if not path.is_file():
            return None
        return pd.read_parquet(path)

    def write(self, kind: str, name: str, df: pd.DataFrame) -> Path:
        path = self._path(kind, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
        return path

    def keys(self, kind: str) -> list[Path]:
        folder = self.root / kind
        return sorted(folder.glob("*.parquet")) if folder.is_dir() else []

    def connect(self) -> duckdb.DuckDBPyConnection:
        """In-memory DuckDB connection with one view per dataset that has files."""
        con = duckdb.connect()
        for kind in ("prices", "macro", "sentiment"):
            if self.keys(kind):
                pattern = str(self.root / kind / "*.parquet").replace("'", "''")
                con.execute(
                    f"CREATE VIEW {kind} AS "
                    f"SELECT * FROM read_parquet('{pattern}', union_by_name = true)"
                )
        return con

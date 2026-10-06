"""Runtime configuration: data paths and environment variables.

Everything that touches the filesystem or credentials goes through here so tests can
point the pipeline at a temporary directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_DIR = Path("data")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    fred_api_key: str | None

    @property
    def prices_dir(self) -> Path:
        return self.data_dir / "prices"

    @property
    def macro_dir(self) -> Path:
        return self.data_dir / "macro"

    @property
    def sentiment_dir(self) -> Path:
        return self.data_dir / "sentiment"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def quality_dir(self) -> Path:
        return self.data_dir / "quality"

    @property
    def rankings_dir(self) -> Path:
        return self.data_dir / "rankings"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Minimal ``.env`` reader (KEY=VALUE lines); real env vars take precedence."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_settings(data_dir: Path | None = None, dotenv: Path = Path(".env")) -> Settings:
    env = {**_read_dotenv(dotenv), **os.environ}
    resolved = data_dir or Path(env.get("QRD_DATA_DIR") or DEFAULT_DATA_DIR)
    key = env.get("FRED_API_KEY") or None
    return Settings(data_dir=resolved, fred_api_key=key)

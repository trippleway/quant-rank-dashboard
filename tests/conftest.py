"""pytest hooks: network tests are opt-in."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("QRD_RUN_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set QRD_RUN_NETWORK=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)

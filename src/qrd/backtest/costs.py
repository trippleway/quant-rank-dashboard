"""Transaction cost model: one-way cost (commission + spread + slippage) in basis points.

Tiered by the trailing 60-session average dollar volume known on the signal date (no
look-ahead), higher for leveraged / inverse products and volatility ETPs. Defaults sit in
PLAN §5's 5–10 bps one-way range for ordinary products; the multiplier scales all costs
for the sensitivity sweep. Rationale: docs/adr/0005-backtest-engine.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    # (minimum ADV in USD, one-way bps), checked from the top; unknown ADV → last tier
    tiers: tuple[tuple[float, float], ...] = (
        (100_000_000.0, 5.0),
        (20_000_000.0, 7.5),
        (0.0, 10.0),
    )
    complex_multiplier: float = 2.0  # leverage != 1 or volatility ETP
    multiplier: float = 1.0  # global scale (sensitivity sweep)

    def bps(self, adv_usd: pd.Series, leverage: pd.Series, asset_class: pd.Series) -> pd.Series:
        adv = adv_usd.astype(float).to_numpy()
        out = np.full(len(adv), self.tiers[-1][1])
        for floor, bps in reversed(self.tiers):
            out = np.where(np.isfinite(adv) & (adv >= floor), bps, out)
        complex_ = (leverage.astype(float).to_numpy() != 1) | (
            asset_class.astype(str).to_numpy() == "volatility_etp"
        )
        out = np.where(complex_, out * self.complex_multiplier, out)
        return pd.Series(out * self.multiplier, index=adv_usd.index)

    def describe(self) -> dict[str, object]:
        return {
            "tiers_bps": [{"min_adv_usd": f, "bps": b} for f, b in self.tiers],
            "complex_multiplier": self.complex_multiplier,
            "multiplier": self.multiplier,
        }

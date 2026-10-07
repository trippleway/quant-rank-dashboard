"""Scoring configuration: factor specs, regime weights, penalties and Top 50 constraints.

All numbers here are subjective defaults chosen for interpretability, not fitted to
returns (no optimisation on backtest results). Rationale: docs/adr/0004-ranking-engine.md;
the full method is described in docs/methodology.md. M4 runs sensitivity sweeps on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from qrd.features.regime import NEUTRAL, RISK_OFF, RISK_ON, UNKNOWN

Transform = Literal["none", "abs", "log", "log1p"]

MOMENTUM = "momentum"
LOW_RISK = "low_risk"
LIQUIDITY = "liquidity"
YIELD = "yield"
DURATION = "duration"
GROUPS = (MOMENTUM, LOW_RISK, LIQUIDITY, YIELD, DURATION)


@dataclass(frozen=True)
class FactorSpec:
    column: str  # column in features/factors.parquet
    group: str
    sign: int  # +1: higher (after transform) is better; -1: lower is better
    label: str  # short Traditional Chinese label for the UI
    transform: Transform = "none"
    asset_classes: frozenset[str] | None = None  # None = applies to every asset class


BOND = frozenset({"bond_etf"})

FACTOR_SPECS: tuple[FactorSpec, ...] = (
    FactorSpec("mom_12_1", MOMENTUM, +1, "12-1 月動能"),
    FactorSpec("mom_6m", MOMENTUM, +1, "6 月動能"),
    FactorSpec("mom_3m", MOMENTUM, +1, "3 月動能"),
    FactorSpec("trend_200", MOMENTUM, +1, "200 日均線趨勢"),
    FactorSpec("vol_63", LOW_RISK, -1, "低波動"),
    FactorSpec("downside_63", LOW_RISK, -1, "低下行偏差"),
    FactorSpec("max_dd_252", LOW_RISK, +1, "回撤較淺"),
    FactorSpec("beta_252", LOW_RISK, -1, "低 |beta|", transform="abs"),
    FactorSpec("adv_usd_60", LIQUIDITY, +1, "成交額高", transform="log"),
    FactorSpec("amihud_60", LIQUIDITY, -1, "衝擊成本低", transform="log1p"),
    FactorSpec("trailing_yield_252", YIELD, +1, "配息率"),
    FactorSpec("rate_duration", DURATION, +1, "存續期", asset_classes=BOND),
)


def _weights(w: dict[str, float]) -> MappingProxyType[str, float]:
    unknown = set(w) - set(GROUPS)
    if unknown:
        raise ValueError(f"unknown factor groups: {sorted(unknown)}")
    return MappingProxyType({g: w.get(g, 0.0) for g in GROUPS})


# Group weights per regime. Duration is a *signed* tilt for bond ETFs only: long duration
# is favoured in risk-off (flight to quality) and disfavoured in risk-on. `unknown` uses
# neutral weights (ADR 0003).
DEFAULT_REGIME_WEIGHTS: MappingProxyType[str, MappingProxyType[str, float]] = MappingProxyType(
    {
        RISK_ON: _weights(
            {MOMENTUM: 0.50, LOW_RISK: 0.20, LIQUIDITY: 0.10, YIELD: 0.10, DURATION: -0.10}
        ),
        NEUTRAL: _weights({MOMENTUM: 0.40, LOW_RISK: 0.30, LIQUIDITY: 0.10, YIELD: 0.15}),
        RISK_OFF: _weights(
            {MOMENTUM: 0.25, LOW_RISK: 0.45, LIQUIDITY: 0.10, YIELD: 0.10, DURATION: 0.10}
        ),
    }
)


@dataclass(frozen=True)
class NormalizationConfig:
    lower_pct: float = 0.05  # winsorize tails before z-scoring
    upper_pct: float = 0.95
    min_group_size: int = 5  # smaller asset-class groups use the pooled z-score only
    group_blend: float = 0.5  # z = blend * within-class z + (1 - blend) * pooled z


@dataclass(frozen=True)
class PenaltyConfig:
    per_extra_leverage: float = 0.25  # × (|leverage| − 1) when |leverage| > 1
    inverse: float = 0.25
    volatility_etp: float = 0.50
    high_vol_threshold: float = 0.40  # annualised vol_63
    high_vol_slope: float = 0.50  # × (vol / threshold − 1)
    high_vol_cap: float = 1.00
    short_history: float = 0.25


@dataclass(frozen=True)
class SelectionConfig:
    top_n: int = 50
    asset_class_caps: MappingProxyType[str, int] = field(
        default_factory=lambda: MappingProxyType(
            {
                "equity": 30,
                "equity_etf": 20,
                "bond_etf": 15,
                "commodity_etf": 10,
                "currency_etf": 5,
                "volatility_etp": 2,
            }
        )
    )
    category_cap: int = 8  # per (asset_class, category), e.g. equity/information_technology
    leveraged_cap: int = 5  # leveraged or inverse products (leverage != 1)
    max_correlation: float = 0.95  # skip near-duplicates of an already selected ticker
    corr_window: int = 126  # sessions of daily returns for the correlation check
    corr_min_periods: int = 60
    concentration_penalty: float = 0.04  # per already-selected ticker in the same category


@dataclass(frozen=True)
class ScoringConfig:
    factors: tuple[FactorSpec, ...] = FACTOR_SPECS
    regime_weights: MappingProxyType[str, MappingProxyType[str, float]] = field(
        default_factory=lambda: DEFAULT_REGIME_WEIGHTS
    )
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    penalties: PenaltyConfig = field(default_factory=PenaltyConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    min_coverage: float = 0.6  # share of applicable group weight with data
    # Backtest ranking only: drop tickers with < 1 year of history instead of penalising
    # them (PLAN §5 — they may enter the daily list, flagged, but not the backtest list).
    exclude_short_history: bool = False

    def weights_for(self, regime: str) -> MappingProxyType[str, float]:
        if regime == UNKNOWN or regime not in self.regime_weights:
            return self.regime_weights[NEUTRAL]
        return self.regime_weights[regime]

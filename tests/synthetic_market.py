"""Shared SYNTHETIC FIXTURE market for look-ahead tests (ranking and backtest).

Prices and macro observations here are generated, never real, and are only used inside
pytest's temporary data. Includes a near-duplicate (VOO ≈ 1.5 × SPY), a ticker that
stops trading early (S11), leveraged/inverse products and lagged macro releases.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qrd.features.regime import RegimeComponent, RegimeConfig
from tests.helpers import make_bars

N = 420
START = "2022-01-03"
UNIVERSE = [
    ("SPY", "equity_etf", "broad_us", 1),
    ("VOO", "equity_etf", "broad_us", 1),
    ("QQQ", "equity_etf", "broad_us", 1),
    ("SSO", "equity_etf", "broad_us", 2),
    ("SH", "equity_etf", "broad_us", -1),
    ("HYG", "bond_etf", "corporate_hy", 1),
    ("IEF", "bond_etf", "treasury_intermediate", 1),
    ("TLT", "bond_etf", "treasury_long", 1),
    ("SHY", "bond_etf", "treasury_short", 1),
    ("AGG", "bond_etf", "aggregate", 1),
    ("TBT", "bond_etf", "treasury_long", -2),
    ("GLD", "commodity_etf", "precious_metals", 1),
    ("USO", "commodity_etf", "energy", 1),
    ("UUP", "currency_etf", "usd", 1),
    ("VIXY", "volatility_etp", "vix_futures", 1),
    *[
        (f"S{i:02d}", "equity", "information_technology" if i < 6 else "financials", 1)
        for i in range(12)
    ],
]
MACRO = {"vix": 1, "hy_oas": 1, "curve_10y2y": 1, "ust_10y": 1, "usd_broad": 7, "wti": 7}
REGIME_CFG = RegimeConfig(
    components=tuple(
        RegimeComponent(name, d, 1.0, min_periods=40)
        for name, d in [
            ("vix", 1),
            ("hy_oas", 1),
            ("credit_proxy", -1),
            ("spy_trend", -1),
            ("curve", -1),
            ("usd_mom", 1),
            ("oil_mom", 1),
        ]
    ),
    pct_window=200,
)


def universe() -> pd.DataFrame:
    return pd.DataFrame(
        [(*row, "etf") for row in UNIVERSE],
        columns=["ticker", "asset_class", "category", "leverage", "instrument"],
    )


def prices() -> pd.DataFrame:
    frames = []
    for i, (t, *_rest) in enumerate(UNIVERSE):
        df = make_bars(t, start=START, periods=N, seed=i + 100, price=20 + 5 * i)
        if t == "VOO":  # near-duplicate of SPY → exercised by correlation de-dup
            spy = make_bars("SPY", start=START, periods=N, seed=100, price=20)
            df[["open", "high", "low", "close", "adj_close"]] = (
                spy[["open", "high", "low", "close", "adj_close"]].to_numpy() * 1.5
            )
        if t == "S11":  # stops trading early → stale on later cutoffs
            df = df.iloc[:330]
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def observations() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    frames = []
    for series, lag in MACRO.items():
        dates = pd.bdate_range(START, periods=N + 10)
        values = 30 + np.cumsum(rng.normal(0, 1, len(dates)))
        frames.append(
            pd.DataFrame(
                {
                    "obs_date": dates,
                    "available_date": dates + pd.offsets.BDay(lag),
                    "series": series,
                    "value": values,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def day(pos: int) -> pd.Timestamp:
    return pd.bdate_range(START, periods=N)[pos]

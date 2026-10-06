"""Universe construction and liquidity filtering.

The candidate list is a static, versioned seed file (``seeds.csv``) so runs are
reproducible. It is a *current* snapshot, which introduces survivorship bias in
backtests — disclosed in docs/adr/0002-data-sources-and-storage.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import pandas as pd

ASSET_CLASSES = frozenset(
    {"equity", "equity_etf", "bond_etf", "commodity_etf", "currency_etf", "volatility_etp"}
)
INSTRUMENTS = frozenset({"stock", "etf", "etn"})
UNIVERSE_COLUMNS = ["ticker", "asset_class", "category", "leverage", "instrument"]


def load_universe() -> pd.DataFrame:
    """Load and validate the packaged seed universe."""
    with resources.files("qrd.universe").joinpath("seeds.csv").open("r", encoding="utf-8") as fh:
        df = pd.read_csv(fh, comment="#")
    validate_universe(df)
    df["leveraged_or_inverse"] = df["leverage"] != 1
    return df.reset_index(drop=True)


def validate_universe(df: pd.DataFrame) -> None:
    missing = set(UNIVERSE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"universe missing columns: {sorted(missing)}")
    dups = df.loc[df["ticker"].duplicated(), "ticker"].tolist()
    if dups:
        raise ValueError(f"duplicate tickers in universe: {dups}")
    bad_cls = set(df["asset_class"]) - ASSET_CLASSES
    if bad_cls:
        raise ValueError(f"unknown asset classes: {sorted(bad_cls)}")
    bad_inst = set(df["instrument"]) - INSTRUMENTS
    if bad_inst:
        raise ValueError(f"unknown instruments: {sorted(bad_inst)}")
    if (df["leverage"] == 0).any():
        raise ValueError("leverage must be non-zero")
    stocks_with_leverage = df[(df["instrument"] == "stock") & (df["leverage"] != 1)]
    if not stocks_with_leverage.empty:
        raise ValueError("single stocks cannot carry a leverage factor")


@dataclass(frozen=True)
class LiquidityRules:
    adv_window: int = 60  # sessions for average daily dollar volume
    min_adv_usd: float = 5_000_000.0
    min_price: float = 5.0
    min_history_sessions: int = 60  # enough for the ADV window; longer history is a confidence flag


def liquidity_filter(
    prices: pd.DataFrame, asof: pd.Timestamp, rules: LiquidityRules | None = None
) -> pd.DataFrame:
    """Evaluate the liquidity screen for each ticker using only bars dated ``<= asof``.

    ``prices`` is long-format canonical bars. Returns one row per ticker with the screen
    inputs, ``eligible`` and a human-readable ``reason`` for exclusions.
    """
    r = rules or LiquidityRules()
    cols = ["ticker", "sessions", "last_close", "adv_usd", "eligible", "reason"]
    hist = prices[prices["date"] <= asof]  # no look-ahead: nothing after asof is visible
    if hist.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for ticker, group in hist.sort_values("date").groupby("ticker", sort=True):
        g = group.dropna(subset=["close"])
        sessions = len(g)
        last_close = float(g["close"].iloc[-1]) if sessions else float("nan")
        tail = g.tail(r.adv_window)
        adv = float((tail["close"] * tail["volume"]).mean()) if sessions else float("nan")
        reasons = []
        if sessions < r.min_history_sessions:
            reasons.append(f"history {sessions} < {r.min_history_sessions} sessions")
        if not last_close >= r.min_price:
            reasons.append(f"price {last_close:.2f} < {r.min_price:.2f}")
        if not adv >= r.min_adv_usd:
            reasons.append(f"ADV ${adv:,.0f} < ${r.min_adv_usd:,.0f}")
        rows.append((ticker, sessions, last_close, adv, not reasons, "; ".join(reasons)))
    return pd.DataFrame(rows, columns=cols)

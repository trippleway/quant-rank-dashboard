"""Universe seed list validity and the liquidity screen (incl. a no-look-ahead test)."""

from __future__ import annotations

import pandas as pd
import pytest

from qrd.universe import (
    ASSET_CLASSES,
    LiquidityRules,
    liquidity_filter,
    load_universe,
    validate_universe,
)
from tests.helpers import make_bars


def test_universe_has_at_least_300_unique_tickers() -> None:
    uni = load_universe()
    assert len(uni) >= 300
    assert uni["ticker"].is_unique
    assert set(uni["asset_class"]) <= ASSET_CLASSES


def test_universe_covers_all_asset_classes_and_flags_leverage() -> None:
    uni = load_universe()
    assert set(uni["asset_class"]) == ASSET_CLASSES
    flagged = set(uni.loc[uni["leveraged_or_inverse"], "ticker"])
    assert {"TQQQ", "SQQQ", "TMF", "UVXY", "SH"} <= flagged
    assert "SPY" not in flagged
    # Treasury ETFs required by PLAN.md §2
    assert {"SHY", "IEI", "IEF", "TLT", "TIP", "BND"} <= set(uni["ticker"])


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"ticker": "SPY"}, "duplicate"),
        ({"ticker": "ZZZ", "asset_class": "crypto"}, "asset classes"),
        ({"ticker": "ZZZ", "instrument": "future"}, "instruments"),
        ({"ticker": "ZZZ", "instrument": "stock", "leverage": 2}, "single stocks"),
    ],
)
def test_validate_universe_rejects_bad_rows(row: dict[str, object], message: str) -> None:
    uni = load_universe().drop(columns="leveraged_or_inverse")
    base = {"asset_class": "equity", "category": "x", "leverage": 1, "instrument": "stock"}
    bad = pd.concat([uni, pd.DataFrame([{**base, **row}])], ignore_index=True)
    with pytest.raises(ValueError, match=message):
        validate_universe(bad)


def _prices() -> pd.DataFrame:
    liquid = make_bars("LIQ", periods=120, price=50, volume=1_000_000)  # ~$50M/day
    thin = make_bars("THIN", periods=120, price=50, volume=10_000)  # ~$0.5M/day
    cheap = make_bars("PENNY", periods=120, price=2, volume=50_000_000)
    young = make_bars("YOUNG", start="2024-05-01", periods=30, price=50, volume=1_000_000)
    return pd.concat([liquid, thin, cheap, young], ignore_index=True)


def test_liquidity_filter_reasons() -> None:
    prices = _prices()
    out = liquidity_filter(prices, prices["date"].max()).set_index("ticker")
    assert bool(out.loc["LIQ", "eligible"])
    assert "ADV" in str(out.at["THIN", "reason"])
    assert "price" in str(out.at["PENNY", "reason"])
    assert "history" in str(out.at["YOUNG", "reason"])


def test_liquidity_filter_ignores_future_bars() -> None:
    """Truncating everything after ``asof`` must not change the result (no look-ahead)."""
    prices = _prices()
    asof = pd.Timestamp("2024-04-15")
    with_future = liquidity_filter(prices, asof)
    truncated = liquidity_filter(prices[prices["date"] <= asof], asof)
    pd.testing.assert_frame_equal(with_future, truncated)

    # And future data that would flip the decision really is ignored.
    boosted = prices.copy()
    boosted.loc[(boosted["ticker"] == "THIN") & (boosted["date"] > asof), "volume"] = 1e9
    assert liquidity_filter(boosted, asof).equals(with_future)


def test_liquidity_rules_are_configurable() -> None:
    prices = _prices()
    loose = LiquidityRules(min_adv_usd=100_000, min_price=1, min_history_sessions=20)
    out = liquidity_filter(prices, prices["date"].max(), loose)
    assert bool(out["eligible"].all())

"""Top N constraints: caps, leverage cap, correlation de-dup, concentration penalty.

All candidates are SYNTHETIC FIXTURE rows built in this file.
"""

from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

from qrd.scoring.config import SelectionConfig
from qrd.scoring.select import return_correlations, select_top
from tests.helpers import make_bars

Row = tuple[str, str, str, float, float]


def scored(rows: list[Row]) -> pd.DataFrame:
    """rows: (ticker, asset_class, category, leverage, score)."""
    return pd.DataFrame(rows, columns=["ticker", "asset_class", "category", "leverage", "score"])


def many(
    n: int, cls: str, cat: str, start: float, *, lev: float = 1.0, prefix: str = "X"
) -> list[Row]:
    return [(f"{prefix}{i:03d}", cls, cat, lev, start - i * 0.01) for i in range(n)]


def test_ranks_contiguous_and_ordered_by_adjusted_score() -> None:
    rows = many(30, "equity", "a", 2.0, prefix="A") + many(30, "equity", "b", 1.9, prefix="B")
    cfg = SelectionConfig(top_n=10, category_cap=50, concentration_penalty=0.0)
    sel = select_top(scored(rows), None, cfg).selected
    assert sel["rank"].tolist() == list(range(1, 11))
    assert sel["adjusted_score"].is_monotonic_decreasing


def test_never_more_than_top_n_and_nan_scores_excluded() -> None:
    rows = many(80, "equity", "a", 2.0)
    df = scored(rows)
    df.loc[0, "score"] = np.nan  # ineligible (e.g. low coverage)
    sel = select_top(df, None, SelectionConfig(category_cap=100, asset_class_caps=_caps(100)))
    assert len(sel.selected) == 50
    assert "X000" not in set(sel.selected["ticker"])


def _caps(n: int) -> MappingProxyType[str, int]:
    return MappingProxyType(dict.fromkeys(["equity", "equity_etf", "bond_etf"], n))


def test_asset_class_cap() -> None:
    rows = many(60, "equity", "a", 3.0, prefix="E") + many(30, "bond_etf", "t", 1.0, prefix="B")
    cfg = SelectionConfig(category_cap=100)
    res = select_top(scored(rows), None, cfg)
    counts = res.selected["asset_class"].value_counts()
    assert counts["equity"] == cfg.asset_class_caps["equity"] == 30
    assert counts["bond_etf"] == cfg.asset_class_caps["bond_etf"] == 15
    assert len(res.selected) == 45  # caps bind: fewer than 50 is reported, not padded
    assert res.skipped["reason"].str.startswith("asset_class cap").any()


def test_category_cap() -> None:
    rows = many(20, "equity", "tech", 3.0, prefix="T") + many(20, "equity", "util", 1.0, prefix="U")
    cfg = SelectionConfig(top_n=20, category_cap=8, concentration_penalty=0.0)
    res = select_top(scored(rows), None, cfg)
    assert res.selected["category"].value_counts().to_dict() == {"tech": 8, "util": 8}
    assert (res.skipped["reason"] == "category cap equity/tech (8)").sum() == 12


def test_category_cap_is_per_asset_class() -> None:
    rows = many(10, "equity", "energy", 3.0, prefix="E") + many(
        10, "commodity_etf", "energy", 2.9, prefix="C"
    )
    res = select_top(scored(rows), None, SelectionConfig(top_n=16, category_cap=8))
    assert res.selected.groupby("asset_class").size().to_dict() == {
        "commodity_etf": 8,
        "equity": 8,
    }


def test_leveraged_cap_counts_inverse_too() -> None:
    rows = (
        many(4, "equity_etf", "broad_us", 5.0, lev=3.0, prefix="L")
        + many(4, "equity_etf", "broad_us", 4.9, lev=-1.0, prefix="I")
        + many(20, "equity", "a", 1.0, prefix="P")
    )
    cfg = SelectionConfig(top_n=20, leveraged_cap=5, category_cap=100)
    sel = select_top(scored(rows), None, cfg).selected
    assert (sel["leverage"] != 1).sum() == 5
    assert (sel["leverage"] < 0).sum() == 1  # 4 × 3x first, then one inverse, then capped


def test_correlated_duplicates_are_skipped() -> None:
    rows = [
        ("SPY", "equity_etf", "broad_us", 1.0, 2.0),
        ("VOO", "equity_etf", "broad_us", 1.0, 1.99),
        ("IEF", "bond_etf", "t", 1.0, 1.5),
    ]
    tickers = ["SPY", "VOO", "IEF"]
    corr = pd.DataFrame(
        [[1.0, 0.999, -0.2], [0.999, 1.0, -0.2], [-0.2, -0.2, 1.0]], index=tickers, columns=tickers
    )
    res = select_top(scored(rows), corr, SelectionConfig())
    assert res.selected["ticker"].tolist() == ["SPY", "IEF"]
    reason = str(res.skipped.set_index("ticker").at["VOO", "reason"])
    assert reason.startswith("correlation 0.999 with SPY")


def test_concentration_penalty_diversifies() -> None:
    # 3rd tech name (2.00 − 2×0.1 = 1.80) loses to the best utility (1.85)
    rows = [
        ("T1", "equity", "tech", 1.0, 2.10),
        ("T2", "equity", "tech", 1.0, 2.05),
        ("T3", "equity", "tech", 1.0, 2.00),
        ("U1", "equity", "util", 1.0, 1.85),
    ]
    cfg = SelectionConfig(top_n=3, concentration_penalty=0.1)
    sel = select_top(scored(rows), None, cfg).selected
    assert sel["ticker"].tolist() == ["T1", "T2", "U1"]
    assert sel["concentration_penalty"].tolist() == pytest.approx([0.0, 0.1, 0.0])
    no_pen = select_top(scored(rows), None, SelectionConfig(top_n=3, concentration_penalty=0.0))
    assert no_pen.selected["ticker"].tolist() == ["T1", "T2", "T3"]


def test_ties_break_by_ticker_deterministically() -> None:
    rows = [("B", "equity", "a", 1.0, 1.0), ("A", "equity", "b", 1.0, 1.0)]
    sel = select_top(scored(rows), None, SelectionConfig(top_n=2)).selected
    assert sel["ticker"].tolist() == ["A", "B"]


def test_return_correlations_use_only_past_bars() -> None:
    a = make_bars("AAA", periods=200, seed=1)
    b = a.assign(ticker="BBB")  # identical history → correlation 1
    c = make_bars("CCC", periods=200, seed=2)
    prices = pd.concat([a, b, c], ignore_index=True)
    asof = a["date"].iloc[150]
    cfg = SelectionConfig()
    corr = return_correlations(prices, ["AAA", "BBB", "CCC"], asof, cfg)
    assert float(corr["BBB"].loc["AAA"]) == pytest.approx(1.0)
    assert abs(float(corr["CCC"].loc["AAA"])) < 0.5
    future = prices["date"] > asof
    prices.loc[future & (prices["ticker"] == "BBB"), "adj_close"] *= np.linspace(
        0.5, 2, int((future & (prices["ticker"] == "BBB")).sum())
    )
    again = return_correlations(prices, ["AAA", "BBB", "CCC"], asof, cfg)
    pd.testing.assert_frame_equal(corr, again)

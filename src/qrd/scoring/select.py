"""Top N selection under constraints (greedy, deterministic).

At each step every remaining candidate's ``adjusted`` score is its ``score`` minus a
concentration penalty (``concentration_penalty`` × tickers already selected in the same
asset_class/category). The best candidate that passes all hard constraints is taken:

* asset-class cap (``asset_class_caps``)
* category cap (per asset_class/category)
* leveraged/inverse cap (``leverage != 1``, so −1x inverse ETFs count too)
* correlation de-duplication: trailing daily-return correlation with an already selected
  ticker above ``max_correlation`` (e.g. SPY / VOO / IVV) → skipped as a duplicate

Caps and selected sets only grow, so a candidate that fails a constraint can never pass
later; it is dropped with a recorded reason. Ties break by ticker for reproducibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qrd.features.factors import price_for_returns
from qrd.scoring.config import SelectionConfig


@dataclass
class Selection:
    selected: pd.DataFrame  # scored rows + rank, concentration_penalty, adjusted_score
    skipped: pd.DataFrame  # ticker, score, reason — candidates removed by a constraint


def daily_returns_wide(prices: pd.DataFrame, tickers: list[str] | None = None) -> pd.DataFrame:
    """Date x ticker daily returns, each ticker's return computed between its own bars."""
    bars = prices if tickers is None else prices[prices["ticker"].isin(tickers)]
    bars = bars.sort_values(["ticker", "date"])
    px = price_for_returns(bars)
    rets = bars.assign(ret=px / px.groupby(bars["ticker"], sort=False).shift(1) - 1)
    wide = rets.pivot_table(index="date", columns="ticker", values="ret", aggfunc="last")
    return wide.sort_index()


def correlations_from_returns(
    wide: pd.DataFrame, tickers: list[str], asof: pd.Timestamp, cfg: SelectionConfig
) -> pd.DataFrame:
    """Pairwise correlation over the last ``corr_window`` sessions <= asof of ``tickers``."""
    cols = [t for t in tickers if t in wide.columns]
    sub = wide.loc[wide.index <= asof, cols].dropna(how="all").tail(cfg.corr_window)
    corr = sub.corr(min_periods=cfg.corr_min_periods)
    return corr.reindex(index=tickers, columns=tickers)


def return_correlations(
    prices: pd.DataFrame, tickers: list[str], asof: pd.Timestamp, cfg: SelectionConfig
) -> pd.DataFrame:
    """Pairwise correlation of daily returns over the last ``corr_window`` sessions <= asof."""
    bars = prices[(prices["date"] <= asof) & prices["ticker"].isin(tickers)]
    if bars.empty:
        return pd.DataFrame(index=tickers, columns=tickers, dtype=float)
    return correlations_from_returns(daily_returns_wide(bars), tickers, asof, cfg)


@dataclass
class _Book:
    """Running state of the greedy selection."""

    cfg: SelectionConfig
    corr: pd.DataFrame | None
    tickers: list[str] = field(default_factory=list)
    class_n: dict[str, int] = field(default_factory=dict)
    cat_n: dict[str, int] = field(default_factory=dict)
    lev_n: int = 0

    def violation(self, row: pd.Series) -> str:
        c = self.cfg
        cls, cat = str(row["asset_class"]), str(row["cat_key"])
        cap = c.asset_class_caps.get(cls, c.top_n)
        if self.class_n.get(cls, 0) >= cap:
            return f"asset_class cap {cls} ({cap})"
        if self.cat_n.get(cat, 0) >= c.category_cap:
            return f"category cap {cat} ({c.category_cap})"
        if float(row["leverage"]) != 1 and self.lev_n >= c.leveraged_cap:
            return f"leveraged/inverse cap ({c.leveraged_cap})"
        ticker = str(row["ticker"])
        if self.corr is not None and ticker in self.corr.index:
            for other in self.tickers:
                rho = float(self.corr[other].loc[ticker]) if other in self.corr.columns else np.nan
                if np.isfinite(rho) and rho > c.max_correlation:
                    return f"correlation {rho:.3f} with {other} > {c.max_correlation}"
        return ""

    def add(self, row: pd.Series) -> None:
        cls, cat = str(row["asset_class"]), str(row["cat_key"])
        self.tickers.append(str(row["ticker"]))
        self.class_n[cls] = self.class_n.get(cls, 0) + 1
        self.cat_n[cat] = self.cat_n.get(cat, 0) + 1
        self.lev_n += int(float(row["leverage"]) != 1)


def select_top(
    scored: pd.DataFrame, corr: pd.DataFrame | None, cfg: SelectionConfig | None = None
) -> Selection:
    """Greedy constrained selection of eligible rows (``score`` not NaN)."""
    c = cfg or SelectionConfig()
    pool = scored[scored["score"].notna()].sort_values("ticker").reset_index(drop=True)
    pool["cat_key"] = pool["asset_class"].astype(str) + "/" + pool["category"].astype(str)
    book = _Book(c, corr)
    tickers = pool["ticker"].astype(str).to_numpy()
    scores = pool["score"].to_numpy(dtype=float)
    cat_keys = pool["cat_key"].to_numpy()
    alive = np.ones(len(pool), dtype=bool)
    chosen: list[tuple[int, float, float]] = []  # (row, concentration penalty, adjusted)
    skipped: list[tuple[str, float, str]] = []

    while alive.any() and len(chosen) < c.top_n:
        conc = c.concentration_penalty * np.array(
            [float(book.cat_n.get(k, 0)) for k in cat_keys], dtype=float
        )
        adjusted = scores - conc
        idx = np.flatnonzero(alive)
        order = idx[np.lexsort((tickers[idx], -adjusted[idx]))]  # best first, ties by ticker
        for i in order:
            row = pool.loc[i]
            reason = book.violation(row)
            alive[i] = False
            if reason:
                skipped.append((str(row["ticker"]), float(row["score"]), reason))
                continue
            chosen.append((int(i), float(conc[i]), float(adjusted[i])))
            book.add(row)
            break

    sel = pool.loc[[i for i, _, _ in chosen]].copy()
    sel["concentration_penalty"] = [p for _, p, _ in chosen]
    sel["adjusted_score"] = [a for _, _, a in chosen]
    sel.insert(0, "rank", np.arange(1, len(sel) + 1))
    sel = sel.drop(columns="cat_key").reset_index(drop=True)
    skip = pd.DataFrame(skipped, columns=["ticker", "score", "reason"])
    return Selection(sel, skip)

"""Point-in-time macro / sentiment panel on the trading calendar.

Input rows follow the M1 schema (``obs_date``, ``available_date``, ``series``, ``value``).
For trading day ``t`` the panel holds, per series, the latest observation whose
``available_date <= t`` — never anything joined on ``obs_date``. Observations older than
``max_age_days`` (calendar days, measured on ``obs_date``) are treated as missing so a
dead source shows up as NaN instead of a silently frozen value.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

# Weekly series (H.10 USD, EIA WTI) published with a 7-business-day lag are up to ~17
# calendar days old just before the next release; 21 leaves room for holidays.
DEFAULT_MAX_AGE_DAYS = 21


def _series_asof(obs: pd.DataFrame, calendar: pd.DatetimeIndex, max_age_days: int) -> pd.Series:
    rows = obs.dropna(subset=["value"]).sort_values(["available_date", "obs_date"])
    # A row is only "news" if it is newer than everything already published.
    rows = rows[rows["obs_date"] >= rows["obs_date"].cummax()]
    rows = rows.drop_duplicates("available_date", keep="last")
    left = pd.DataFrame({"date": calendar.astype("datetime64[ns]")})
    right = pd.DataFrame(
        {
            "available_date": rows["available_date"].to_numpy(dtype="datetime64[ns]"),
            "obs_date": rows["obs_date"].to_numpy(dtype="datetime64[ns]"),
            "value": rows["value"].astype(float).to_numpy(),
        }
    )
    merged = pd.merge_asof(
        left, right, left_on="date", right_on="available_date", direction="backward"
    )
    age = (merged["date"] - merged["obs_date"]).dt.days
    values = merged["value"].where(age <= max_age_days)
    return pd.Series(values.to_numpy(dtype=float), index=calendar)


def macro_panel(
    observations: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    series: Sequence[str] = (),
) -> pd.DataFrame:
    """Wide panel indexed by ``calendar`` with one column per series.

    ``series`` lists columns that must exist even without any observation yet (all NaN),
    so the panel's shape does not depend on how much history is available.
    """
    cal = pd.DatetimeIndex(calendar).sort_values().unique()
    cal.name = "date"
    groups = dict(iter(observations.groupby("series", sort=True)))
    names = sorted(set(series) | {str(k) for k in groups})
    cols = {
        name: (
            _series_asof(groups[name], cal, max_age_days)
            if name in groups
            else pd.Series(np.nan, index=cal)
        )
        for name in names
    }
    return pd.DataFrame(cols, index=cal, dtype=np.float64)

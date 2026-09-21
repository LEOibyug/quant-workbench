"""Forward-only distribution return index for signals, never execution prices."""

import numpy as np
import pandas as pd


def forward_index(parent_close, distributions):
    """Chain (parent close + distributed value)/previous raw close on ex dates.

    This index assumes theoretical reinvestment at the distribution-date close.
    It is not a cash or holdings ledger and excludes unprovided corporate actions.
    """
    if parent_close.index.has_duplicates or not parent_close.index.is_monotonic_increasing:
        raise ValueError("Unique ordered parent sessions required")
    if (
        parent_close.empty
        or not np.isfinite(parent_close.to_numpy()).all()
        or (parent_close <= 0).any()
    ):
        raise ValueError("Positive finite parent closes required")
    dates = list(parent_close.index)
    p = parent_close.to_numpy(dtype=float)
    values = np.zeros(len(p))
    seen = set()
    for event in distributions:
        day = event["day"]
        if day > dates[-1]:
            continue
        if day < dates[0]:
            continue
        if day not in parent_close.index or day == dates[0]:
            raise ValueError("Distribution requires event session and preceding parent close")
        if event["id"] in seen:
            raise ValueError("Duplicate distribution")
        seen.add(event["id"])
        ratio = event["numerator"] / event["denominator"]
        price = event["child_close"]
        if not event["verified"] or not np.isfinite([ratio, price]).all() or min(ratio, price) <= 0:
            raise ValueError("Verified ratio and positive same-session child close required")
        if event["child_price_day"] != day:
            raise ValueError("Child price must be from the distribution session")
        values[dates.index(day)] += ratio * price
    gross = np.r_[1.0, (p[1:] + values[1:]) / p[:-1]]
    return pd.Series(
        p[0] * np.cumprod(gross), index=parent_close.index, name="distribution_return_index"
    )

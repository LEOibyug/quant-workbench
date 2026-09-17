"""Transparent model/rule fusion, independent of training and portfolio state."""

import math


def risk_overlay(probability, expected_bps, cost_bps):
    """Size a cost-screened rule opportunity; weak model evidence is not a hard veto.

    The return is a fraction of the rule risk budget, not portfolio leverage.
    Strong adverse evidence still blocks entry. No forced minimum trade frequency.
    """
    values = (probability, expected_bps, cost_bps)
    if any(value is None or not math.isfinite(value) for value in values) or cost_bps < 0:
        return False, 0.0
    if not 0 <= probability <= 1:
        return False, 0.0
    allow = not (probability < 0.45 and expected_bps < 0) and expected_bps > -cost_bps
    confidence = min(1.0, max(0.0, (probability - 0.45) / 0.15))
    edge = min(1.0, max(0.0, expected_bps / max(cost_bps, 1)))
    return allow, 0.25 + 0.5 * confidence + 0.25 * edge

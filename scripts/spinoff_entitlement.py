"""Exact research entitlement accounting; fractional claims are not spendable cash."""

from dataclasses import dataclass
from fractions import Fraction
from math import isfinite


@dataclass(frozen=True)
class Entitlement:
    whole_shares: int
    fractional_claim: Fraction


def allocate(parent_shares: int, numerator: int, denominator: int) -> Entitlement:
    if any(type(x) is not int for x in (parent_shares, numerator, denominator)):
        raise TypeError("Shares and ratio terms must be integers")
    if parent_shares < 0 or numerator <= 0 or denominator <= 0:
        raise ValueError("Long-only nonnegative holdings and positive ratio required")
    total = Fraction(parent_shares * numerator, denominator)
    whole = total.numerator // total.denominator
    return Entitlement(whole, total - whole)


def mark(entitlement: Entitlement, child_price: float):
    if not isfinite(child_price) or child_price <= 0:
        raise ValueError("Positive finite child mark required")
    return dict(
        whole_share_value=entitlement.whole_shares * child_price,
        fractional_receivable_value=float(entitlement.fractional_claim) * child_price,
        cash_credit=0.0,
    )

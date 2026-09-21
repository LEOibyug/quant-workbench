"""Research-only corporate entitlement subledger, independent of trading targets."""

from dataclasses import dataclass, field
from fractions import Fraction
from math import isfinite

from spinoff_entitlement import allocate


@dataclass
class DistributionLedger:
    child_shares: dict[str, int] = field(default_factory=dict)
    fractional_claims: dict[str, tuple[str, Fraction]] = field(default_factory=dict)
    applied_events: set[str] = field(default_factory=set)
    settled_claims: set[str] = field(default_factory=set)
    cash: float = 0.0

    def apply(self, event_id, child, eligible_parent_shares, numerator, denominator):
        if event_id in self.applied_events:
            raise ValueError("Distribution already applied")
        entitlement = allocate(eligible_parent_shares, numerator, denominator)
        self.child_shares[child] = self.child_shares.get(child, 0) + entitlement.whole_shares
        if entitlement.fractional_claim:
            self.fractional_claims[event_id] = (child, entitlement.fractional_claim)
        self.applied_events.add(event_id)

    def settle_fraction(self, event_id, actual_net_cash):
        if event_id in self.settled_claims or event_id not in self.fractional_claims:
            raise ValueError("No unsettled fractional claim")
        if not isfinite(actual_net_cash) or actual_net_cash < 0:
            raise ValueError("Invalid confirmed net proceeds")
        del self.fractional_claims[event_id]
        self.cash += actual_net_cash
        self.settled_claims.add(event_id)

    def value(self, marks):
        symbols = set(self.child_shares) | {s for s, _ in self.fractional_claims.values()}
        if any(s not in marks or not isfinite(marks[s]) or marks[s] <= 0 for s in symbols):
            raise ValueError("Missing or invalid mark")
        return (
            self.cash
            + sum(n * marks[s] for s, n in self.child_shares.items())
            + sum(float(n) * marks[s] for s, n in self.fractional_claims.values())
        )

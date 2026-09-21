"""Atomic pre-open research state transition; economic basis, not tax accounting."""

from dataclasses import dataclass, field
from math import isfinite

from spinoff_entitlement import allocate


@dataclass
class DistributionState:
    child_shares: dict[str, int] = field(default_factory=dict)
    fractional_claims: dict[str, float] = field(default_factory=dict)
    child_cost: dict[str, float] = field(default_factory=dict)
    applied: set[str] = field(default_factory=set)

    def apply_before_risk(self, event, parent_shares, parent_basis, parent_open, child_open):
        """Return new parent per-share economic basis without mutating caller state.

        Proportional current opening fair-value allocation conserves total cost.
        Entitlements remain side assets, never cash or new strategy targets.
        """
        event_id = event["id"]
        child = event["child"]
        if event_id in self.applied:
            raise ValueError("Duplicate distribution event")
        if not event["verified"]:
            raise ValueError("Unverified distribution")
        if any(not isfinite(v) or v <= 0 for v in (parent_open, child_open)):
            raise ValueError("Both contemporaneous opening marks required")
        if not isfinite(parent_basis) or parent_basis < 0:
            raise ValueError("Invalid parent basis")
        e = allocate(parent_shares, event["numerator"], event["denominator"])
        ratio = event["numerator"] / event["denominator"]
        before_cost = parent_shares * parent_basis
        parent_fraction = parent_open / (parent_open + ratio * child_open)
        new_basis = parent_basis * parent_fraction if parent_shares else 0.0
        transferred = before_cost - parent_shares * new_basis
        # All checks precede mutations: failure cannot partly credit the account.
        self.child_shares[child] = self.child_shares.get(child, 0) + e.whole_shares
        self.fractional_claims[child] = self.fractional_claims.get(child, 0) + float(
            e.fractional_claim
        )
        self.child_cost[child] = self.child_cost.get(child, 0) + transferred
        self.applied.add(event_id)
        return dict(
            parent_basis=new_basis,
            transferred_cost=transferred,
            whole_child_shares=e.whole_shares,
            fractional_child_claim=float(e.fractional_claim),
            cash_change=0.0,
            parent_shares=parent_shares,
        )

    def mark(self, prices):
        total = 0.0
        for child, whole in self.child_shares.items():
            quantity = whole + self.fractional_claims[child]
            if quantity == 0:
                continue
            if child not in prices or not isfinite(prices[child]) or prices[child] <= 0:
                raise ValueError("Missing child mark")
            total += quantity * prices[child]
        return dict(market_value=total, unrealized_pnl=total - sum(self.child_cost.values()))

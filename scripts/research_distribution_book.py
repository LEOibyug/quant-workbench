"""Research adapter: hold distributed assets, never use receivables as cash."""

import copy

from spinoff_transition import DistributionState


class ResearchDistributionBook:
    def __init__(self, events, marks):
        self.events = copy.deepcopy(events)
        if len({e["id"] for e in events}) != len(events):
            raise ValueError("Duplicate event ids")
        self.marks = marks
        self.states = {}
        self.started = False
        self.audit = []

    def start(self, symbols, start, end):
        if self.started:
            raise ValueError("Distribution book cannot be reused across simulations")
        for e in self.events:
            if not e["verified"] or e["parent"] not in symbols or e["child"] in symbols:
                raise ValueError("Verified parent event and separate side asset required")
        self.started = True
        self.active_events = [e for e in self.events if start <= e["day"] < end]

    def before_open(self, day, prices, shares, basis):
        changed = []
        pending = [e for e in self.active_events if e["day"] == day]
        # Validate all required child quotes before mutating any event state.
        marks = self.marks.at(day, [e["child"] for e in pending if shares[e["parent"]] > 0], "open")
        for event in pending:
            parent = event["parent"]
            quantity = shares[parent]
            if not quantity:
                self.audit.append(dict(id=event["id"], day=day, parent=parent, parent_shares=0))
                continue
            state = self.states.setdefault(parent, DistributionState())
            transition = state.apply_before_risk(
                event,
                quantity,
                basis[parent],
                float(prices.loc[parent, "open"]),
                marks[event["child"]],
            )
            basis[parent] = transition["parent_basis"]
            changed.append(parent)
            self.audit.append(dict(id=event["id"], day=day, parent=parent, **transition))
        return changed

    def mark(self, day, field):
        by_parent = {}
        unrealized = 0.0
        assets = {}
        for parent, state in self.states.items():
            symbols = [
                s for s, n in state.child_shares.items() if n + state.fractional_claims[s] > 0
            ]
            marks = self.marks.at(day, symbols, field)
            value = state.mark(marks)
            by_parent[parent] = value["market_value"]
            unrealized += value["unrealized_pnl"]
            for s in symbols:
                assets[parent + ":" + s] = dict(
                    parent=parent,
                    symbol=s,
                    shares=state.child_shares[s],
                    fractional_receivable=state.fractional_claims[s],
                    mark=marks[s],
                    cost=state.child_cost[s],
                )
        return dict(
            market_value=sum(by_parent.values()),
            unrealized_pnl=unrealized,
            by_parent=by_parent,
            assets=assets,
        )

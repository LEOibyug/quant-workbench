"""Ordinary USD cash entitlements for research; requires separately verified events.

Gross distributions only: no tax model, short positions, special distributions,
due bills, foreign currencies, or inferred historical data availability.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from numbers import Integral


def money(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Nonfinite dividend amount")
    return result


class CashDividendBook:
    def __init__(self, events, *, source_rate_scenario=False):
        self.source_rate_scenario = source_rate_scenario
        self.events = deepcopy(events)
        ids, economic_keys = set(), set()
        for e in self.events:
            if not e.get("id") or not e.get("symbol") or not e.get("evidence"):
                raise ValueError("Event identity and evidence required")
            if source_rate_scenario:
                if (
                    e.get("verified") is not False
                    or e.get("currency") not in (None, "USD")
                    or e.get("scenario_assumption") != "USD gross source rate"
                ):
                    raise ValueError("Explicit unverified source-rate scenario required")
            elif e.get("verified") is not True or e.get("currency") != "USD":
                raise ValueError("Verified USD event required")
            if e.get("kind") != "ordinary_cash" or e.get("amount_basis") != "gross":
                raise ValueError("Only ordinary gross cash distributions supported")
            if any(
                e.get(k) for k in ("foreign", "special", "due_bill_on_date", "due_bill_off_date")
            ):
                raise ValueError("Special entitlement rules require a separate adapter")
            ex, pay = date.fromisoformat(e["ex_date"]), date.fromisoformat(e["payable_date"])
            if pay < ex or money(e["rate"]) <= 0:
                raise ValueError("Invalid ordinary dividend dates or rate")
            key = (e["symbol"], e["ex_date"])
            if e["id"] in ids or key in economic_keys:
                raise ValueError("Duplicate or ambiguous same-day entitlement")
            ids.add(e["id"])
            economic_keys.add(key)
        self.claims = {}
        self.audit = []
        self.last_day = None
        self.open_day = None
        self.total_earned = Decimal(0)
        self.total_paid = Decimal(0)

    def start(self, symbols, days):
        if self.last_day is not None or self.open_day is not None or self.claims:
            raise ValueError("Dividend book cannot be reused")
        if getattr(self, "started", False):
            raise ValueError("Dividend book cannot be reused")
        for event in self.events:
            if event["symbol"] not in symbols or event["ex_date"] not in days:
                raise ValueError("Event requires an included security and ex-date session")
        self.started = True

    def snapshot(self):
        by_symbol = {}
        for claim in self.claims.values():
            entry = by_symbol.setdefault(
                claim["symbol"], dict(income=0.0, paid=0.0, receivable=0.0)
            )
            amount = float(claim["amount"])
            entry["income"] += amount
            entry["paid" if claim["paid"] else "receivable"] += amount
        return dict(
            data_status=(
                "unverified_source_rate_scenario"
                if self.source_rate_scenario
                else "caller_verified_events"
            ),
            income=float(self.total_earned),
            paid=float(self.total_paid),
            receivable=float(self.receivable),
            by_symbol=by_symbol,
        )

    @property
    def receivable(self):
        return sum((c["amount"] for c in self.claims.values() if not c["paid"]), Decimal(0))

    def before_open(self, day, prior_close_shares):
        """Call before that day's trades, using the actual preceding closing holdings."""
        date.fromisoformat(day)
        if self.open_day is not None or (self.last_day is not None and day <= self.last_day):
            raise ValueError("Sessions must advance; each opening must have one closing")
        if self.last_day is not None and any(
            self.last_day < e["ex_date"] < day for e in self.events
        ):
            raise ValueError("An ex-date was skipped; holdings snapshot unavailable")
        if self.last_day is None and any(e["ex_date"] < day for e in self.events):
            raise ValueError(
                "Past ex-dates require explicit opening claims; do not silently omit them"
            )
        pending = [e for e in self.events if e["ex_date"] == day]
        # Validate every relevant snapshot before changing any claim.
        for e in pending:
            n = prior_close_shares.get(e["symbol"])
            if isinstance(n, bool) or not isinstance(n, Integral) or n < 0:
                raise ValueError("Explicit nonnegative integer preceding holdings required")
        for e in pending:
            n = int(prior_close_shares[e["symbol"]])
            amount = money(e["rate"]) * n
            self.claims[e["id"]] = dict(
                symbol=e["symbol"], amount=amount, payable_date=e["payable_date"], paid=False
            )
            self.total_earned += amount
            self.audit.append(
                dict(id=e["id"], day=day, action="recognize", shares=n, amount=str(amount))
            )
        self.open_day = day
        return self.receivable

    def after_close(self, day):
        """Return a once-only cash credit, usable starting the next session.

        Payment at session close is a conservative timing convention; weekend
        payments transfer at the first subsequent session close. It is not a
        claim about a broker's actual intraday crediting time.
        """
        if day != self.open_day:
            raise ValueError("Must close the currently opened session exactly once")
        credit = Decimal(0)
        for event_id, claim in self.claims.items():
            if not claim["paid"] and claim["payable_date"] <= day:
                claim["paid"] = True
                credit += claim["amount"]
                self.audit.append(
                    dict(id=event_id, day=day, action="pay", amount=str(claim["amount"]))
                )
        self.total_paid += credit
        self.last_day, self.open_day = day, None
        assert self.total_earned == self.total_paid + self.receivable
        return credit

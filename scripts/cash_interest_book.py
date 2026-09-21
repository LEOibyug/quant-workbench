"""Explicit lagged-rate research scenario, crediting prior close cash at next open."""
import math
from datetime import date


class CashInterestBook:
    def __init__(self, rates, haircut=0):
        self.rates = sorted(rates.items())
        if not self.rates or not math.isfinite(haircut) or haircut < 0:
            raise ValueError('Invalid cash rate scenario')
        for day, rate in self.rates:
            date.fromisoformat(day)
            if not math.isfinite(rate): raise ValueError('Nonfinite cash rate')
        self.haircut = haircut
        self.started = False
        self.income = 0.
        self.audit = []

    def start(self, days):
        if self.started or not days or days != sorted(set(days)):
            raise ValueError('Book reused or invalid calendar')
        self.days = list(days)
        self.index = 0
        self.started = True
        # Fail before executing trades if any interval lacks a past rate.
        if len(days)>1 and not any(d < days[0] for d,_ in self.rates):
            raise ValueError('Missing lagged rate')

    def before_open(self, day, cash):
        if not self.started or self.index >= len(self.days) or day != self.days[self.index]:
            raise ValueError('Missing or repeated cash credit day')
        if not math.isfinite(cash) or cash < 0:raise ValueError('Invalid cash balance')
        credit=0.
        if self.index:
            previous=self.days[self.index-1]
            rate_day,rate=next((d,r) for d,r in reversed(self.rates) if d < previous)
            elapsed=(date.fromisoformat(day)-date.fromisoformat(previous)).days
            credit=cash*max(0,rate-self.haircut)/100*elapsed/360
            self.audit.append(dict(day=day,previous_close=previous,effective_date=rate_day,rate_percent=rate,calendar_days=elapsed,cash_basis=cash,credit=credit))
            self.income+=credit
        self.index+=1
        return credit

    def snapshot(self):
        return dict(income=self.income,scenario='lagged SOFR proxy; not broker yield',haircut_percentage_points=self.haircut)

"""Causal constrained entropic updates; research targets, not realized wealth."""
import numpy as np
from sklearn.covariance import LedoitWolf
from cash_interest_book import CashInterestBook


def project(z):
    z = np.asarray(z, dtype=float)
    if z.ndim != 1 or len(z) < 2 or not np.isfinite(z).all() or (z <= 0).any():
        raise ValueError('Expected positive finite stock and cash weights')
    z = z / z.max()
    lower = np.zeros(len(z)); lower[-1] = .05
    upper = np.full(len(z), .2); upper[-1] = 1.
    lo, hi = 0., 1.
    while np.clip(hi*z, lower, upper).sum() < 1:
        hi *= 2
    for _ in range(100):
        mid = (lo+hi)/2
        if np.clip(mid*z, lower, upper).sum() < 1: lo = mid
        else: hi = mid
    return np.clip((lo+hi)/2*z, lower, upper)


def update(weights, relatives):
    x = np.asarray(relatives, dtype=float)
    if x.shape != weights.shape or not np.isfinite(x).all() or (x <= 0).any():
        raise ValueError('Invalid price relatives')
    gradient = x / (weights @ x)
    return project(weights*np.exp(gradient-gradient.max()))


def forecasts(frame, rates, start):
    p = frame.pivot(index='day', columns='symbol', values='close').sort_index().sort_index(axis=1)
    if not np.isfinite(p.to_numpy()).all() or (p <= 0).any().any():
        raise ValueError('Incomplete or invalid common prices')
    days = list(p.index); n = len(p.columns)
    initial = np.full(n+1, min(.2, .95/n)); initial[-1] = 1-initial[:-1].sum()
    first = next(i for i,d in enumerate(days) if d >= start)-1
    if first < 63: raise ValueError('Insufficient warmup')
    cash = 1.; index = []; book = CashInterestBook(rates); book.start(days)
    for day in days:
        cash += book.before_open(day, cash); index.append(cash)
    returns = np.diff(np.log(p.to_numpy()), axis=0)
    prices = p.to_numpy(); weights = initial.copy()
    maps = {'eg': {}, 'fixed': {}}; audit = []
    for i in range(first, len(p)):
        if i > first:
            x = np.r_[prices[i]/prices[i-1], index[i]/index[i-1]]
            weights = update(weights, x)
        cov = LedoitWolf().fit(returns[i-63:i]).covariance_ + np.eye(n)*1e-12
        vol = np.sqrt(np.diag(cov))
        for method, raw in [('eg', weights), ('fixed', initial)]:
            w = raw[:-1]*min(1., .1/max(np.sqrt(raw[:-1]@cov@raw[:-1]*252), 1e-12))
            assert (w >= 0).all() and w.max() <= .2+1e-12 and w.sum() <= .95+1e-12
            for j, symbol in enumerate(p.columns):
                maps[method][str(days[i]), symbol] = dict(target_weight=float(w[j]), volatility=float(vol[j]), status='ok')
        audit.append(dict(day=str(days[i]), raw_weights=dict(zip([*p.columns, 'CASH'], map(float, weights)))))
    return maps, audit

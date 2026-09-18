"""Optional, causal portfolio allocation layered above strategy eligibility."""

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf


class AllocationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    enabled: bool = False
    symbols: list[str] = Field(default_factory=list, max_length=10)
    lookback: int = Field(default=60, ge=20, le=252)
    max_positions: int = Field(default=3, ge=1, le=10)
    max_weight: float = Field(default=0.35, gt=0, le=0.5)
    cash_reserve: float = Field(default=0.05, ge=0, le=0.9)
    risk_aversion: float = Field(default=10, ge=0.1, le=100)
    cost_penalty: float = Field(default=2, ge=0, le=10)
    rebalance_band: float = Field(default=0.02, ge=0, le=0.2)
    max_daily_turnover: float = Field(default=1, gt=0, le=10)
    rebalance_minutes: int = Field(default=30, ge=5, le=120)


def allocate(config, symbols, returns, base, current, expected, cost_rates, horizon=1):
    """Fixed strategy-approved gross exposure; optimize its distribution, not entry signals.

    Ranking reduces cardinality first; the remaining risk/cost problem is convex.
    All arrays must contain only observations known at this decision timestamp.
    """
    targets = dict(base)
    pool = [s for s in symbols if not config.symbols or s in config.symbols]
    outside = sum(base[s] for s in symbols if s not in pool)
    eligible = [s for s in pool if base[s] > 0]
    for s in pool:
        targets[s] = 0.0
    diagnostic = dict(
        method="shrinkage-risk-cost",
        status="cash",
        selected=[],
        observed_rows=len(returns),
        target_weights=targets.copy(),
    )
    if not eligible:
        return targets, diagnostic
    history = returns.reindex(columns=eligible).tail(config.lookback).dropna()
    if len(history) < min(20, config.lookback):
        diagnostic["status"] = "warming_up"
        return targets, diagnostic
    covariance = LedoitWolf().fit(history.to_numpy()).covariance_ * max(horizon, 1)
    covariance += np.eye(len(eligible)) * 1e-10
    volatility = np.sqrt(np.diag(covariance))
    mu = np.array([expected.get(s, 0.0) for s in eligible])
    # Incumbent bonus approximates avoidable transaction costs during rank changes.
    ranks = [
        (
            (mu[i] + config.cost_penalty * cost_rates[s] * (current[s] > 0))
            / max(volatility[i], 1e-6),
            -volatility[i],
            s,
        )
        for i, s in enumerate(eligible)
    ]
    selected = [r[2] for r in sorted(ranks, reverse=True)[: config.max_positions]]
    indices = [eligible.index(s) for s in selected]
    cov = covariance[np.ix_(indices, indices)]
    mu = mu[indices]
    old = np.array([current[s] for s in selected])
    costs = np.array([cost_rates[s] for s in selected])
    budget = min(
        sum(base[s] for s in pool),
        max(0, 1 - config.cash_reserve - outside),
        len(selected) * config.max_weight,
    )
    if budget <= 0:
        return targets, diagnostic
    n = len(selected)
    initial = np.full(n, budget / n)
    x0 = np.r_[initial, np.abs(initial - old)]

    def objective(x):
        w, turnover = x[:n], x[n:]
        return 10000 * (
            config.risk_aversion / 2 * w @ cov @ w - mu @ w + config.cost_penalty * costs @ turnover
        )

    def jacobian(x):
        return 10000 * np.r_[config.risk_aversion * cov @ x[:n] - mu, config.cost_penalty * costs]

    result = minimize(
        objective,
        x0,
        jac=jacobian,
        method="SLSQP",
        bounds=[(0, config.max_weight)] * n + [(0, 1)] * n,
        constraints=[
            {
                "type": "eq",
                "fun": lambda x: x[:n].sum() - budget,
                "jac": lambda x: np.r_[np.ones(n), np.zeros(n)],
            },
            {
                "type": "ineq",
                "fun": lambda x: x[n:] - (x[:n] - old),
                "jac": lambda x: np.c_[-np.eye(n), np.eye(n)],
            },
            {
                "type": "ineq",
                "fun": lambda x: x[n:] + (x[:n] - old),
                "jac": lambda x: np.c_[np.eye(n), np.eye(n)],
            },
        ],
        options={"ftol": 1e-10, "maxiter": 100},
    )
    if not result.success or not np.isfinite(result.x).all():
        # Avoid new risk on optimizer failure; retain bounded eligible holdings only.
        w = np.minimum(old, config.max_weight)
        if w.sum() > budget:
            w *= budget / w.sum()
        status = "fallback_hold"
    else:
        w = np.clip(result.x[:n], 0, config.max_weight)
        if w.sum() > budget:
            w *= budget / w.sum()
        status = "optimized"
    targets.update({s: float(v) for s, v in zip(selected, w, strict=True)})
    diagnostic.update(
        status=status,
        selected=selected,
        target_weights=targets.copy(),
        expected_horizon_return=float(mu @ w),
        horizon_volatility=float(np.sqrt(w @ cov @ w)),
        estimated_turnover=float(sum(abs(targets[s] - current[s]) for s in pool)),
    )
    return targets, diagnostic

"""Fixed, causal daily portfolio rules; scores are signals, never return forecasts."""

import math

import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

MODELS = {
    "cross_momentum",
    "channel_trend",
    "residual_reversal",
    "minimum_variance",
    "fixed_ensemble",
    "adaptive_specialist",
    "synthetic_regime",
    "generated_policy",
}


def rule_forecasts(daily, config):
    if config.model == "adaptive_specialist":
        return specialist_forecasts(daily, config)
    closes = (
        daily.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    symbols = list(closes.columns)
    prices = closes.to_numpy(dtype=float)
    logs = np.log(prices)
    returns = np.diff(logs, axis=0)
    active = np.zeros(len(symbols), dtype=bool)
    forecasts = {}
    cap = min(config.max_weight, 0.2)
    gross = 0.95

    def weights(scores, vol):
        raw = np.maximum(scores, 0) / np.maximum(vol, 1e-6)
        return np.minimum(cap, raw / raw.sum() * gross) if raw.sum() > 0 else raw

    for i in range(1, len(prices)):
        if i >= 55:
            active |= prices[i] > prices[i - 55 : i].max(axis=0)
            active &= prices[i] >= prices[i - 20 : i].min(axis=0)
        if i < 63:
            continue
        history = returns[i - 63 : i]
        if not np.isfinite(history).all():
            raise ValueError("固定日线策略需要连续完整的交易日日线")
        cov = LedoitWolf().fit(history).covariance_ + np.eye(len(symbols)) * 1e-12
        vol = np.sqrt(np.diag(cov))
        momentum = logs[i - 5] - logs[i - 63]
        top = sorted(range(len(symbols)), key=lambda j: (-momentum[j], symbols[j]))[
            : max(1, math.ceil(len(symbols) * 0.25))
        ]
        eligible = np.zeros(len(symbols))
        for j in top:
            eligible[j] = float(momentum[j] > 0)
        momentum_weights = weights(eligible, vol)
        channel_weights = weights(active.astype(float), vol)
        market = history.mean(axis=1)
        design = np.column_stack([np.ones(len(history)), market])
        residual = history - design @ np.linalg.lstsq(design, history, rcond=None)[0]
        z = residual[-5:].sum(axis=0) / np.maximum(
            residual.std(axis=0, ddof=2) * math.sqrt(5), 1e-8
        )
        reversal_weights = weights(np.where(z < -1, -z, 0), vol)
        method = config.model
        status = "ok"
        if method == "minimum_variance":
            budget = min(gross, len(symbols) * cap)
            result = minimize(
                lambda w, cov=cov: float(w @ cov @ w) * 10000,
                np.full(len(symbols), budget / len(symbols)),
                jac=lambda w, cov=cov: 20000 * cov @ w,
                bounds=[(0, cap)] * len(symbols),
                constraints=[
                    {
                        "type": "eq",
                        "fun": lambda w, budget=budget: w.sum() - budget,
                        "jac": lambda w: np.ones(len(symbols)),
                    }
                ],
                method="SLSQP",
                options={"ftol": 1e-10, "maxiter": 100},
            )
            if result.success and np.isfinite(result.x).all():
                target = np.clip(result.x, 0, cap)
                target *= min(1, budget / max(target.sum(), 1e-12))
            else:
                target = np.zeros(len(symbols))
                status = "optimizer_failed_cash"
        elif method == "generated_policy":
            from quant_workbench.generated_policy import policy_probabilities

            predictions = [
                policy_probabilities(logs[i - 63 : i + 1, j]) for j in range(len(symbols))
            ]
            probabilities = np.array([item[0] for item in predictions])
            trend_signal = (logs[i] - logs[i - 20] > 0).astype(float)
            past = logs[i - 20 : i + 1]
            reversion_signal = (
                (past.mean(axis=0) - logs[i]) / np.maximum(past.std(axis=0, ddof=1), 0.001) > 0.5
            ).astype(float)
            target = weights(
                probabilities[:, 1] * trend_signal + probabilities[:, 2] * reversion_signal, vol
            )
            # Cash probability must actually reduce investment, not be normalized away.
            target *= float(np.mean(1 - probabilities[:, 0]))
        elif method == "synthetic_regime":
            from quant_workbench.synthetic_regimes import regime_probabilities

            probabilities = np.array(
                [regime_probabilities(logs[i - 63 : i + 1, j]) for j in range(len(symbols))]
            )
            target = (
                probabilities[:, 0] * (momentum_weights + channel_weights) / 2
                + probabilities[:, 1] * reversal_weights
            )
        else:
            target = {
                "cross_momentum": momentum_weights,
                "channel_trend": channel_weights,
                "residual_reversal": reversal_weights,
                "fixed_ensemble": (momentum_weights + channel_weights + reversal_weights) / 3,
            }[method]
        annual_vol = math.sqrt(max(0, float(target @ cov @ target)) * 252)
        scale = min(1, 0.10 / max(annual_vol, 1e-12))
        target = target * scale
        for j, symbol in enumerate(symbols):
            forecasts[(str(closes.index[i]), symbol)] = dict(
                target_weight=float(target[j]),
                volatility=float(vol[j]),
                momentum_score=float(momentum[j]),
                residual_z=float(z[j]),
                channel_active=bool(active[j]),
                risk_scale=float(scale),
                status=status,
            )
            if method == "generated_policy":
                forecasts[(str(closes.index[i]), symbol)].update(
                    cash_probability=float(probabilities[j, 0]),
                    trend_probability=float(probabilities[j, 1]),
                    reversion_probability=float(probabilities[j, 2]),
                    classifier_version=predictions[j][1],
                )
            if method == "synthetic_regime":
                forecasts[(str(closes.index[i]), symbol)].update(
                    trend_probability=float(probabilities[j, 0]),
                    reversion_probability=float(probabilities[j, 1]),
                    noise_probability=float(probabilities[j, 2]),
                    classifier_version="synthetic-regimes-v1-seed-1709",
                )
    return forecasts


def cost_aware_targets(symbols, returns, targets, current, cost_rates, cap, horizon):
    """Convex tracking-error + L1 turnover problem, with hard cash/risk bounds."""
    history = returns.reindex(columns=symbols).tail(63).dropna()
    if len(history) < 63:
        return dict.fromkeys(symbols, 0.0), {
            "status": "warming_up",
            "selected": [],
            "method": "cost-aware-tracking",
        }
    cov = LedoitWolf().fit(history.to_numpy()).covariance_ + np.eye(len(symbols)) * 1e-12
    t = np.array([targets[s] for s in symbols])
    old = np.array([current[s] for s in symbols])
    metric = cov / max(float(np.diag(cov).mean()), 1e-12)
    penalty = np.array([cost_rates[s] for s in symbols]) / np.maximum(
        np.sqrt(np.diag(cov) * max(horizon, 1)), 1e-6
    )
    n = len(symbols)
    budget = min(0.95, float(t.sum()))
    bound = max(float(t @ cov @ t), 1e-12)

    def objective(x):
        delta = x[:n] - t
        return float(0.5 * delta @ metric @ delta + penalty @ x[n:])

    def jac(x):
        return np.r_[metric @ (x[:n] - t), penalty]

    result = minimize(
        objective,
        np.r_[t, np.abs(t - old)],
        jac=jac,
        method="SLSQP",
        bounds=[(0, cap if t[i] > 1e-10 else 0) for i in range(n)] + [(0, 1)] * n,
        constraints=[
            {
                "type": "ineq",
                "fun": lambda x: budget - x[:n].sum(),
                "jac": lambda x: np.r_[-np.ones(n), np.zeros(n)],
            },
            {
                "type": "ineq",
                "fun": lambda x: x[n:] - x[:n] + old,
                "jac": lambda x: np.c_[-np.eye(n), np.eye(n)],
            },
            {
                "type": "ineq",
                "fun": lambda x: x[n:] + x[:n] - old,
                "jac": lambda x: np.c_[np.eye(n), np.eye(n)],
            },
            {
                "type": "ineq",
                "fun": lambda x: (bound - x[:n] @ cov @ x[:n]) * 10000,
                "jac": lambda x: np.r_[-20000 * cov @ x[:n], np.zeros(n)],
            },
        ],
        options={"ftol": 1e-10, "maxiter": 200},
    )
    w = result.x[:n] if result.success else t.copy()
    w = np.clip(w, 0, cap)
    w[t <= 1e-10] = 0
    w *= min(1, budget / max(w.sum(), 1e-12), math.sqrt(bound / max(float(w @ cov @ w), 1e-12)))
    output = dict(zip(symbols, map(float, w), strict=True))
    return output, dict(
        method="cost-aware-tracking",
        status="optimized" if result.success else "fallback_signal",
        selected=[s for s in symbols if output[s] > 1e-10],
        target_weights=output.copy(),
        estimated_turnover=float(np.abs(w - old).sum()),
        original_turnover=float(np.abs(t - old).sum()),
    )


def specialist_forecasts(daily, config):
    """Stock-specific experts selected only from matured, costed shadow outcomes."""
    experts = ["cross_momentum", "channel_trend", "residual_reversal"]
    signals = {m: rule_forecasts(daily, config.model_copy(update={"model": m})) for m in experts}
    close = (
        daily.pivot(index="day", columns="symbol", values="close").sort_index().sort_index(axis=1)
    )
    opening = daily.pivot(index="day", columns="symbol", values="open").reindex(
        index=close.index, columns=close.columns
    )
    days = list(close.index)
    symbols = list(close.columns)
    prices = close.to_numpy()
    opens = opening.to_numpy()
    rewards = np.zeros((len(days), len(symbols), len(experts)))
    selected = [None] * len(symbols)
    output = {}
    costs = config.costs

    def rate(price, sell=False):
        shares = max(1, math.floor(config.costs.initial_cash * 0.05 / price))
        return (
            costs.spread_bps / 2 + costs.slippage_bps + (costs.sell_fee_bps if sell else 0)
        ) / 10000 + max(costs.minimum_commission, shares * costs.commission_per_share) / (
            shares * price
        )

    for i in range(65, len(days)):
        for j, s in enumerate(symbols):
            for k, m in enumerate(experts):
                held = float(signals[m].get((days[i - 2], s), {}).get("target_weight", 0) > 1e-8)
                previous = float(
                    signals[m].get((days[i - 3], s), {}).get("target_weight", 0) > 1e-8
                )
                rewards[i, j, k] = held * (opens[i, j] / opens[i - 1, j] - 1) - abs(
                    held - previous
                ) * rate(opens[i - 1, j], held < previous)
        if i < 127:
            continue
        observed = rewards[i - 62 : i + 1]
        scores = observed.mean(axis=0) - observed.std(axis=0, ddof=1) / math.sqrt(63)
        if (i - 127) % 21 == 0:
            for j, _symbol in enumerate(symbols):
                best = int(np.argmax(scores[j]))
                best = best if scores[j, best] > 0 else None
                incumbent = selected[j]
                old_score = scores[j, incumbent] if incumbent is not None else 0.0
                new_score = scores[j, best] if best is not None else 0.0
                threshold = 2 * rate(prices[i, j], True) / 21 if incumbent is not None else 0.0
                if best != incumbent and new_score > old_score + threshold:
                    selected[j] = best
        raw = np.array(
            [
                signals[experts[selected[j]]].get((days[i], s), {}).get("target_weight", 0)
                if selected[j] is not None
                else 0
                for j, s in enumerate(symbols)
            ]
        )
        raw = np.clip(raw, 0, min(0.2, config.max_weight))
        raw *= min(1, 0.95 / max(raw.sum(), 1e-12))
        history = np.diff(np.log(prices[i - 63 : i + 1]), axis=0)
        cov = LedoitWolf().fit(history).covariance_ + np.eye(len(symbols)) * 1e-12
        scale = min(1, 0.1 / max(math.sqrt(float(raw @ cov @ raw) * 252), 1e-12))
        for j, s in enumerate(symbols):
            chosen = selected[j]
            output[(str(days[i]), s)] = dict(
                target_weight=float(raw[j] * scale),
                volatility=float(math.sqrt(cov[j, j])),
                selected_expert=experts[chosen] if chosen is not None else "cash",
                observation_start=str(days[i - 62]),
                observation_end=str(days[i]),
                observation_score=float(scores[j, chosen]) if chosen is not None else 0.0,
                risk_scale=scale,
                status="ok",
            )
    return output

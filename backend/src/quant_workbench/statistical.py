"""Causal AR(1)/OU and Kalman local-linear-trend forecasts, in log-price bps."""

import math
from collections import deque

import numpy as np
import pandas as pd


def bayesian_session_forecasts(frame, config):
    """Predict remaining-session returns from opening 30 minutes; train on prior days only.

    Pooled stocks with fixed symbol indicators and Bayesian shrinkage. Labels use
    next-bar entry/flatten opens, but only completed prior-day labels enter fitting.
    """
    from sklearn.linear_model import BayesianRidge
    from sklearn.preprocessing import StandardScaler

    from quant_workbench.market_data import schedule

    symbols = sorted(frame.symbol.unique())
    rows = []
    dates = frame.timestamp.dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d")
    end = (pd.Timestamp(dates.max()) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    closes = {str(row.Index.date()): row.close for row in schedule(dates.min(), end).itertuples()}
    for (symbol, day), group in frame.assign(day=dates).groupby(["symbol", "day"]):
        bars = group.sort_values("timestamp")
        if len(bars) < 30:
            continue
        opening = bars.iloc[:30]
        close = opening.close.to_numpy()
        base = float(opening.iloc[0].open)
        high, low = float(opening.high.max()), float(opening.low.min())
        features = [
            math.log(close[-1] / base) * 10000,
            (high - low) / base * 10000,
            float(np.std(np.diff(np.log(close))) * 10000),
            math.log(close[-1] / close[-6]) * 10000,
            (close[-1] - low) / max(high - low, 1e-9),
            *[float(symbol == s) for s in symbols],
        ]
        # Signal at close-5min fills on the next minute's open, matching the engine.
        target = None
        if len(bars) > 30 and bars.iloc[-1].timestamp >= closes[day]:
            target = math.log(
                float(bars.iloc[-config.flatten_minutes].open) / float(bars.iloc[30].open)
            ) * 10000
        rows.append(dict(day=day, symbol=symbol, x=features, y=target))
    predictions = {}
    days = sorted({row["day"] for row in rows})
    for i, day in enumerate(days):
        previous = set(days[max(0, i - 60):i])
        train = [row for row in rows if row["day"] in previous and row["y"] is not None]
        today = [row for row in rows if row["day"] == day]
        if len(train) < 50:
            continue
        scaler = StandardScaler()
        x = scaler.fit_transform([row["x"] for row in train])
        model = BayesianRidge()
        model.fit(x, [row["y"] for row in train])
        mean, std = model.predict(scaler.transform([row["x"] for row in today]), return_std=True)
        for row, expected, uncertainty in zip(today, mean, std, strict=True):
            predictions[(row["symbol"], day)] = dict(
                mean_bps=float(expected), uncertainty_bps=float(uncertainty),
                last_training_day=max(previous), training_samples=len(train),
            )
    return predictions


class StatisticalForecast:
    def __init__(self, config, strategy):
        self.config, self.strategy = config, strategy
        self.prices = deque(maxlen=config.stat_window + 1)
        self.state = None
        self.covariance = np.eye(2)

    def observe(self, close):
        price = math.log(close) * 10000
        self.prices.append(price)
        if self.strategy == "kalman_trend":
            if self.state is None:
                self.state = np.array([price, 0.0])
                return
            variance = max(float(np.var(np.diff(self.prices))), 1.0)
            transition = np.array([[1.0, 1.0], [0.0, 1.0]])
            process = variance * np.diag([0.01, self.config.stat_process_noise])
            predicted = transition @ self.state
            covariance = transition @ self.covariance @ transition.T + process
            gain = covariance[:, 0] / (covariance[0, 0] + variance)
            self.state = predicted + gain * (price - predicted[0])
            # Joseph covariance update preserves positive semidefiniteness.
            residual = np.eye(2)
            residual[:, 0] -= gain
            self.covariance = residual @ covariance @ residual.T + variance * np.outer(gain, gain)

    def forecast(self):
        cfg = self.config
        if len(self.prices) < cfg.stat_window + 1:
            return None
        values = np.asarray(self.prices)
        horizon = cfg.stat_horizon
        if self.strategy == "kalman_trend":
            projection = np.array([1.0, float(horizon)])
            mean = float(projection @ self.state - values[-1])
            noise = max(float(np.var(np.diff(values))), 1.0)
            variance = float(projection @ self.covariance @ projection) + noise * (
                1 + 0.01 * horizon
                + cfg.stat_process_noise * (horizon - 1) * horizon * (2 * horizon - 1) / 6
            )
            return dict(mean_bps=mean, uncertainty_bps=math.sqrt(variance), eligible=mean > 0)
        x, y = values[:-1], values[1:]
        center = float(x.mean())
        dx = x - center
        xx = float(dx @ dx)
        if xx < 1e-9:
            return None
        phi = float(dx @ (y - y.mean()) / xx)
        if not 0 < phi < 0.995:
            return None  # No evidence of a stable discrete OU / AR(1) equilibrium.
        intercept = float(y.mean() - phi * center)
        equilibrium = intercept / (1 - phi)
        residual = y - (intercept + phi * x)
        variance = max(float(residual @ residual) / (len(x) - 2), 1e-9)
        stationary_sd = math.sqrt(variance / (1 - phi * phi))
        z = (values[-1] - equilibrium) / stationary_sd
        forecast = float(values[-1])
        gradient = np.zeros(2)
        for _ in range(horizon):
            gradient = np.array([1.0, forecast - center]) + phi * gradient
            forecast = float(y.mean()) + phi * (forecast - center)
        # Innovation variance plus delta-method uncertainty of estimated intercept/slope.
        uncertainty = variance * (
            (1 - phi ** (2 * horizon)) / (1 - phi * phi)
            + gradient[0] ** 2 / len(x) + gradient[1] ** 2 / xx
        )
        return dict(
            mean_bps=forecast - values[-1], uncertainty_bps=math.sqrt(uncertainty),
            eligible=z <= -cfg.stat_entry_z, z_score=z,
            half_life=-math.log(2) / math.log(phi),
        )

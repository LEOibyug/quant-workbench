"""Train a historical-calibrated pattern recognizer without future-return labels."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from quant_workbench.conditional_policy import decompose, network
from torch import nn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("artifacts/models/conditional-policy-v2/history/daily.parquet"),
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/models/pattern-policy-v2"))
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(20250901)
    rng = np.random.default_rng(20250901)
    data = pd.read_parquet(args.history)
    assert data.day.max() < "2025-09-01"
    train = []
    valid = []
    sigmas = []
    dates = []
    for _symbol, g in data.groupby("symbol"):
        g = g.sort_values("day")
        logs = np.log(g.close.to_numpy())
        for i in range(63, len(g), 5):
            if (pd.to_datetime(g.day.iloc[i]) - pd.to_datetime(g.day.iloc[i - 63])).days > 110:
                continue
            window = logs[i - 63 : i + 1]
            sample = decompose(window)
            if g.day.iloc[i] < "2024-09-01":
                train.append(sample)
                sigmas.append(np.diff(window).std())
                dates.append(g.day.iloc[i])
            elif g.day.iloc[i - 63] >= "2024-09-01":
                valid.append(sample)
    sigma_bounds = np.quantile(sigmas, [0.1, 0.9])
    # Synthetic teacher coefficients refer to visible decomposition, not latent future state.
    synthetic = []
    for _ in range(6000):
        t = np.arange(64)
        sigma = rng.uniform(*sigma_bounds)
        components = rng.dirichlet([0.7, 0.7, 0.7])
        trend = (t - 31.5) / np.std(t) * rng.choice([-1, 1])
        cycles = sum(
            rng.normal() * np.sin(2 * np.pi * t / period + rng.uniform(0, 2 * np.pi))
            for period in (10, 21, 42)
        )
        cycles /= max(cycles.std(), 1e-6)
        noise = np.cumsum(rng.standard_t(5, size=64))
        noise = (noise - noise.mean()) / max(noise.std(), 1e-6)
        y = (
            (
                np.sqrt(components[0]) * trend
                + np.sqrt(components[1]) * cycles
                + np.sqrt(components[2]) * noise
            )
            * sigma
            * np.sqrt(64)
        )
        if rng.random() < 0.25:
            y[32:] += rng.normal(0, sigma * 2) * np.arange(32) / 32
        synthetic.append(decompose(y))
    combined = train + synthetic

    def tensors(rows):
        return [torch.tensor(np.stack([r[k] for r in rows]), dtype=torch.float32) for k in range(3)]

    x, f, y = tensors(combined)
    vx, vf, vy = tensors(valid)
    model = network()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    best = float("inf")
    state = None
    history = []
    for epoch in range(40):
        model.train()
        order = torch.randperm(len(x))
        losses = []
        for batch in order.split(256):
            logits = model(x[batch], f[batch])
            loss = -(y[batch] * torch.log_softmax(logits, 1)).sum(1).mean()
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
            losses.append(float(loss.detach()))
        model.eval()
        with torch.no_grad():
            pred = torch.softmax(model(vx, vf), 1)
            error = float(((pred - vy) ** 2).mean())
        history.append(dict(epoch=epoch + 1, loss=float(np.mean(losses)), validation_mse=error))
        if error < best:
            best = error
            state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_epoch = epoch + 1
        if epoch % 5 == 0:
            print(history[-1], flush=True)
    model.load_state_dict(state)
    with torch.no_grad():
        pred = torch.softmax(model(vx, vf), 1).numpy()
    actual = vy.numpy()
    report = dict(
        version="spectral-pattern-v2",
        cutoff="2025-09-01",
        train_end_exclusive="2024-09-01",
        history_sha256=hashlib.sha256(args.history.read_bytes()).hexdigest(),
        training_windows=len(train),
        synthetic_windows=len(synthetic),
        validation_windows=len(valid),
        max_training_observation=max(dates),
        best_epoch=best_epoch,
        epochs=history,
        calibration_sigma_bounds=sigma_bounds.tolist(),
        metrics=dict(
            pattern_mse=best,
            mean_absolute_error=float(np.abs(pred - actual).mean()),
            dominant_pattern_agreement=float(np.mean(pred.argmax(1) == actual.argmax(1))),
        ),
        limitations=("Teacher is past-window Fourier/Haar decomposition, not independent truth "
                     "or future profit label; agreement is distillation accuracy only."),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(
        dict(state=state, version=report["version"], cutoff=report["cutoff"], report=report),
        args.output / "model.pt",
    )
    report["model_sha256"] = hashlib.sha256((args.output / "model.pt").read_bytes()).hexdigest()
    (args.output / "training.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "epochs"}), flush=True)


if __name__ == "__main__":
    main()

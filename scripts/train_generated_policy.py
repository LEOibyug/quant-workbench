"""Train constrained conditional sequence generator and future-utility classifier."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import torch
from quant_workbench.synthetic_regimes import window_features
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn


class Generator(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(19, 64), nn.Tanh(), nn.Linear(64, 64), nn.Tanh(), nn.Linear(64, 85)
        )

    def forward(self, z, labels):
        # At most 0.6% conditional daily drift, independent noise cannot be cancelled.
        return 0.006 * torch.tanh(
            self.net(torch.cat([z, torch.nn.functional.one_hot(labels, 3).float()], 1))
        )


def utilities(r, soft=False):
    price = torch.cumsum(r, 1)
    returns = []
    for t in range(64, 85):
        trend = price[:, t - 1] - price[:, t - 21]
        past = price[:, t - 21 : t]
        revert = (past.mean(1) - price[:, t - 1]) / past.std(1).clamp_min(0.001)
        if soft:
            a = torch.sigmoid(trend / 0.015)
            b = torch.sigmoid((revert - 0.5) * 3)
        else:
            a = (trend > 0).float()
            b = (revert > 0.5).float()
        returns.append(torch.stack([torch.zeros_like(a), a, b], 1))
    weights = torch.stack(returns, 1)
    changes = torch.diff(weights, dim=1, prepend=torch.zeros_like(weights[:, :1]))
    pnl = weights * r[:, 64:, None] - 0.001 * changes.abs()
    # Charge liquidation and realized path risk, no free turnover.
    return pnl.sum(1) - 0.001 * weights[:, -1] - 0.5 * pnl.std(1) * np.sqrt(21)


def sample(generator, n, seed):
    rng = torch.Generator().manual_seed(seed)
    labels = torch.arange(n) % 3
    z = torch.randn(n, 16, generator=rng)
    with torch.no_grad():
        drift = generator(z, labels)
    sigma = 0.005 + 0.02 * torch.rand(n, 1, generator=rng)
    noise = torch.randn(n, 85, generator=rng) * sigma
    r = (drift + noise).clamp(-0.10, 0.10)
    # Half the classifier data is unoptimized, preventing winner-only templates.
    r[::2] = noise[::2].clamp(-0.10, 0.10)
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/models/generated-policy-v1"))
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(1709)
    np.random.seed(1709)
    generator = Generator()
    opt = torch.optim.Adam(generator.parameters(), lr=0.001)
    history = []
    for step in range(400):
        labels = torch.arange(192) % 3
        z = torch.randn(192, 16)
        drift = generator(z, labels)
        noise = torch.randn_like(drift) * (0.005 + 0.02 * torch.rand(192, 1))
        r = (drift + noise).clamp(-0.10, 0.10)
        u = utilities(r, soft=True)
        chosen = u.gather(1, labels[:, None]).squeeze(1)
        other = u.masked_fill(torch.nn.functional.one_hot(labels, 3).bool(), -1e6).max(1).values
        loss = -(chosen - other).mean() + 2 * (drift / 0.006).square().mean() * 0.01
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(generator.parameters(), 1)
        opt.step()
        if step % 50 == 0:
            history.append({"step": step, "loss": float(loss.detach())})
            print(history[-1], flush=True)

    def dataset(n, seed):
        r = sample(generator, n, seed)
        utility = utilities(r).numpy()
        y = utility.argmax(1)
        x = np.stack([window_features(np.cumsum(row[:64])) for row in r.numpy()])
        return x, y, r.numpy(), utility

    x, y, sequences, utility = dataset(6000, 2718)
    model = make_pipeline(
        StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=1709)
    ).fit(x, y)
    a, b, testseq, testutility = dataset(2000, 3141)
    probabilities = model.predict_proba(a)
    pred = model.predict(a)
    majority = int(np.bincount(y, minlength=3).argmax())
    metrics = dict(
        accuracy=accuracy_score(b, pred),
        majority_accuracy=float(np.mean(b == majority)),
        log_loss=log_loss(b, probabilities, labels=model.classes_),
        confusion_matrix=confusion_matrix(b, pred, labels=[0, 1, 2]).tolist(),
        train_classes=np.bincount(y, minlength=3).tolist(),
        test_classes=np.bincount(b, minlength=3).tolist(),
        selected_future_utility=float(testutility[np.arange(len(pred)), pred].mean()),
        cash_future_utility=0.0,
        oracle_future_utility=float(testutility.max(1).mean()),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(generator.state_dict(), args.output / "generator.pt")
    joblib.dump(
        dict(model=model, version="generated-policy-v1", labels=["cash", "trend", "reversion"]),
        args.output / "classifier.joblib",
    )
    np.savez_compressed(
        args.output / "samples.npz",
        train_returns=sequences,
        train_labels=y,
        test_returns=testseq,
        test_labels=b,
    )
    report = dict(
        version="generated-policy-v1",
        seed=1709,
        steps=400,
        training=history,
        metrics=metrics,
        constraints=(
            "bounded conditional drift + independent noise; future utility labels; "
            "observation features only; no real data training"
        ),
        limitation=(
            "generator rewards differentiable single-stock proxies, not full shared-capital "
            "engine; synthetic labels do not guarantee real-world strategy labels"
        ),
        classifier_sha256=hashlib.sha256(
            (args.output / "classifier.joblib").read_bytes()
        ).hexdigest(),
    )
    (args.output / "training.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()

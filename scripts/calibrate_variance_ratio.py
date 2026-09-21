"""Fixed-seed null diagnostics, never used to tune the trading threshold."""

import json
from pathlib import Path

import numpy as np
from variance_applicability import judge_returns


def main():
    rng = np.random.default_rng(20250921)
    rows = []
    for name in ("iid_gaussian", "independent_volatility_shift"):
        values = []
        scale = np.ones(126) if name == "iid_gaussian" else np.r_[np.ones(63), np.full(63, 3.0)]
        for _ in range(5000):
            values.append(judge_returns(rng.normal(size=126) * scale)["z"])
        z = np.array(values)
        rate = float(np.mean(abs(z) > 1.96))
        rows.append(
            dict(
                null=name,
                paths=len(z),
                rejection_rate=rate,
                monte_carlo_standard_error=float(np.sqrt(rate * (1 - rate) / len(z))),
                z_quantiles=np.quantile(z, [0.025, 0.5, 0.975]).tolist(),
            )
        )
    report = dict(
        seed=20250921,
        threshold=1.96,
        results=rows,
        note="有限样本诊断；没有按模拟结果改阈值，不能作为实际市场概率校准",
    )
    Path("docs/research-results/2026-09-21-variance-ratio-null.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

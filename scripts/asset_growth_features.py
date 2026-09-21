"""Same-filing total asset expansion; never a validated suitability verdict."""

import argparse
import json
from datetime import date
from pathlib import Path

from quality_value_features import EXCLUDED


def judge(facts, symbol, cutoff, verified=False):
    date.fromisoformat(cutoff)
    out = dict(symbol=symbol, asof=cutoff, status="证据不足", validated=False, computable=False)
    if not verified or symbol in EXCLUDED:
        return dict(out, reason="身份或会计范围未通过")
    rows = [
        dict(r, tag="Assets")
        for r in facts.get("facts", {})
        .get("us-gaap", {})
        .get("Assets", {})
        .get("units", {})
        .get("USD", [])
        if r.get("form") in ("10-K", "10-K/A")
        and r.get("filed", "9999") < cutoff
        and r.get("end", "9999") < cutoff
        and "start" not in r
        and r.get("accn")
    ]
    if not rows:
        return dict(out, reason="缺年度已公开资产")
    last = max(rows, key=lambda r: (r["end"], r["filed"], r["accn"]))
    end = last["end"]
    accn = last["accn"]
    if (date.fromisoformat(cutoff) - date.fromisoformat(end)).days > 550:
        return dict(out, reason="资产年度陈旧")
    current = [r for r in rows if r["end"] == end and r["accn"] == accn]
    prior = [
        r
        for r in rows
        if r["accn"] == accn
        and 330 <= (date.fromisoformat(end) - date.fromisoformat(r["end"])).days <= 400
    ]
    if not prior:
        return dict(out, reason="同年报缺前一年资产")
    prev = max(r["end"] for r in prior)
    prior = [r for r in prior if r["end"] == prev]
    if len({r["val"] for r in current}) != 1 or len({r["val"] for r in prior}) != 1:
        return dict(out, reason="同申报资产值冲突")
    if min(current[0]["val"], prior[0]["val"]) <= 0:
        return dict(out, reason="资产非正")
    return dict(
        out,
        computable=True,
        growth=current[0]["val"] / prior[0]["val"] - 1,
        accession=accn,
        sources=dict(current_assets=current[0], prior_assets=prior[0]),
        reason="资产增长可计算；低增长的策略适用性尚未验证，资格排名依赖股票池",
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--date", required=True)
    a = p.parse_args()
    s = a.symbol.upper()
    path = Path("artifacts/research/sec-quality") / f"{s}-facts.json"
    ids = json.loads(Path("docs/research-results/2026-09-21-sec-50-issuers.json").read_text())
    print(
        json.dumps(
            judge(
                json.loads(path.read_text()) if path.exists() else {},
                s,
                a.date,
                ids.get(s, {}).get("identity_verified", False),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

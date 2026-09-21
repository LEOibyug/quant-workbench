import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_dividend_replay import replay  # noqa: E402


def test_replay_uses_prior_holdings_and_preserves_unpaid_claims():
    curve = [
        dict(date="2024-02-07", positions={"A": 0}, equity=1000, cash=1000),
        dict(date="2024-02-08", positions={"A": 10}, equity=1000, cash=0),
        dict(date="2024-02-09", positions={"A": 0}, equity=997.6, cash=997.6),
        dict(date="2024-02-15", positions={"A": 0}, equity=997.6, cash=997.6),
    ]
    event = dict(id="one", symbol="A", ex_date="2024-02-09", payable_date="2024-02-15", rate=0.24)
    r = replay(curve, 1000, [event])
    assert float(r["assumed_income"]) == 2.4
    assert float(r["assumed_paid"]) == 2.4
    assert r["provisional_curve"][-1]["provisional_equity"] == 1000
    assert r["events"][0]["preceding_shares"] == 10
    later = replay(curve, 1000, [{**event, "payable_date": "2024-03-15"}])
    assert float(later["assumed_paid"]) == 0
    assert float(later["assumed_receivable"]) == 2.4
    ambiguous = replay(curve, 1000, [event, {**event, "id": "two"}])
    assert float(ambiguous["assumed_income"]) == 0 and len(ambiguous["excluded"]) == 2

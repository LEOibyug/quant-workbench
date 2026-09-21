"""Only realized same-day wealth may change subsequent mixture targets."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from study_online_mixture import mixture_maps  # noqa: E402


def test_future_wealth_cannot_change_past_decision():
    def expert(wealth, target):
        return {
            "curve": [
                {"date": date, "equity": equity, "assets": {"A": {"target_weight": target}}}
                for date, equity in zip(["2025-09-02", "2025-09-03"], wealth, strict=True)
            ]
        }

    experts = [expert([100, 110], 0.2), expert([100, 90], 0.1)]
    result = mixture_maps(experts, 100)
    changed = copy.deepcopy(experts)
    changed[0]["curve"][1]["equity"] = 1000
    revised = mixture_maps(changed, 100)
    key = ("2025-09-02", "A")
    assert result["wealth_mix"][key] == revised["wealth_mix"][key]
    assert result["wealth_mix"][key]["target_weight"] == pytest.approx(0.1)
    assert result["wealth_mix"]["2025-09-03", "A"]["target_weight"] == pytest.approx(31 / 300)
    assert revised["wealth_mix"]["2025-09-03", "A"] != result["wealth_mix"]["2025-09-03", "A"]

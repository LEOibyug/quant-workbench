import pytest
from quant_workbench.storage import estimate_storage


def test_two_year_minute_budget_accounts_for_seven_symbols_and_working_copies():
    result = estimate_storage()
    assert result.rows == 1_375_920
    assert result.compressed_bytes_low == 33_022_080
    assert result.compressed_bytes_high == 88_058_880
    assert result.working_bytes_high == 264_176_640


def test_one_second_data_has_sixty_times_as_many_rows():
    minute = estimate_storage()
    second = estimate_storage(interval_seconds=1)
    assert second.rows == minute.rows * 60


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbols": 0},
        {"symbols": 2.5},
        {"symbols": True},
        {"years": -1},
        {"years": float("nan")},
        {"years": float("inf")},
        {"interval_seconds": 0},
        {"interval_seconds": 7},
        {"days_per_year": 0},
    ],
)
def test_invalid_budget_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        estimate_storage(**kwargs)


def test_storage_estimate_is_immutable():
    from dataclasses import FrozenInstanceError

    result = estimate_storage()
    with pytest.raises(FrozenInstanceError):
        result.rows = 1

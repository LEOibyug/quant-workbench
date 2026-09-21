import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('cash_interest_book',Path(__file__).parents[1]/'scripts/cash_interest_book.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
CashInterestBook=module.CashInterestBook


def test_lag_weekend_reinvestment_and_reuse():
    book=CashInterestBook({'2024-01-04':5,'2024-01-05':99,'2024-01-08':99},haircut=1)
    book.start(['2024-01-05','2024-01-08','2024-01-09'])
    assert book.before_open('2024-01-05',1000)==0
    friday_interest=book.before_open('2024-01-08',1000)
    assert friday_interest==pytest.approx(1000*.04*3/360)
    assert book.before_open('2024-01-09',1000+friday_interest)==pytest.approx((1000+friday_interest)*.98/360)
    with pytest.raises(ValueError):book.before_open('2024-01-09',1000)
    with pytest.raises(ValueError):book.start(['2024-01-10'])


def test_missing_rate_and_invalid_balance():
    with pytest.raises(ValueError):CashInterestBook({'2024-01-05':5}).start(['2024-01-05','2024-01-08'])
    b=CashInterestBook({'2024-01-04':5});b.start(['2024-01-05'])
    with pytest.raises(ValueError):b.before_open('2024-01-05',-1)

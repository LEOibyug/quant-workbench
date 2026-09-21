"""Accounting guards for the unvalidated earnings stability research proxy."""
import copy
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from earnings_stability import judge


def test_original_filing_scale_missing_conflict_and_negative_income():
    facts={'facts':{'us-gaap':{tag:{'units':{'USD':[]}} for tag in ['Assets','NetIncomeLoss']}}}
    for year in range(2017,2022):
        base=dict(end=f'{year}-12-31',filed=f'{year+1}-02-01',form='10-K',accn=str(year))
        facts['facts']['us-gaap']['Assets']['units']['USD'].append(dict(base,val=1000))
        facts['facts']['us-gaap']['NetIncomeLoss']['units']['USD'].append(dict(base,start=f'{year}-01-01',val=(year-2019)*10))
    result=judge(facts,'SYN','2022-09-01')
    assert result['computable'] and result['positive_years']==2 and result['status']=='证据不足'
    scaled=copy.deepcopy(facts)
    for tag in ['Assets','NetIncomeLoss']:
        for row in scaled['facts']['us-gaap'][tag]['units']['USD']:row['val']*=100
    assert judge(scaled,'SYN','2022-09-01')['volatility']==result['volatility']
    missing=copy.deepcopy(facts);missing['facts']['us-gaap']['NetIncomeLoss']['units']['USD'].pop()
    assert not judge(missing,'SYN','2022-09-01')['computable']
    conflict=copy.deepcopy(facts);rows=conflict['facts']['us-gaap']['NetIncomeLoss']['units']['USD'];rows.append(dict(rows[-1],val=99))
    assert not judge(conflict,'SYN','2022-09-01')['computable']
    later=copy.deepcopy(facts)
    for tag in ['Assets','NetIncomeLoss']:
        rows=later['facts']['us-gaap'][tag]['units']['USD'];rows.append(dict(rows[-1],accn='later',filed='2022-05-01',val=999))
    assert judge(later,'SYN','2022-09-01')==result

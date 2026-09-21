"""Frozen dynamic cash yield comparison with matched pure cash and zero controls."""
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from cash_interest_book import CashInterestBook
from asset_growth_forecasts import forecasts
from verified_liability_features import judge
from prepare_liability_transfer import CACHE
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def main():
    f=pd.read_parquet('artifacts/research/liability-transfer-temporal/combined.parquet')
    start,end='2022-09-01','2025-09-01'
    history=sorted(f.loc[f.day<start,'day'].unique())[-273:]
    f=f[(f.day>=history[0])&(f.day<end)]
    info=json.loads((ROOT/'2026-09-22-liability-transfer-fundamentals.json').read_text())
    ids={s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()}
    maps,_,_=forecasts(f,start,end,facts_root=CACHE,identities=ids,judge_fn=judge,ratio_key='burden')
    refs=json.loads((ROOT/'2026-09-22-liability-transfer-temporal.json').read_text())['results']
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(Path('artifacts/research/cash-benchmark/sofr.json').read_text())['refRates']}
    rows=[];checks=[]
    for method,mode in [('low_liability','low_growth'),('eligible','eligible')]:
        for mult in [1,2]:
            ref=next(r for r in refs if (r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])==(start,end,method,mult))
            cfg=PositionConfig(**ref['config'])
            for scenario,haircut in [('zero',None),('sofr',0),('sofr_minus1',1)]:
                book=None if haircut is None else CashInterestBook(rates,haircut)
                with patch('quant_workbench.position.daily_forecasts',return_value=maps[mode]):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book)
                if scenario=='zero':
                    assert r['metrics']==ref['metrics'] and r['contributions']==ref['contributions']
                    with patch('quant_workbench.position.daily_forecasts',return_value=maps[mode]):
                        z=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=CashInterestBook({d:0 for d in rates}))
                    assert {k:v for k,v in z['metrics'].items() if k!='cash_interest_income'}==r['metrics']
                    assert z['contributions']==r['contributions'] and z['trades']==r['trades']
                else:
                    assert np.isclose(sum(x['net_profit'] for x in r['contributions'])+book.income,r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
                    for p in r['curve']:
                        pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                        # Trading PNL includes fees in realization/basis in this engine.
                        assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                    for event,p in zip(book.audit,r['curve'][:-1]):
                        assert event['cash_basis']==p['cash']
                rows.append(dict(method=method,scenario=scenario,cost_multiplier=mult,start=start,end_exclusive=end,**{k:r[k] for k in ['config','metrics','contributions','curve']},cash_events=book.audit if book else []))
                checks.append(dict(method=method,cost_multiplier=mult,scenario=scenario,conservation=True,zero_control=haircut is None))
                save_results(ROOT/'2026-09-22-cash-feedback.json',rows)
                print(method,mult,scenario,r['metrics']['return_pct'],r['metrics']['halted'],flush=True)
    pure=[]
    days=sorted(f.loc[f.day>=start,'day'].unique())
    for haircut in [0,1]:
        b=CashInterestBook(rates,haircut);b.start(days);cash=100000
        for day in days:cash+=b.before_open(day,cash)
        pure.append(dict(haircut=haircut,first_close=days[0],last_close=days[-1],return_pct=(cash/100000-1)*100,income=b.income))
    assert len(rows)==12
    save_results(ROOT/'2026-09-22-cash-feedback.json',rows,completed=True)
    (ROOT/'2026-09-22-cash-feedback-checks.json').write_text(json.dumps(dict(checks=checks,pure_cash=pure),indent=2)+'\n')

if __name__=='__main__':main()

"""Shared equity-cushion cap and fixed30 control; frozen eighteen accounts."""
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from excess_trend_forecasts import forecasts
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def cushion(day,equity,peak):
    return min(.95,3*max(equity-.9*peak,0)/equity)


def main():
    assert np.isclose(cushion('',100,100),.3) and cushion('',90,100)==0
    assert np.isclose(cushion('',95,100),15/95)
    base=json.loads((ROOT/'2026-09-22-excess-trend.json').read_text())['results']
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(Path('artifacts/research/cash-benchmark/sofr-extended.json').read_text())['refRates']}
    paths=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];pure=[]
    for pool,path in paths.items():
        f=pd.read_parquet(path);start,end='2022-09-01','2025-09-01'
        history=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=history[0])&(f.day<end)]
        mapping=forecasts(f,rates)['inverse_vol']
        for mult in [1,2]:
            ref=next(r for r in base if (r['pool'],r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])==(pool,start,end,'inverse_vol',mult))
            cfg=PositionConfig(**{**ref['config'],'rebalance_days':1})
            for method,callback in [('uncapped',None),('constant30',lambda d,e,p:.3),('cushion',cushion)]:
                book=CashInterestBook(rates)
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book,research_risk_budget=callback)
                if method=='uncapped':
                    with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                        control=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=CashInterestBook(rates),research_risk_budget=lambda d,e,p:1.)
                    assert control['metrics']==r['metrics'] and control['contributions']==r['contributions'] and control['trades']==r['trades']
                else:
                    assert all(x['final_budget']<=x['cap']+1e-12 and x['final_budget']<=x['raw_budget']+1e-12 for x in r['research_risk_budget'])
                for p in r['curve']:
                    pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,budget_decisions=r.get('research_risk_budget',[]),**{k:r[k] for k in ['config','metrics','curve','contributions']}))
                save_results(ROOT/'2026-09-22-cushion-budget.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),flush=True)
    assert len(rows)==18
    save_results(ROOT/'2026-09-22-cushion-budget.json',rows,completed=True)

if __name__=='__main__':main()

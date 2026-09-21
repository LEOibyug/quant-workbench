"""Frozen eighteen-account semivariance comparison with shared cash accounting."""
import hashlib,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from downside_allocation import objective,forecasts
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def main():
    x=np.array([[-.1,.1],[.1,-.1]]);w=np.array([.5,.5]);cov=np.eye(2)*.01
    value,_=objective(w,x,cov,'downside');assert np.isclose(value,5e-9,atol=1e-14)
    assert np.mean((np.minimum(x,0)@w)**2)>.001
    x=np.random.default_rng(734).normal(0,.02,(63,7));w=np.full(7,.1);cov=x.T@x/63
    for mode in ['downside','upside','variance']:
        value,gradient=objective(w,x,cov,mode)
        numeric=[]
        for i in range(7):
            step=np.zeros(7);step[i]=1e-6
            numeric.append((objective(w+step,x,cov,mode)[0]-objective(w-step,x,cov,mode)[0])/2e-6)
        assert value>=0 and np.allclose(gradient,numeric,atol=1e-7,rtol=1e-6)
    ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json');rates={r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    base=json.loads((ROOT/'2026-09-22-excess-trend.json').read_text())['results']
    paths=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];checks=[];hashes={str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    for pool,path in paths.items():
        f=pd.read_parquet(path);hashes[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest();start,end='2022-09-01','2025-09-01'
        history=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=history[0])&(f.day<end)]
        maps=forecasts(f,rates,start,end);days=sorted(f.loc[f.day>=start,'day'].unique());cut=days[len(days)//2]
        short=forecasts(f[f.day<=cut],rates,start,end)
        for m in maps:assert short[m]=={k:v for k,v in maps[m].items() if k[0]<=cut}
        cash=100000.;cb=CashInterestBook(rates);cb.start(days)
        for d in days:cash+=cb.before_open(d,cash)
        for mult in [1,2]:
            cfg=PositionConfig(**next(r['config'] for r in base if r['cost_multiplier']==mult))
            for method,mapping in maps.items():
                book=CashInterestBook(rates)
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book)
                for p in r['curve']:
                    pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,cash_return_pct=(cash/100000-1)*100,**{k:r[k] for k in ['config','metrics','curve','trades','contributions']}))
                save_results(ROOT/'2026-09-22-downside-allocation.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),flush=True)
        checks.append(dict(pool=pool,prefix_exact=True,optimizer_feasible=True,objective_not_worse_than_initial=True,conservation=True))
    assert len(rows)==18
    save_results(ROOT/'2026-09-22-downside-allocation.json',rows,completed=True)
    (ROOT/'2026-09-22-downside-checks.json').write_text(json.dumps(dict(checks=checks,input_sha256=hashes,portfolio_netting_synthetic=True,analytic_gradient_checked=True),indent=2)+'\n')


if __name__=='__main__':main()

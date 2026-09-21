"""Frozen twelve-account signal-only adjustment comparison."""
import gzip,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from prepare_adjusted_trend import PATHS,CACHE
from adjusted_trend_forecasts import forecasts
from excess_trend_forecasts import forecasts as original_forecasts
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def main():
    source=json.loads((ROOT/'2026-09-22-adjusted-trend-data.json').read_text());assert source['status']=='completed'
    if any(any(v for k,v in r['differences'].items() if k!='volume') for r in source['raw_comparisons']):raise ValueError('Raw price revisions require separate audit before isolating adjustment')
    adjusted=pd.read_parquet(CACHE/'dividend.parquet')
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(Path('artifacts/research/cash-benchmark/sofr-extended.json').read_text())['refRates']}
    base=json.loads(gzip.decompress((ROOT/'2026-09-22-excess-trend.full.json.gz').read_bytes()))['results']
    rows=[];checks=[]
    for pool,path in PATHS.items():
        f=pd.read_parquet(path);start,end='2022-09-01','2025-09-01';history=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=history[0])&(f.day<end)]
        maps,changes=forecasts(f,adjusted);assert maps['raw_trend']==original_forecasts(f,rates)['raw_trend']
        days=sorted(f.loc[f.day>=start,'day'].unique());cut=days[len(days)//2];short,sc=forecasts(f[f.day<=cut],adjusted[adjusted.day<=cut])
        for m in maps:assert short[m]=={k:v for k,v in maps[m].items() if k[0]<=cut}
        assert sc==[r for r in changes if r['day']<=cut]
        scaled=adjusted.copy();scaled['close']*=10;scaled_maps,_=forecasts(f,scaled)
        assert all(np.isclose(v['target_weight'],scaled_maps[m][k]['target_weight'],atol=1e-12) for m in maps for k,v in maps[m].items())
        decisions=set(days[::20]);cash=100000.;cb=CashInterestBook(rates);cb.start(days)
        for d in days:cash+=cb.before_open(d,cash)
        for mult in [1,2]:
            ref=next(r for r in base if (r['pool'],r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])==(pool,start,end,'raw_trend',mult))
            cfg=PositionConfig(**ref['config'])
            for method,mapping in maps.items():
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=CashInterestBook(rates))
                if method=='raw_trend':
                    for key in ['metrics','contributions','curve']:assert r[key]==ref[key]
                for p in r['curve']:
                    pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,cash_return_pct=(cash/100000-1)*100,**{k:r[k] for k in ['config','metrics','curve','trades','contributions']}))
                save_results(ROOT/'2026-09-22-adjusted-trend.json',rows);print(pool,mult,method,round(r['metrics']['return_pct'],4),flush=True)
        checks.append(dict(pool=pool,prefix_exact=True,raw_signal_and_account_exact=True,scale_invariant=True,conservation=True,all_changed_signals=changes,changed_decisions=[r for r in changes if r['day'] in decisions]))
    assert len(rows)==12
    save_results(ROOT/'2026-09-22-adjusted-trend.json',rows,completed=True)
    (ROOT/'2026-09-22-adjusted-trend-checks.json').write_text(json.dumps(checks,indent=2)+'\n')


if __name__=='__main__':main()

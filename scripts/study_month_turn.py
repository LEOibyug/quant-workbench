"""Frozen 18-account turn-of-month strategy with all-session exact controls."""
import gzip
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from month_turn_forecasts import calendar,forecasts
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results

ROOT=Path('docs/research-results')


def main():
    flags,next_day=calendar('2023-03-01','2023-05-01')
    assert all(flags[d] for d in ['2023-03-31','2023-04-03','2023-04-04','2023-04-05'])
    assert not flags['2023-03-30'] and not flags['2023-04-06'] and next_day['2023-04-06']=='2023-04-10'
    base=json.loads(gzip.decompress((ROOT/'2026-09-22-eg-allocation.full.json.gz').read_bytes()))['results']
    ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    paths=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];checks=[];diagnostics=[];hashes={str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    for pool,path in paths.items():
        f=pd.read_parquet(path);start,end='2022-09-01','2025-09-01';hashes[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        history=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=history[0])&(f.day<end)]
        maps,diag,obs=forecasts(f,rates,start,end)
        days=sorted(f.loc[f.day>=start,'day'].unique());cut=days[len(days)//2]
        short,_,short_obs=forecasts(f[f.day<=cut],rates,start,end)
        for method in maps:assert short[method]=={k:v for k,v in maps[method].items() if k[0]<=cut}
        assert short_obs==[p for p in obs if p['day']<=cut]
        diagnostics.append(dict(pool=pool,summary=diag,observations=obs))
        for mult in [1,2]:
            ref=next(r for r in base if (r['pool'],r['cost_multiplier'],r['method'])==(pool,mult,'fixed'))
            cfg=PositionConfig(**ref['config'])
            for method,mapping in maps.items():
                book=CashInterestBook(rates)
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book)
                if method=='always':
                    for key in ['metrics','curve','trades','contributions']:assert r[key]==ref[key]
                for p in r['curve']:
                    pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,cash_return_pct=ref['cash_return_pct'],**{k:r[k] for k in ['config','metrics','curve','contributions','trades']}))
                save_results(ROOT/'2026-09-22-month-turn.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),flush=True)
        checks.append(dict(pool=pool,prefix_exact=True,always_control_exact=True,complement_identity=True,conservation=True))
    assert len(rows)==18
    save_results(ROOT/'2026-09-22-month-turn.json',rows,completed=True)
    (ROOT/'2026-09-22-month-turn-checks.json').write_text(json.dumps(dict(checks=checks,input_sha256=hashes,diagnostics=diagnostics),indent=2)+'\n')


if __name__=='__main__':main()

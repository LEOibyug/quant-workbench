"""Frozen 72-account cash-consistent trend study; all outcomes retained."""
import hashlib,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from cash_interest_book import CashInterestBook
from excess_trend_forecasts import forecasts
from study_tsmom import forecasts as original_forecasts
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def main():
    ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json');rate_snapshot=json.loads(ratepath.read_text())
    rates={r['effectiveDate']:r['percentRate'] for r in rate_snapshot['refRates']}
    base=json.loads((ROOT/'2026-09-22-liability-transfer-temporal.json').read_text())['results']
    paths=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];checks=[];pure=[];hashes={str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    for pool,path in paths.items():
        all_data=pd.read_parquet(path);hashes[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for start,end in [('2022-09-01','2023-09-01'),('2023-09-01','2024-09-01'),('2024-09-01','2025-09-01'),('2022-09-01','2025-09-01')]:
            history=sorted(all_data.loc[all_data.day<start,'day'].unique())[-273:]
            f=all_data[(all_data.day>=history[0])&(all_data.day<end)]
            maps=forecasts(f,rates);old=original_forecasts(f)
            assert maps['raw_trend']==old['tsmom'] and maps['inverse_vol']==old['inverse_vol']
            zero=forecasts(f,{d:0 for d in rates});assert zero['excess_trend']==old['tsmom']
            ds=sorted(f.loc[f.day>=start,'day'].unique());cut=ds[len(ds)//2]
            prefix=forecasts(f[f.day<=cut],rates)
            for m in maps:assert prefix[m]=={k:v for k,v in maps[m].items() if k[0]<=cut}
            cash=100000.;cb=CashInterestBook(rates);cb.start(ds)
            for d in ds:cash+=cb.before_open(d,cash)
            pure.append(dict(pool=pool,start=start,end=end,last_close=ds[-1],return_pct=(cash/100000-1)*100))
            for mult in [1,2]:
                cfg=PositionConfig(**next(r['config'] for r in base if r['cost_multiplier']==mult))
                for method,mapping in maps.items():
                    book=CashInterestBook(rates)
                    with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                        r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book)
                    assert np.isclose(sum(x['net_profit'] for x in r['contributions'])+book.income,r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
                    for p in r['curve']:
                        pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                        assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                    rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,**{k:r[k] for k in ['config','metrics','contributions','curve']}))
                    save_results(ROOT/'2026-09-22-excess-trend.json',rows)
                    print(pool,start,end,mult,method,round(r['metrics']['return_pct'],4),flush=True)
            checks.append(dict(pool=pool,start=start,end=end,raw_and_zero_signal_exact=True,prefix_invariant=True,conservation=True))
    assert len(rows)==72
    save_results(ROOT/'2026-09-22-excess-trend.json',rows,completed=True)
    (ROOT/'2026-09-22-excess-trend-checks.json').write_text(json.dumps(dict(checks=checks,pure_cash=pure,hashes=hashes,rate_snapshot=rate_snapshot),indent=2)+'\n')

if __name__=='__main__':main()

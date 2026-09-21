"""Frozen 24-account low earnings variability comparison, including failures."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from audit_earnings_stability import universe
from stability_trading_forecasts import forecasts
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results

ROOT=Path('docs/research-results')


def main():
    ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    base=json.loads((ROOT/'2026-09-22-excess-trend.json').read_text())['results']
    paths=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    entries=universe();hashes={str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()};rows=[];checks=[];coverage={}
    for pool,path in paths.items():
        f=pd.read_parquet(path);start,end='2022-09-01','2025-09-01'
        history=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=history[0])&(f.day<end)]
        for p in [Path(path),*[entries[s]['path'] for s in f.symbol.unique()]]:hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        maps,audit=forecasts(f,start,end);coverage[pool]=audit
        days=sorted(f.loc[f.day>=start,'day'].unique());cut=days[len(days)//2]
        short,sa=forecasts(f[f.day<=cut],start,end)
        assert sa==[a for a in audit if a['day']<=cut]
        for m in maps:assert short[m]=={k:v for k,v in maps[m].items() if k[0]<=cut}
        cash=100000.;cb=CashInterestBook(rates);cb.start(days)
        for d in days:cash+=cb.before_open(d,cash)
        for mult in [1,2]:
            cfg=PositionConfig(**next(r['config'] for r in base if r['cost_multiplier']==mult))
            assert cfg.rebalance_days==20
            for method,mapping in maps.items():
                book=CashInterestBook(rates)
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book)
                neff=[];seen=set()
                for p in r['curve']:
                    pnl=sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                    values=np.array([a['market_value'] for a in p['assets'].values()])
                    if values.sum()>0:neff.append(float(values.sum()**2/(values@values)))
                    seen.update(s for s,q in p['positions'].items() if q>0)
                assert np.isclose(sum(a['net_profit'] for a in r['contributions'])+book.income,r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,cash_return_pct=(cash/100000-1)*100,held_symbols=sorted(seen),average_effective_positions_when_invested=float(np.mean(neff)) if neff else 0.,**{k:r[k] for k in ['config','metrics','curve','contributions','trades']}))
                save_results(ROOT/'2026-09-22-stability-trading.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),flush=True)
        checks.append(dict(pool=pool,prefix_exact=True,source_dates_valid=True,budget_valid=True,conservation=True))
    assert len(rows)==24
    save_results(ROOT/'2026-09-22-stability-trading.json',rows,completed=True)
    (ROOT/'2026-09-22-stability-trading-checks.json').write_text(json.dumps(dict(checks=checks,input_sha256=hashes,coverage=coverage),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()

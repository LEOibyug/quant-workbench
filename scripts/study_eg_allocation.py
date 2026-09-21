"""Frozen three-pool EG/control study, including all costs and failed outcomes."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from eg_allocation import forecasts, project, update
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results, forecasts as legacy_forecasts

ROOT = Path('docs/research-results')


def main():
    w = np.r_[np.full(10,.095),.05]
    assert np.allclose(project(w),w) and np.allclose(update(w,np.ones(11)),w)
    x = np.ones(11); x[0] = 1.1
    assert update(w,x)[0] > w[0]
    q = project(np.r_[100.,np.ones(10)])
    assert np.isclose(q.sum(),1) and q[:-1].max() <= .2 and q[-1] >= .05
    ratepath = Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates = {r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    base = json.loads((ROOT/'2026-09-22-cushion-budget.json').read_text())['results']
    paths = dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows = []; checks = []; hashes = {str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    for pool,path in paths.items():
        f = pd.read_parquet(path); hashes[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        start,end = '2022-09-01','2025-09-01'
        history = sorted(f.loc[f.day<start,'day'].unique())[-273:]
        f = f[(f.day>=history[0])&(f.day<end)]
        maps,audit = forecasts(f,rates,start)
        legacy,_ = legacy_forecasts(f)
        fixed_error = max(abs(v['target_weight']-legacy['equal_risk_scaled'][k]['target_weight']) for k,v in maps['fixed'].items())
        assert fixed_error < 1e-12
        days = sorted(f.loc[f.day>=start,'day'].unique()); cut = days[len(days)//2]
        prefix,_ = forecasts(f[f.day<=cut],rates,start)
        for m in maps: assert prefix[m] == {k:v for k,v in maps[m].items() if k[0]<=cut}
        scaled = f.copy(); symbol = sorted(f.symbol.unique())[0]
        scaled.loc[scaled.symbol==symbol,'close'] *= 10
        sm,_ = forecasts(scaled,rates,start)
        for m in maps:
            assert all(np.isclose(sm[m][k]['target_weight'],v['target_weight'],rtol=1e-10,atol=1e-12) for k,v in maps[m].items())
        cash = 100000.; cb = CashInterestBook(rates); cb.start(days)
        for d in days: cash += cb.before_open(d,cash)
        for mult in [1,2]:
            cfg = PositionConfig(**next(r['config'] for r in base if r['cost_multiplier']==mult))
            for method,mapping in maps.items():
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r = simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=CashInterestBook(rates))
                for p in r['curve']:
                    pnl = sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,cash_return_pct=(cash/100000-1)*100,**{k:r[k] for k in ['config','metrics','contributions','curve','trades']}))
                save_results(ROOT/'2026-09-22-eg-allocation.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),flush=True)
        checks.append(dict(pool=pool,prefix_invariant=True,price_unit_invariant=True,conservation=True,legacy_equal_risk_scaled_max_difference=fixed_error,weight_audit=audit))
    assert len(rows)==12
    save_results(ROOT/'2026-09-22-eg-allocation.json',rows,completed=True)
    (ROOT/'2026-09-22-eg-checks.json').write_text(json.dumps(dict(hashes=hashes,checks=checks),indent=2)+'\n')


if __name__=='__main__': main()

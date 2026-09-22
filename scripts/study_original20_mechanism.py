"""Frozen component and leave-one-out diagnostics; no hyperparameter search."""
import gzip
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path('docs/research-results')
OUT = ROOT / '2026-09-22-original20-mechanism.json'
SOURCE = ROOT / '2026-09-22-joint-cash-dividend.full.json.gz'
DATA = Path('artifacts/research/annual-momentum/original20.parquet')


def main():
    refs = json.loads(gzip.decompress(SOURCE.read_bytes()))['results']
    data = pd.read_parquet(DATA)
    jobs = [(m,c,None) for c in [1,2] for m in ['fixed_ensemble','cross_momentum','channel_trend','residual_reversal']]
    jobs += [('fixed_ensemble',1,s) for s in sorted(data.symbol.unique())]
    rows = []
    for method, cost, excluded in jobs:
        ref = next(r for r in refs if r['method']=='raw' and r['cost_multiplier']==cost)
        cfg = PositionConfig(**{**ref['config'],'model':method})
        frame = data if excluded is None else data[data.symbol != excluded].copy()
        mapping = rule_forecasts(frame,cfg)
        with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
            r = simulate_positions(frame,cfg,'2025-09-01','2026-09-01',daily_bars=True)
        exact = method=='fixed_ensemble' and excluded is None
        if exact:
            for key in ['metrics','curve','contributions']:
                assert r[key] == ref[key], key
        initial = cfg.costs.initial_cash
        for p in r['curve']:
            assert abs(p['equity']-p['cash']-sum(a['market_value'] for a in p['assets'].values())) < 1e-6
            assert abs(p['equity']-initial-sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())) < 1e-6
            if excluded:
                assert excluded not in p['assets']
        assert abs(sum(x['net_profit'] for x in r['contributions'])-(r['metrics']['final_equity']-initial)) < 1e-6
        rows.append(dict(method=method,cost_multiplier=cost,excluded=excluded,checks=dict(exact_control=exact,conservation=True),**{k:r[k] for k in ['config','metrics','curve','contributions']}))
        save_results(OUT,rows)
        print(len(rows),method,cost,excluded,r['metrics']['return_pct'],flush=True)
    assert len(rows)==28
    save_results(OUT,rows,completed=True)
    OUT.with_name(OUT.stem+'-sources.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [SOURCE,DATA,Path(__file__),Path('backend/src/quant_workbench/daily_strategies.py'),Path('backend/src/quant_workbench/position.py')]},indent=2)+'\n')

if __name__=='__main__':
    main()

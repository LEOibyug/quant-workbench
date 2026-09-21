"""Frozen target-phase averaging in one shared cash account, not return averaging."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from asset_growth_forecasts import forecasts
from prepare_transfer12_fundamentals import EXCLUDED
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path('docs/research-results')
DEST = ROOT / '2026-09-22-phase-diversification.json'


def schedules(mapping, days, symbols):
    baseline, hold, phase = {}, {}, {}
    slots = None
    for i, day in enumerate(days):
        raw = np.array([mapping[day, s]['target_weight'] for s in symbols])
        if i == 0:
            slots = np.tile(raw, (20, 1))
        slots[i % 20] = raw
        averaged = slots.mean(axis=0)
        # Independent moving-average identity, including initialization padding.
        history = [np.array([mapping[days[j], s]['target_weight'] for s in symbols])
                   for j in range(max(0, i-19), i+1)]
        history = [np.array([mapping[days[0], s]['target_weight'] for s in symbols])] * (20-len(history)) + history
        assert np.allclose(averaged, np.mean(history, axis=0), rtol=0, atol=1e-15)
        assert np.all(averaged >= 0) and np.max(averaged) <= .2 + 1e-12
        assert averaged.sum() <= .95 + 1e-12
        for j, s in enumerate(symbols):
            if i % 20 == 0:
                baseline[day, s] = mapping[day, s]
            hold[day, s] = dict(mapping[days[i-i % 20], s])
            phase[day, s] = {**mapping[day, s], 'target_weight': float(averaged[j])}
    return dict(baseline=baseline, daily_hold=hold, phase20=phase)


def main():
    controls = json.loads((ROOT/'2026-09-22-asset-pool.json').read_text())['results']
    identities = json.loads((ROOT/'2026-09-21-sec-50-issuers.json').read_text())
    info = json.loads((ROOT/'2026-09-21-transfer12-fundamentals.json').read_text())
    identities.update({s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()})
    kwargs = dict(facts_root=Path('artifacts/research/asset-pool/sec'), identities=identities, excluded=EXCLUDED)
    windows = list(dict.fromkeys((r['pool'], r['start'], r['end_exclusive']) for r in controls))
    rows, checks = [], []
    hashes = {}
    for pool,start,end in windows:
        path = Path('artifacts/research/asset-pool') / (pool+'.parquet')
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        frame = pd.read_parquet(path)
        prior = sorted(frame.loc[frame.day < start,'day'].unique())[-273:]
        frame = frame[(frame.day >= prior[0]) & (frame.day < end)]
        days = sorted(frame.loc[frame.day >= start,'day'].unique())
        symbols = sorted(frame.symbol.unique())
        daily,_,_ = forecasts(frame,start,end,decision_stride=1,**kwargs)
        maps = schedules(daily['low_growth'],days,symbols)
        old,_,_ = forecasts(frame,start,end,**kwargs)
        assert maps['baseline'] == old['low_growth']
        # Truncating future prices must leave all earlier decisions unchanged.
        middle = days[len(days)//2]
        prefix,_,_ = forecasts(frame[frame.day <= middle],start,end,decision_stride=1,**kwargs)
        assert prefix['low_growth'] == {k:v for k,v in daily['low_growth'].items() if k[0] <= middle}
        shorter = schedules(prefix['low_growth'],[d for d in days if d<=middle],symbols)
        for method in maps:
            assert shorter[method] == {k:v for k,v in maps[method].items() if k[0] <= middle}
        for mult in [1,2]:
            ref = next(r for r in controls if (r['pool'],r['start'],r['end_exclusive'],r['method'],r['cost_multiplier']) == (pool,start,end,'low_growth',mult))
            for method,mapping in maps.items():
                cfg = {**ref['config'],'rebalance_days':20 if method=='baseline' else 1}
                with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                    r = simulate_positions(frame,PositionConfig(**cfg),start,end,daily_bars=True)
                if method=='baseline':
                    assert r['metrics']==ref['metrics']
                    assert r['contributions']==ref['contributions']
                rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,
                                 first_halt=next((p['date'] for p in r['curve'] if p['halted']),None),
                                 **{k:r[k] for k in ['config','metrics','contributions','curve']}))
                save_results(DEST,rows)
                print(pool,start,end,mult,method,round(r['metrics']['return_pct'],4),flush=True)
        checks.append(dict(pool=pool,start=start,end=end,baseline_exact=True,prefix_invariant=True,phase_identity=True,weight_bounds=True))
    assert len(rows)==30
    save_results(DEST,rows,completed=True)
    (ROOT/'2026-09-22-phase-diversification-checks.json').write_text(json.dumps(dict(checks=checks,data_sha256=hashes),indent=2)+'\n')

if __name__=='__main__':
    main()

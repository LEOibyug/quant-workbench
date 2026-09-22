"""Frozen execution-only factorial diagnostics; signals and stock pools unchanged."""
import gzip,hashlib,json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')
OUT=ROOT/'2026-09-22-buffer-geometry.json'


def main():
    old=json.loads(gzip.decompress((ROOT/'2026-09-22-trend-pullback.full.json.gz').read_bytes()))['results']
    banded=json.loads(gzip.decompress((ROOT/'2026-09-22-banded-execution.full.json.gz').read_bytes()))['results']
    manifest=json.loads((ROOT/'2026-09-21-annual-momentum-data.json').read_text())
    paths={s:v['path'] for s,v in manifest.items()}
    paths.update(random10_temporal='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12_temporal='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12_temporal='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];hashes={}
    for ref in old:
        if ref['method']!='fixed_ensemble' or ref['policy']!='legacy':continue
        path=Path(paths[ref['pool']]);hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        frame=pd.read_parquet(path);start=ref['start'];end=ref['end_exclusive']
        prior=sorted(frame.loc[frame.day<start,'day'].unique())[-273:]
        frame=frame[(frame.day>=prior[0]) & (frame.day<end)]
        mapping=rule_forecasts(frame,PositionConfig(**ref['config']))
        for variant in ['legacy','banded','pooled_only','fixed_entry','risk','boundary','risk_boundary']:
            cfgdata={**ref['config'],'portfolio_policy':'legacy' if variant=='legacy' else 'banded', 'execution_buffer':variant if variant in ['risk','boundary','risk_boundary'] else 'fixed'}
            if variant in ['pooled_only','fixed_entry']:
                cfgdata['allocation']={**cfgdata['allocation'],'rebalance_band':0}
                if variant=='pooled_only':cfgdata['entry_band']=0
            cfg=PositionConfig(**cfgdata)
            with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                r=simulate_positions(frame,cfg,start,end,daily_bars=True)
            if variant in ['legacy','banded']:
                expected=ref if variant=='legacy' else next(b for b in banded if b['pool']==ref['pool'] and b['cost_multiplier']==ref['cost_multiplier'])
                for key in ['metrics','curve','contributions']:assert r[key]==expected[key],(variant,key)
            for p in r['curve']:
                assert p['cash']>=-1e-6
                assert abs(p['equity']-p['cash']-sum(a['market_value'] for a in p['assets'].values()))<1e-6
                assert abs(p['equity']-100000-sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values()))<1e-6
            assert abs(sum(x['net_profit'] for x in r['contributions'])-r['metrics']['final_equity']+100000)<1e-6
            rows.append(dict(pool=ref['pool'],start=start,end_exclusive=end,method=variant,cost_multiplier=ref['cost_multiplier'],checks=dict(conservation=True,exact_control=variant in ['legacy','banded']),**{k:r[k] for k in ['config','metrics','curve','contributions']}))
            save_results(OUT,rows)
            print(len(rows),ref['pool'],ref['cost_multiplier'],variant,round(r['metrics']['return_pct'],4),r['metrics']['trade_count'],flush=True)
    assert len(rows)==84
    save_results(OUT,rows,completed=True)
    for path in [Path(__file__),Path('backend/src/quant_workbench/position.py')]:hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    OUT.with_name(OUT.stem+'-sources.json').write_text(json.dumps(hashes,indent=2)+'\n')

if __name__=='__main__':main()

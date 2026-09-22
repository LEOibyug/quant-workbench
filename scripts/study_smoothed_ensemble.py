"""Second frozen candidate, same windows/configuration as factorial controls."""
import argparse,hashlib,json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')
OUT=ROOT/'2026-09-22-smoothed-ensemble.json'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--banded',action='store_true')
    args=parser.parse_args()
    global OUT
    method='fixed_ensemble' if args.banded else 'smoothed_ensemble'
    policy='banded' if args.banded else 'legacy'
    if args.banded:OUT=ROOT/'2026-09-22-banded-execution.json'
    controls=json.loads((ROOT/'2026-09-22-trend-pullback.json').read_text())
    assert controls['status']=='completed'
    sources=json.loads((ROOT/'2026-09-21-annual-momentum-data.json').read_text())
    paths={s:v['path'] for s,v in sources.items()}
    paths.update(random10_temporal='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12_temporal='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12_temporal='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows=[];hashes={}
    for base in controls['results']:
        if base['method']!='fixed_ensemble' or base['policy']!='legacy':continue
        path=Path(paths[base['pool']]);hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        frame=pd.read_parquet(path);start=base['start'];end=base['end_exclusive']
        prior=sorted(frame.loc[frame.day<start,'day'].unique())[-273:]
        frame=frame[(frame.day>=prior[0]) & (frame.day<end)]
        cfg=PositionConfig(**{**base['config'],'model':method,'portfolio_policy':policy})
        mapping=rule_forecasts(frame,cfg)
        with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
            r=simulate_positions(frame,cfg,start,end,daily_bars=True)
        for p in r['curve']:
            assert p['cash']>=-1e-6
            assert abs(p['equity']-p['cash']-sum(a['market_value'] for a in p['assets'].values()))<1e-6
            assert abs(p['equity']-100000-sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values()))<1e-6
        assert abs(sum(x['net_profit'] for x in r['contributions'])-r['metrics']['final_equity']+100000)<1e-6
        rows.append(dict(pool=base['pool'],start=start,end_exclusive=end,method=method,policy=policy,cost_multiplier=base['cost_multiplier'],checks=dict(conservation=True),**{k:r[k] for k in ['config','metrics','curve','contributions']}))
        save_results(OUT,rows)
        print(len(rows),base['pool'],base['cost_multiplier'],r['metrics']['return_pct'],r['metrics']['trade_count'],flush=True)
    assert len(rows)==12
    save_results(OUT,rows,completed=True)
    for path in [Path(__file__),Path('backend/src/quant_workbench/daily_strategies.py'),Path('backend/src/quant_workbench/position.py')]:hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    OUT.with_name(OUT.stem+'-sources.json').write_text(json.dumps(hashes,indent=2)+'\n')

if __name__=='__main__':main()

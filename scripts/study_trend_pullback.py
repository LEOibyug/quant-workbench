"""Frozen six-pool factorial comparison of signals and cost-aware execution."""
import gzip, hashlib, json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')
OUT=ROOT/'2026-09-22-trend-pullback.json'


def main():
    refs=json.loads(gzip.decompress((ROOT/'2026-09-22-joint-cash-dividend.full.json.gz').read_bytes()))['results']
    manifest=json.loads((ROOT/'2026-09-21-annual-momentum-data.json').read_text())
    windows=[(s,v['path'],'2025-09-01','2026-09-01') for s,v in manifest.items()]
    windows += [(s,p,'2022-09-01','2025-09-01') for s,p in [
        ('random10_temporal','artifacts/research/annual-momentum/random10-temporal.parquet'),
        ('transfer12_temporal','artifacts/research/transfer12-temporal-2026-09-21/combined.parquet'),
        ('new12_temporal','artifacts/research/liability-transfer-temporal/combined.parquet')]]
    rows=[];sources={}
    for pool,path,start,end in windows:
        sources[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        frame=pd.read_parquet(path)
        prior=sorted(frame.loc[frame.day<start,'day'].unique())[-273:]
        frame=frame[(frame.day>=prior[0]) & (frame.day<end)]
        for cost in [1,2]:
            ref=next(r for r in refs if r['method']=='raw' and r['cost_multiplier']==cost)
            for method in ['fixed_ensemble','trend_reversal']:
                cfg=PositionConfig(**{**ref['config'],'model':method})
                mapping=rule_forecasts(frame,cfg)
                for policy in ['legacy','cost_aware']:
                    cfg=cfg.model_copy(update={'portfolio_policy':policy})
                    with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                        r=simulate_positions(frame,cfg,start,end,daily_bars=True)
                    exact=pool=='original20' and method=='fixed_ensemble' and policy=='legacy'
                    if exact:
                        for k in ['metrics','curve','contributions']:assert r[k]==ref[k],k
                    for p in r['curve']:
                        assert p['cash']>=-1e-6
                        assert abs(p['equity']-p['cash']-sum(a['market_value'] for a in p['assets'].values()))<1e-6
                        assert abs(p['equity']-100000-sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values()))<1e-6
                    assert abs(sum(x['net_profit'] for x in r['contributions'])-r['metrics']['final_equity']+100000)<1e-6
                    rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,policy=policy,cost_multiplier=cost,checks=dict(conservation=True,exact_original=exact),**{k:r[k] for k in ['config','metrics','curve','contributions']}))
                    save_results(OUT,rows)
                    print(len(rows),pool,cost,method,policy,round(r['metrics']['return_pct'],3),flush=True)
    assert len(rows)==48
    save_results(OUT,rows,completed=True)
    for p in ['backend/src/quant_workbench/daily_strategies.py','backend/src/quant_workbench/position.py',__file__]:sources[p]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    OUT.with_name(OUT.stem+'-sources.json').write_text(json.dumps(sources,indent=2)+'\n')

if __name__=='__main__':main()

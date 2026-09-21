"""Frozen new-company transfer; missing facts do not trigger replacements."""
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from asset_growth_forecasts import forecasts
from verified_liability_features import judge
from prepare_liability_transfer import CIKS,CACHE
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')

def main():
    f=pd.read_parquet('artifacts/research/liability-transfer/daily.parquet')
    info=json.loads((ROOT/'2026-09-22-liability-transfer-fundamentals.json').read_text())
    assert info['status']=='completed' and set(f.symbol)==set(CIKS)
    assert all(info['issuers'][s]['current_identity_matched'] for s in CIKS)
    identities={s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()}
    kw=dict(facts_root=CACHE,identities=identities,judge_fn=judge,ratio_key='burden')
    maps,cov,_=forecasts(f,'2025-09-01','2026-09-01',**kw)
    cutoff=cov[len(cov)//2]['day']
    before,bc,_=forecasts(f[f.day<=cutoff],'2025-09-01','2026-09-01',**kw)
    assert bc==[d for d in cov if d['day']<=cutoff]
    for mode in maps:assert before[mode]=={k:v for k,v in maps[mode].items() if k[0]<=cutoff}
    (ROOT/'2026-09-22-liability-transfer-coverage.json').write_text(json.dumps(cov,ensure_ascii=False,indent=2)+'\n')
    base=json.loads((ROOT/'2026-09-22-liability-burden.json').read_text())['results']
    rows=[]
    for mult in [1,2]:
        cfg=next(r['config'] for r in base if r['cost_multiplier']==mult)
        for method,mapping in maps.items():
            with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                r=simulate_positions(f,PositionConfig(**cfg),'2025-09-01','2026-09-01',daily_bars=True)
            rows.append(dict(pool='liability_transfer12',start='2025-09-01',end_exclusive='2026-09-01',method={'low_growth':'low_liability','high_growth':'high_liability','eligible':'eligible'}[method],cost_multiplier=mult,**{k:r[k] for k in ['config','metrics','curve','contributions']}))
            save_results(ROOT/'2026-09-22-liability-transfer.json',rows)
            print(method,mult,r['metrics'],flush=True)
    assert len(rows)==6
    save_results(ROOT/'2026-09-22-liability-transfer.json',rows,completed=True)

if __name__=='__main__':main()

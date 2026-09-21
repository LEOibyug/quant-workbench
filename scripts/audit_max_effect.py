"""Numerical, causal and data-source audit of the frozen MAX candidate."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from max_effect_forecasts import forecasts

ROOT=Path('docs/research-results')

def main():
    days=pd.bdate_range('2020-01-01',periods=85).strftime('%Y-%m-%d').tolist()
    # Max exactly 1%, 2%, 3%; positive drifts in every window.
    rows=[dict(day=d,symbol=s,close=100*(1+r)**i) for i,d in enumerate(days)
          for s,r in [('A',.01),('B',.02),('C',.03)]]
    f=pd.DataFrame(rows)
    _,diag=forecasts(f,days[63],'2021-01-01')
    assert np.allclose(list(diag[0]['max_return'].values()),[.01,.02,.03],rtol=0,atol=1e-14)
    assert diag[0]['selected']['low_max']==['A'] and diag[0]['selected']['high_max']==['C']
    manifest=json.loads((ROOT/'2026-09-21-annual-momentum-data.json').read_text())
    paths=[m['path'] for m in manifest.values()]+[
        'artifacts/research/transfer12-2026-09-21/daily.parquet',
        'artifacts/research/annual-momentum/random10-temporal.parquet',
        'artifacts/research/transfer12-temporal-2026-09-21/combined.parquet']
    checks=[]
    for path in paths:
        f=pd.read_parquet(path)
        ds=sorted(f.day.unique()); start=ds[273]; end='2026-09-01'
        maps,d=forecasts(f,start,end)
        cut=d[len(d)//2]['day']
        before,bd=forecasts(f[f.day<=cut],start,end)
        assert bd==[x for x in d if x['day']<=cut]
        for mode in maps: assert before[mode]=={k:v for k,v in maps[mode].items() if k[0]<=cut}
        scaled=f.copy(); scaled['close']*=7
        mm,dd=forecasts(scaled,start,end)
        assert [x['selected'] for x in d]==[x['selected'] for x in dd]
        for mode in maps:
            assert list(maps[mode])==list(mm[mode])
            assert all(np.isclose(v['target_weight'],mm[mode][k]['target_weight'],rtol=1e-10,atol=1e-12) for k,v in maps[mode].items())
        assert all(not(set(x['selected']['low_max']) & set(x['selected']['high_max'])) for x in d)
        checks.append(dict(path=path,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),prefix_invariant=True,price_unit_invariant=True,groups_disjoint=True))
    (ROOT/'2026-09-22-max-effect-checks.json').write_text(json.dumps(dict(synthetic_formula=True,checks=checks),indent=2)+'\n')
    print('Synthetic simple-return formula and six input-file prefix/unit audits passed')

if __name__=='__main__':main()

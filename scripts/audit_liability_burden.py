"""Point-in-time and same-filing checks for the liability burden proxy."""
import copy
import hashlib
import json
from pathlib import Path
import pandas as pd
from asset_growth_forecasts import forecasts
from liability_burden_features import judge
from prepare_transfer12_fundamentals import EXCLUDED

ROOT=Path('docs/research-results')

def main():
    ids=json.loads((ROOT/'2026-09-21-sec-50-issuers.json').read_text())
    info=json.loads((ROOT/'2026-09-21-transfer12-fundamentals.json').read_text())
    ids.update({s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()})
    factsroot=Path('artifacts/research/asset-pool/sec')
    checks=[]; examples=[]; hashes={}
    for symbol in sorted(ids):
        path=factsroot/(symbol+'-facts.json')
        if not path.exists():continue
        facts=json.loads(path.read_text());hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for cutoff in ['2022-09-01','2023-09-01','2024-09-01','2025-09-01']:
            verified=ids[symbol]['identity_verified'] and symbol not in EXCLUDED
            r=judge(facts,symbol,cutoff,verified)
            future=copy.deepcopy(facts)
            for values in future['facts'].get('us-gaap',{}).values():
                for entries in values.get('units',{}).values():
                    for item in entries:
                        if item.get('filed','9999')>=cutoff:item['val']=999999999999999
            assert judge(future,symbol,cutoff,verified)==r
            if r['computable']:
                assert len({v['end'] for v in r['sources'].values()})==1
                assert all(v['filed']<cutoff and v['accn']==r['accession'] for v in r['sources'].values())
                missing=copy.deepcopy(facts);del missing['facts']['us-gaap']['Liabilities']
                assert not judge(missing,symbol,cutoff,verified)['computable']
                conflict=copy.deepcopy(facts)
                bad={k:v for k,v in r['sources']['Liabilities'].items() if k!='tag'};bad['val']+=1
                conflict['facts']['us-gaap']['Liabilities']['units']['USD'].append(bad)
                assert not judge(conflict,symbol,cutoff,verified)['computable']
            checks.append(dict(symbol=symbol,asof=cutoff,computable=r['computable'],reason=r['reason'],future_invariant=True))
            if symbol in ('AAPL','USB','ABT') and cutoff=='2025-09-01':examples.append(r)
    data=Path('artifacts/research/asset-pool/merged62.parquet');frame=pd.read_parquet(data)
    kw=dict(facts_root=factsroot,identities=ids,excluded=EXCLUDED,judge_fn=judge,ratio_key='burden')
    maps,diag,_=forecasts(frame,'2025-09-01','2026-09-01',**kw)
    cut=diag[len(diag)//2]['day'];before,bd,_=forecasts(frame[frame.day<=cut],'2025-09-01','2026-09-01',**kw)
    assert bd==[d for d in diag if d['day']<=cut]
    for mode in maps:assert before[mode]=={k:v for k,v in maps[mode].items() if k[0]<=cut}
    hashes[str(data)]=hashlib.sha256(data.read_bytes()).hexdigest()
    (ROOT/'2026-09-22-liability-burden-checks.json').write_text(json.dumps(dict(checks=checks,real_price_prefix=True,missing_rejected=True,conflict_rejected=True,sha256=hashes),ensure_ascii=False,indent=2)+'\n')
    (ROOT/'2026-09-22-liability-burden-judgments.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n')
    print('Audited',len(checks),'issuer-dates; computable',sum(c['computable'] for c in checks))

if __name__=='__main__':main()

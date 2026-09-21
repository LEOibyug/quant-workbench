"""Audit current plus noncurrent liabilities without changing trading eligibility."""
import hashlib
import json
from pathlib import Path
from datetime import date

ROOT=Path('docs/research-results')
TAGS=['Assets','Liabilities','LiabilitiesCurrent','LiabilitiesNoncurrent']


def snapshot(facts,cutoff):
    gaap=facts.get('facts',{}).get('us-gaap',{})
    def rows(tag):
        return [dict(r,tag=tag) for r in gaap.get(tag,{}).get('units',{}).get('USD',[])
                if r.get('form') in ['10-K','10-K/A'] and r.get('filed','9999')<cutoff
                and r.get('end','9999')<cutoff and 'start' not in r and r.get('accn')]
    ar=rows('Assets')
    if not ar:return dict(status='missing_assets')
    latest=max(ar,key=lambda r:(r['end'],r['filed'],r['accn']))
    end,accn=latest['end'],latest['accn']
    sources={};conflicts=[]
    for t in TAGS:
        rr=[r for r in rows(t) if r['end']==end and r['accn']==accn]
        if len({r['val'] for r in rr})>1:conflicts.append(t)
        elif rr:sources[t]=rr[0]
    out=dict(asof=cutoff,end=end,accession=accn,sources=sources,conflicts=conflicts)
    if conflicts:return dict(out,status='conflict')
    if (date.fromisoformat(cutoff)-date.fromisoformat(end)).days>550:return dict(out,status='stale')
    if sources['Assets']['val']<=0:return dict(out,status='invalid_assets')
    pair=all(t in sources for t in TAGS[2:])
    if not pair:return dict(out,status='direct_only' if 'Liabilities' in sources else 'missing_components')
    if any(sources[t]['val']<0 for t in TAGS[2:]):return dict(out,status='negative_component')
    total=sum(sources[t]['val'] for t in TAGS[2:])
    delta=total-sources['Liabilities']['val'] if 'Liabilities' in sources else None
    return dict(out,status=('exact_reconciliation' if delta==0 else 'reconciliation_difference') if delta is not None else 'derived_candidate',component_total=total,direct_difference=delta,candidate_burden=total/sources['Assets']['val'])


def main():
    ids=json.loads((ROOT/'2026-09-21-sec-50-issuers.json').read_text())
    info=json.loads((ROOT/'2026-09-21-transfer12-fundamentals.json').read_text())
    ids.update({s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()})
    from quality_value_features import EXCLUDED
    from prepare_transfer12_fundamentals import EXCLUDED as NEW_EXCLUDED
    rows=[];hashes={};definitions={}
    for s in sorted(ids):
        path=Path('artifacts/research/asset-pool/sec')/(s+'-facts.json')
        if not path.exists():continue
        f=json.loads(path.read_text());hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for t in TAGS:
            tag=f['facts'].get('us-gaap',{}).get(t)
            if tag:definitions[t]={k:tag.get(k) for k in ['label','description']}
        for cutoff in ['2022-09-01','2023-09-01','2024-09-01','2025-09-01']:
            r=snapshot(f,cutoff)
            import copy
            future=copy.deepcopy(f)
            for v in future['facts'].get('us-gaap',{}).values():
                for series in v.get('units',{}).values():
                    for x in series:
                        if x.get('filed','9999')>=cutoff:x['val']=1e18
            assert snapshot(future,cutoff)==r
            for v in r.get('sources',{}).values():assert v['filed']<cutoff and v['end']==r['end'] and v['accn']==r['accession']
            rows.append(dict(symbol=s,scope_eligible=ids[s]['identity_verified'] and s not in EXCLUDED|set(NEW_EXCLUDED),**r))
    from collections import Counter
    summary=dict(all=dict(Counter(r['status'] for r in rows)),in_scope=dict(Counter(r['status'] for r in rows if r['scope_eligible'])))
    out=dict(summary=summary,rows=rows,sha256=hashes,definitions=definitions,future_invariant=True,source_dates_checked=True,production_changed=False)
    (ROOT/'2026-09-22-liability-components.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary))
    print('Candidates',[(r['symbol'],r['asof'],r['candidate_burden']) for r in rows if r['scope_eligible'] and r['status']=='derived_candidate'])

if __name__=='__main__':main()

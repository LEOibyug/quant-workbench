"""Frozen 74-issuer coverage and next-year earnings-error mechanism audit."""
import argparse
import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import numpy as np
from earnings_stability import annuals, judge
from quality_value_features import EXCLUDED
from prepare_transfer12_fundamentals import EXCLUDED as TRANSFER_EXCLUDED

ROOT = Path('docs/research-results')


def universe():
    ids = json.loads((ROOT/'2026-09-21-sec-50-issuers.json').read_text())
    entries = {s:dict(path=Path('artifacts/research/asset-pool/sec')/(s+'-facts.json'),eligible=v['identity_verified'] and s not in EXCLUDED) for s,v in ids.items()}
    for name,folder in [('2026-09-21-transfer12-fundamentals.json','asset-pool/sec'),('2026-09-22-liability-transfer-fundamentals.json','liability-transfer-sec')]:
        info = json.loads((ROOT/name).read_text())['issuers']
        entries.update({s:dict(path=Path('artifacts/research')/folder/(s+'-facts.json'),eligible=v['current_identity_matched'] and s not in TRANSFER_EXCLUDED) for s,v in info.items()})
    assert len(entries)==74
    return entries


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--symbol'); parser.add_argument('--date',default='2025-09-01'); args=parser.parse_args()
    entries = universe()
    if args.symbol:
        s=args.symbol.upper();e=entries.get(s)
        result=judge(json.loads(e['path'].read_text()) if e and e['path'].exists() else {},s,args.date,bool(e and e['eligible']))
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    rows=[];hashes={}; checks=0
    for s,e in entries.items():
        facts=json.loads(e['path'].read_text());hashes[str(e['path'])]=hashlib.sha256(e['path'].read_bytes()).hexdigest()
        future=annuals(facts,'2026-09-22')
        for cutoff in ['2022-09-01','2023-09-01','2024-09-01','2025-09-01']:
            r=judge(facts,s,cutoff,e['eligible'])
            altered=copy.deepcopy(facts)
            for tag in ['Assets','NetIncomeLoss']:
                for q in altered.get('facts',{}).get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[]):
                    if q.get('filed','9999')>=cutoff: q['val']=1e99
            assert r==judge(altered,s,cutoff,e['eligible'])
            checks+=1
            if r['computable']:
                candidates=[q for q in future if 330 <= (date.fromisoformat(q['end'])-date.fromisoformat(r['last_end'])).days <= 400]
                if len(candidates)==1 and candidates[0]['computable']:
                    label=candidates[0]
                    r['outcome']=dict(next_annual=label,absolute_error=abs(label['ratio']-r['last_ratio']))
                else: r['outcome_missing']='下一年度未公开、字段冲突或无法唯一匹配'
            rows.append(r)
    summary=[]
    for cutoff in sorted({r['asof'] for r in rows}):
        cohort=[r for r in rows if r['asof']==cutoff and r['computable']]
        if len(cohort)<9: continue
        low,high=np.quantile([r['volatility'] for r in cohort],[1/3,2/3])
        if low==high: continue
        for r in cohort:r['group']='low' if r['volatility']<=low else 'high' if r['volatility']>=high else 'middle'
        for group in ['low','middle','high']:
            members=[r for r in cohort if r['group']==group];known=[r for r in members if 'outcome' in r]
            errors=[r['outcome']['absolute_error'] for r in known]
            summary.append(dict(asof=cutoff,group=group,eligible=len(members),outcomes=len(known),missing_outcomes=len(members)-len(known),median_absolute_error=float(np.median(errors)) if errors else None,mean_absolute_error=float(np.mean(errors)) if errors else None,mean_historical_ratio=float(np.mean([r['mean_ratio'] for r in members])),low_threshold=float(low),high_threshold=float(high)))
    payload=dict(rows=rows,summary=summary,input_sha256=hashes,future_filing_perturbation_checks=checks,status='completed',formal_applicability='证据不足')
    (ROOT/'2026-09-22-earnings-stability.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()

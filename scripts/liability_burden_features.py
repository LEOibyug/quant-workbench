"""Total liabilities/assets, not interest-bearing debt or failure probability."""
import argparse
import json
from datetime import date
from pathlib import Path
from quality_value_features import EXCLUDED


def judge(facts,symbol,cutoff,verified=False):
    date.fromisoformat(cutoff)
    base=dict(symbol=symbol,asof=cutoff,status='证据不足',validated=False,computable=False)
    if not verified or symbol in EXCLUDED:
        return dict(base,reason='身份或会计范围未通过')
    def rows(tag):
        return [dict(r,tag=tag) for r in facts.get('facts',{}).get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[])
                if r.get('form') in ('10-K','10-K/A') and r.get('filed','9999')<cutoff
                and r.get('end','9999')<cutoff and 'start' not in r and r.get('accn')]
    assets=rows('Assets')
    if not assets: return dict(base,reason='缺已公开年度资产')
    latest=max(assets,key=lambda r:(r['end'],r['filed'],r['accn']))
    end,accn=latest['end'],latest['accn']
    if (date.fromisoformat(cutoff)-date.fromisoformat(end)).days>550:
        return dict(base,reason='最新年度资产陈旧')
    sources={}
    for tag in ['Assets','Liabilities']:
        rr=[r for r in rows(tag) if r['end']==end and r['accn']==accn]
        if not rr: return dict(base,reason='同申报同日缺'+tag)
        if len({r['val'] for r in rr})!=1: return dict(base,reason='同申报同字段值冲突:'+tag)
        sources[tag]=rr[0]
    a,l=sources['Assets']['val'],sources['Liabilities']['val']
    if a<=0 or l<0: return dict(base,reason='资产非正或负债为负')
    return dict(base,computable=True,burden=l/a,accession=accn,sources=sources,
                reason='负债负担可计算，非破产概率；排名依赖股票池，策略适用性未验证')


def main():
    p=argparse.ArgumentParser();p.add_argument('--symbol',required=True);p.add_argument('--date',required=True)
    a=p.parse_args();s=a.symbol.upper()
    root=Path('docs/research-results')
    ids=json.loads((root/'2026-09-21-sec-50-issuers.json').read_text())
    new=json.loads((root/'2026-09-21-transfer12-fundamentals.json').read_text())
    from prepare_transfer12_fundamentals import EXCLUDED as NEW_EXCLUDED
    ids.update({s:dict(identity_verified=v['current_identity_matched']) for s,v in new['issuers'].items()})
    path=Path('artifacts/research/asset-pool/sec')/(s+'-facts.json')
    print(json.dumps(judge(json.loads(path.read_text()) if path.exists() else {},s,a.date,
                           ids.get(s,{}).get('identity_verified',False) and s not in NEW_EXCLUDED),ensure_ascii=False,indent=2))

if __name__=='__main__':main()

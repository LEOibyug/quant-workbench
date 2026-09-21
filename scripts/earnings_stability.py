"""Auditable first-filing earnings variability, not stock-return suitability."""
from datetime import date
import math
import numpy as np


def annuals(facts, cutoff):
    date.fromisoformat(cutoff)
    def rows(tag):
        return [dict(r, tag=tag) for r in facts.get('facts',{}).get('us-gaap',{}).get(tag,{}).get('units',{}).get('USD',[])
                if r.get('form')=='10-K' and r.get('filed','9999')<cutoff and r.get('end','9999')<cutoff and r.get('accn')]
    assets = [r for r in rows('Assets') if 'start' not in r]
    income = [r for r in rows('NetIncomeLoss') if 'start' in r and 330 <= (date.fromisoformat(r['end'])-date.fromisoformat(r['start'])).days <= 400]
    result = []
    for end in sorted({r['end'] for r in assets}):
        first = min((r for r in assets if r['end']==end),key=lambda r:(r['filed'],r['accn']))
        accn = first['accn']
        a = [r for r in assets if r['end']==end and r['accn']==accn]
        n = [r for r in income if r['end']==end and r['accn']==accn]
        entry = dict(end=end, accession=accn, computable=False, sources=dict(assets=a,income=n))
        if not n: entry['reason']='最早资产申报缺同年全年NetIncomeLoss'
        elif len({r['val'] for r in a})!=1 or len({(r['start'],r['val']) for r in n})!=1:
            entry['reason']='同申报数值或年度起点冲突'
        elif any(not math.isfinite(r['val']) for r in a+n) or a[0]['val']<=0:
            entry['reason']='非有限字段或资产非正'
        else:
            entry.update(computable=True,ratio=n[0]['val']/a[0]['val'])
        result.append(entry)
    return result


def judge(facts, symbol, cutoff, eligible=True):
    base = dict(symbol=symbol,asof=cutoff,status='证据不足',validated=False,computable=False)
    if not eligible: return dict(base,reason='既定会计范围或当前身份条件未通过')
    annual = annuals(facts,cutoff)[-5:]
    base['annual_sources'] = annual
    if len(annual)!=5: return dict(base,reason='不足五个年度')
    ends = [date.fromisoformat(r['end']) for r in annual]
    if (date.fromisoformat(cutoff)-ends[-1]).days>550 or any(not 330 <= (b-a).days <= 400 for a,b in zip(ends,ends[1:])):
        return dict(base,reason='年度陈旧或不连续')
    if not all(r['computable'] for r in annual): return dict(base,reason='至少一个年度口径缺失或冲突')
    values = [r['ratio'] for r in annual]
    return dict(base,computable=True,volatility=float(np.std(values,ddof=1)),mean_ratio=float(np.mean(values)),positive_years=sum(v>0 for v in values),last_ratio=values[-1],last_end=annual[-1]['end'],reason='仅财务波动可计算，尚未证明股票策略适用')

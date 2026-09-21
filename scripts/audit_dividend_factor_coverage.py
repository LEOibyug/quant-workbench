"""Vendor-internal consistency audit, never issuer verification or live cash credit."""
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal
import hashlib,json,os
from pathlib import Path
import httpx
import numpy as np
import pandas as pd
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.providers import _get
from prepare_liability_transfer import CIKS
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/dividend-factor-new12')


def main():
    CACHE.mkdir(parents=True,exist_ok=True);sources=[];events={}
    old=ROOT/'2026-09-22-dividend-audit.json'
    for e in json.loads(old.read_text())['events']:events[e['id']]=e
    sources.append(dict(path=str(old),sha256=hashlib.sha256(old.read_bytes()).hexdigest()))
    headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']}
    # Existing COP pages are reused; only the eleven other new symbols are requested.
    symbols=sorted(set(CIKS)-{'COP'})
    for path in sorted(Path('artifacts/research/cop-dividends/api').glob('*.json')):
        payload=json.loads(path.read_text())
        for e in payload.get('corporate_actions',{}).get('cash_dividends',[]):events[e['id']]=e
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    with httpx.Client(timeout=35) as client:
        for start,end in quarter_windows('2021-08-01','2026-09-23'):
            start=str(start);stop=(end-timedelta(days=1)).isoformat()
            params=dict(symbols=','.join(symbols),types='cash_dividend',start=start,end=stop,limit=1000);seen=set()
            for page in range(100):
                path=CACHE/f'{start}-{stop}-{page}.json'
                if path.exists():payload=json.loads(path.read_text())
                else:
                    try:r=_get(client,'https://data.alpaca.markets/v1/corporate-actions',params=params,headers=headers)
                    except httpx.HTTPError:raise ValueError('Dividend transport error') from None
                    if r.status_code!=200:raise ValueError(f'Dividend HTTP {r.status_code}')
                    payload=r.json();path.write_text(json.dumps(payload,indent=2)+'\n')
                sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                for e in payload.get('corporate_actions',{}).get('cash_dividends',[]):
                    assert e['symbol'] in symbols and start<=e['process_date']<=stop
                    if e['id'] in events and e!=events[e['id']]:raise ValueError('Conflicting event ID')
                    events[e['id']]=e
                token=payload.get('next_page_token')
                if not token:break
                if token in seen:raise ValueError('Repeated page token')
                seen.add(token);params['page_token']=token
            else:raise ValueError('Pagination limit')
            print(start,stop,'complete',flush=True)
    raw=pd.read_parquet('artifacts/research/adjusted-trend/raw.parquet');adj=pd.read_parquet('artifacts/research/adjusted-trend/dividend.parquet');rows=[]
    for symbol in sorted(raw.symbol.unique()):
        p=raw[raw.symbol==symbol].set_index('day').sort_index();a=adj[adj.symbol==symbol].set_index('day').sort_index();assert p.index.equals(a.index)
        selected=sorted([e for e in events.values() if e['symbol']==symbol and p.index[0]<e.get('ex_date','')<=p.index[-1]],key=lambda e:(e['ex_date'],e['id']))
        groups=defaultdict(list)
        for e in selected:groups[e['ex_date']].append(e)
        issues=[];steps={}
        for d,ee in groups.items():
            if d not in p.index:issues.append(dict(day=d,reason='non-session exdate'));continue
            i=p.index.get_loc(d)
            if i==0:issues.append(dict(day=d,reason='no preceding close'));continue
            previous=float(p.close.iloc[i-1]);amount=sum(Decimal(str(e['rate'])) for e in ee)
            if any(not np.isfinite(float(e['rate'])) or float(e['rate'])<=0 for e in ee) or amount>=Decimal(str(previous)):
                issues.append(dict(day=d,reason='invalid amount'));continue
            steps[d]=(1-float(amount)/previous,float(np.prod([1-float(e['rate'])/previous for e in ee])))
        result=dict(symbol=symbol,event_count=len(selected),grouped_dates=len(groups),events=selected,multi_component_dates=[d for d,e in groups.items() if len(e)>1],issues=issues,currency_missing=sum(not e.get('currency') for e in selected),special_review=sum(bool(e.get('foreign') or e.get('special') or e.get('sub_type') or e.get('due_bill_on_date') or e.get('due_bill_off_date')) for e in selected),issuer_verified=False,book_ready=False,arithmetic={})
        if not issues:
            fields=['open','high','low','close'];raw_values=p[fields].to_numpy();adjusted=a[fields].to_numpy()
            for mode,j in [('cash_sum',0),('component_product',1)]:
                rel=np.ones(len(p));factor=1.
                for i in range(len(p)-1,0,-1):
                    if p.index[i] in steps:factor*=steps[p.index[i]][j]
                    rel[i-1]=factor
                basis=raw_values*rel[:,None];lo=float(((adjusted-.005)/basis).max());hi=float(((adjusted+.005)/basis).min());anchor=(lo+hi)/2
                result['arithmetic'][mode]=dict(feasible=lo<=hi,anchor_interval=[lo,hi],max_residual_at_interval_midpoint=float(np.abs(adjusted-basis*anchor).max()))
        rows.append(result)
    report=dict(status='completed',sources=sources,rows=rows,note='Same-provider event/price consistency, not independent issuer verification or legal cash entitlement')
    (ROOT/'2026-09-22-dividend-factor-coverage.json').write_text(json.dumps(report,indent=2)+'\n')
    for r in rows:print(r['symbol'],r['event_count'],r['issues'],{k:v['feasible'] for k,v in r['arithmetic'].items()},flush=True)


if __name__=='__main__':main()

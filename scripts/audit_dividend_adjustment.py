"""Read-only MSFT adjusted-bar probe, with issuer-event reconciliation."""
import hashlib,json,os
from pathlib import Path
import httpx
import numpy as np
import pandas as pd
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.providers import _get
from quant_workbench.market_data import schedule
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/adjustment-audit')


def fetch(client,headers,start,end,mode,sources):
    params=dict(symbols='MSFT',timeframe='1Day',start=start,end=end,adjustment=mode,feed='sip',limit=10000)
    bars=[];seen=set()
    for page in range(100):
        path=CACHE/f'{mode}-{start}-{end}-{page}.json'
        if path.exists():payload=json.loads(path.read_text())
        else:
            try:r=_get(client,'https://data.alpaca.markets/v2/stocks/bars',params=params,headers=headers)
            except httpx.HTTPError:raise ValueError('Bar request transport error') from None
            if r.status_code!=200:raise ValueError(f'Bar HTTP {r.status_code}')
            payload=r.json();path.write_text(json.dumps(payload,indent=2)+'\n')
        sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        for b in payload.get('bars',{}).get('MSFT',[]):
            day=pd.Timestamp(b['t']).tz_convert('America/New_York').strftime('%Y-%m-%d')
            if start<=day<end:bars.append(dict(day=day,open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']))
        token=payload.get('next_page_token')
        if not token:break
        if token in seen:raise ValueError('Repeated page')
        seen.add(token);params['page_token']=token
    else:raise ValueError('Pagination limit')
    f=pd.DataFrame(bars).set_index('day').sort_index()
    if f.index.has_duplicates:raise ValueError('Duplicate day')
    assert list(f.index)==list(schedule(start,end).index.strftime('%Y-%m-%d'))
    return f


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']}
    sources=[];frames={}
    with httpx.Client(timeout=30) as client:
        for mode in ['raw','dividend']:
            parts=[]
            for start,end in quarter_windows('2024-08-01','2025-09-01'):
                parts.append(fetch(client,headers,str(start),str(end),mode,sources))
                print(mode,start,end,'complete',flush=True)
            frames[mode]=pd.concat(parts)
            assert not frames[mode].index.has_duplicates
            frames[mode].to_parquet(CACHE/f'{mode}.parquet')
        prefix=fetch(client,headers,'2024-08-01','2024-09-01','dividend',sources)
    raw,adj=frames['raw'],frames['dividend'];assert raw.index.equals(adj.index)
    factor=adj.close/raw.close;change=factor/factor.shift(1)
    issuer_path=ROOT/'2026-09-22-msft-dividends.json'
    events={e['ex_date']:e for e in json.loads(issuer_path.read_text())['events'] if raw.index[0]<e['ex_date']<=raw.index[-1]}
    daily=[]
    for i,day in enumerate(raw.index):
        row=dict(day=day,raw_close=float(raw.close.iloc[i]),adjusted_close=float(adj.close.iloc[i]),factor=float(factor.iloc[i]))
        if i:
            e=events.get(day);amount=float(e['rate']) if e else 0.;previous=float(raw.close.iloc[i-1]);current=float(raw.close.iloc[i])
            row.update(factor_change=float(change.iloc[i]),expected_factor_change=1/(1-amount/previous),adjusted_return=float(adj.close.iloc[i]/adj.close.iloc[i-1]-1),gross_entitlement_return=(current+amount)/previous-1,issuer_event=e)
            row['return_difference_bps']=(row['adjusted_return']-row['gross_entitlement_return'])*10000
        daily.append(row)
    changed=[r for r in daily[1:] if abs(r['factor_change']-1)>1e-6]
    factors=adj[['open','high','low','close']]/raw[['open','high','low','close']]
    report=dict(status='completed',symbol='MSFT',rows=len(raw),sources=sources,issuer_source_sha256=hashlib.sha256(issuer_path.read_bytes()).hexdigest(),volume_equal=bool(raw.volume.equals(adj.volume)),max_ohlc_factor_spread=float((factors.max(axis=1)-factors.min(axis=1)).max()),prefix_max_absolute_price_difference=float((prefix.close-adj.loc[prefix.index,'close']).abs().max()),factor_change_threshold=1e-6,changes=changed,issuer_events_without_detected_change=sorted(set(events)-{r['day'] for r in changed}),unmatched_changes=[r['day'] for r in changed if r['issuer_event'] is None],max_factor_formula_error=float(max(abs(r['factor_change']-r['expected_factor_change']) for r in daily[1:])),daily=daily,limitation='Current vendor snapshot; not point-in-time data or executable total-return account')
    (ROOT/'2026-09-22-dividend-adjustment.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['daily','sources','changes','unmatched_changes']},indent=2))
    print('raw factor flags',len(changed),'unmatched flags',len(report['unmatched_changes']))


if __name__=='__main__':main()

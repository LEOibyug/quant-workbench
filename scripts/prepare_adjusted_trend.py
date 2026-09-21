"""Frozen three-pool vendor snapshots, preserving existing execution prices."""
import gzip,hashlib,json,os
from pathlib import Path
import httpx
import numpy as np
import pandas as pd
from quant_workbench.provider_windows import quarter_windows
from quant_workbench.providers import _get
from quant_workbench.market_data import schedule
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/adjusted-trend')
PATHS=dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')


def main():
    CACHE.mkdir(parents=True,exist_ok=True)
    old={k:pd.read_parquet(p) for k,p in PATHS.items()};symbols=sorted(set().union(*(set(f.symbol) for f in old.values())))
    headers={'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']}
    sources=[];frames={}
    with httpx.Client(timeout=35) as client:
        for mode in ['raw','dividend']:
            records=[]
            for start,end in quarter_windows('2021-08-01','2025-09-01'):
                start,end=str(start),str(end);params=dict(symbols=','.join(symbols),timeframe='1Day',start=start,end=end,feed='sip',adjustment=mode,limit=10000);seen=set()
                for page in range(100):
                    path=CACHE/f'{mode}-{start}-{end}-{page}.json'
                    if path.exists():payload=json.loads(path.read_text())
                    else:
                        try:r=_get(client,'https://data.alpaca.markets/v2/stocks/bars',params=params,headers=headers)
                        except httpx.HTTPError:raise ValueError('Bar transport error') from None
                        if r.status_code!=200:raise ValueError(f'Bar HTTP {r.status_code}')
                        payload=r.json();path.write_text(json.dumps(payload,separators=(',',':'))+'\n')
                    sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                    for s,bars in payload.get('bars',{}).items():
                        assert s in symbols
                        for b in bars:
                            day=pd.Timestamp(b['t']).tz_convert('America/New_York').strftime('%Y-%m-%d')
                            if start<=day<end:records.append(dict(symbol=s,day=day,open=b['o'],high=b['h'],low=b['l'],close=b['c'],volume=b['v']))
                    token=payload.get('next_page_token')
                    if not token:break
                    if token in seen:raise ValueError('Repeated token')
                    seen.add(token);params['page_token']=token
                else:raise ValueError('Pagination limit')
                print(mode,start,end,flush=True)
            frame=pd.DataFrame(records).sort_values(['day','symbol']).reset_index(drop=True)
            assert not frame.duplicated(['day','symbol']).any()
            expected=list(schedule('2021-08-01','2025-09-01').index.strftime('%Y-%m-%d'))
            for s in symbols:assert list(frame.loc[frame.symbol==s,'day'])==expected
            assert np.isfinite(frame[['open','high','low','close','volume']].to_numpy()).all()
            assert (frame[['open','high','low','close']]>0).all().all()
            frame.to_parquet(CACHE/f'{mode}.parquet');frames[mode]=frame
    comparisons=[]
    for pool,f in old.items():
        f=f[(f.day>='2021-08-01')&(f.day<'2025-09-01')]
        merged=f.merge(frames['raw'],on=['day','symbol'],suffixes=('_old','_new'),validate='one_to_one');assert len(merged)==len(f)
        differences={k:int((merged[k+'_old']!=merged[k+'_new']).sum()) for k in ['open','high','low','close','volume']}
        comparisons.append(dict(pool=pool,matched_rows=len(merged),differences=differences,old_path=PATHS[pool],old_sha256=hashlib.sha256(Path(PATHS[pool]).read_bytes()).hexdigest()))
    evidence=ROOT/'2026-09-22-adjusted-trend-bars.json.gz'
    evidence.write_bytes(gzip.compress(json.dumps({k:f.to_dict('records') for k,f in frames.items()},separators=(',',':')).encode(),mtime=0))
    report=dict(status='completed',symbols=symbols,rows_per_mode={k:len(f) for k,f in frames.items()},sources=sources,raw_comparisons=comparisons,evidence=str(evidence),evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())
    (ROOT/'2026-09-22-adjusted-trend-data.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(comparisons,indent=2))


if __name__=='__main__':main()

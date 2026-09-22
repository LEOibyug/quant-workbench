"""Causal rolling information-diffusion diagnostic, before portfolio construction."""
import gzip,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
ROOT=Path('docs/research-results')
OUT=ROOT/'2026-09-22-lead-lag'
HORIZON=5
TRAIN=252


def conditional(x,y,current):
    mx=x.mean(axis=0);sx=np.maximum(x.std(axis=0,ddof=1),1e-12)
    my=y.mean();sy=max(y.std(ddof=1),1e-12)
    z=np.column_stack([(x-mx)/sx,(y-my)/sy])
    cov=LedoitWolf().fit(z).covariance_
    beta=np.linalg.solve(cov[:-1,:-1]+np.eye(x.shape[1])*1e-12,cov[:-1,-1])
    return float(my+sy*((current-mx)/sx)@beta)


def predict(frame,start,end,stop_after=None):
    close=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    opening=frame.pivot(index='day',columns='symbol',values='open').reindex(index=close.index,columns=close.columns)
    assert close.notna().all().all() and opening.notna().all().all()
    assert (close>0).all().all() and (opening>0).all().all()
    dates=list(map(str,close.index));symbols=list(close.columns)
    logs=np.log(close.to_numpy());opens=np.log(opening.to_numpy())
    x=np.full_like(logs,np.nan);x[5:]=logs[5:]-logs[:-5]
    y=np.full_like(logs,np.nan);y[:-5]=logs[5:]-opens[1:-4]
    rows=[]
    for i,day in enumerate(dates):
        if not(start<=day<end) or i<TRAIN+9:continue
        if stop_after is not None and day>stop_after:break
        # Target at t has matured at t+5; equality at today's close is permitted.
        train=np.arange(i-HORIZON-TRAIN+1,i-HORIZON+1)
        assert train[0]>=5 and train[-1]+HORIZON==i
        xx=x[train];current=x[i]
        assert np.isfinite(xx).all() and np.isfinite(y[train]).all()
        predictions={k:[] for k in ['mean','own_market','network','shifted']};scales=[]
        for j,s in enumerate(symbols):
            yy=y[train,j]
            baseline_x=np.column_stack([xx[:,j],(xx.sum(axis=1)-xx[:,j])/(len(symbols)-1)])
            baseline_current=np.array([current[j],(current.sum()-current[j])/(len(symbols)-1)])
            predictions['mean'].append(float(yy.mean()))
            predictions['own_market'].append(conditional(baseline_x,yy,baseline_current))
            predictions['network'].append(conditional(xx,yy,current))
            predictions['shifted'].append(conditional(np.roll(xx,126,axis=0),yy,current))
            scales.append(float(max(yy.var(ddof=1),1e-12)))
        row=dict(day=day,train_first_signal=dates[train[0]],train_last_signal=dates[train[-1]],train_last_maturity=dates[i],symbols=symbols,predictions=predictions,training_variance=scales)
        if i+5<len(dates) and dates[i+5]<end:
            row.update(entry=dates[i+1],maturity=dates[i+5],actual=y[i].tolist())
        rows.append(row)
    return rows


def main():
    manifest=json.loads((ROOT/'2026-09-21-annual-momentum-data.json').read_text())
    windows=[(s,v['path'],'2025-09-01','2026-09-01') for s,v in manifest.items()]
    windows += [(s,p,'2022-09-01','2025-09-01') for s,p in [
        ('random10_temporal','artifacts/research/annual-momentum/random10-temporal.parquet'),
        ('transfer12_temporal','artifacts/research/transfer12-temporal-2026-09-21/combined.parquet'),
        ('new12_temporal','artifacts/research/liability-transfer-temporal/combined.parquet')]]
    pools=[];hashes={}
    for pool,path,start,end in windows:
        path=Path(path);hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        frame=pd.read_parquet(path)
        prior=sorted(frame.loc[frame.day<start,'day'].unique())[-273:]
        frame=frame[(frame.day>=prior[0]) & (frame.day<end)]
        rows=predict(frame,start,end)
        # Real prefix, row-order and price-unit invariance for the first three predictions.
        cutoff=rows[2]['day']
        prefix=frame[frame.day<=cutoff]
        short=predict(prefix,start,end)
        def forecasts_only(items):return [{k:r[k] for k in ['day','symbols','predictions','training_variance','train_last_maturity']} for r in items]
        assert forecasts_only(short)==forecasts_only(rows[:3])
        shuffled=predict(prefix.sample(frac=1,random_state=22),start,end)
        assert forecasts_only(short)==forecasts_only(shuffled)
        scaled=prefix.copy();scaled[['open','close']]*=7
        unit=predict(scaled,start,end)
        for a,b in zip(short,unit,strict=True):
            for method in a['predictions']:assert np.allclose(a['predictions'][method],b['predictions'][method],atol=1e-12,rtol=1e-9)
        pools.append(dict(pool=pool,start=start,end_exclusive=end,rows=rows,checks=dict(prefix=True,row_permutation=True,price_units=True,training_maturity=True)))
        OUT.with_suffix('.full.json.gz').write_bytes(gzip.compress(json.dumps(dict(status='running',pools=pools),separators=(',',':')).encode(),mtime=0))
        print(pool,len(rows),sum('actual' in r for r in rows),flush=True)
    OUT.with_suffix('.full.json.gz').write_bytes(gzip.compress(json.dumps(dict(status='completed',pools=pools),separators=(',',':')).encode(),mtime=0))
    hashes[str(Path(__file__))]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    OUT.with_name(OUT.name+'-sources.json').write_text(json.dumps(hashes,indent=2)+'\n')

if __name__=='__main__':main()

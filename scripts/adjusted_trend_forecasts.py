"""Dividend-adjusted eligibility only; risk estimates remain based on raw prices."""
import numpy as np
from sklearn.covariance import LedoitWolf


def forecasts(frame,adjusted):
    p=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    a=adjusted.pivot(index='day',columns='symbol',values='close').reindex(index=p.index,columns=p.columns)
    if not np.isfinite(a.to_numpy()).all() or (a<=0).any().any():raise ValueError('Missing adjusted prices')
    logs=np.log(p.to_numpy());adj_logs=np.log(a.to_numpy());returns=np.diff(logs,axis=0)
    maps={m:{} for m in ['raw_trend','adjusted_trend']};changes=[]
    for i in range(252,len(p)):
        cov=LedoitWolf().fit(returns[i-63:i]).covariance_+np.eye(p.shape[1])*1e-12
        vol=np.sqrt(np.diag(cov));inverse=1/vol;inverse=np.minimum(.2,.95*inverse/inverse.sum())
        raw_trend=logs[i]-logs[i-252];adjusted_trend=adj_logs[i]-adj_logs[i-252]
        for mode,trend in [('raw_trend',raw_trend),('adjusted_trend',adjusted_trend)]:
            raw=inverse*(trend>0);w=raw*min(1,.1/max(np.sqrt(raw@cov@raw*252),1e-12))
            assert w.min()>=0 and w.max()<=.2+1e-12 and w.sum()<=.95+1e-12
            for j,s in enumerate(p.columns):maps[mode][str(p.index[i]),s]=dict(target_weight=float(w[j]),volatility=float(vol[j]),status='ok')
        for j,s in enumerate(p.columns):
            if (raw_trend[j]>0)!=(adjusted_trend[j]>0):changes.append(dict(day=str(p.index[i]),symbol=s,raw_log_return=float(raw_trend[j]),adjusted_log_return=float(adjusted_trend[j])))
    return maps,changes

"""Annual price trend above lagged cash return, with identical raw-trend controls."""
import numpy as np
from sklearn.covariance import LedoitWolf
from cash_interest_book import CashInterestBook


def forecasts(frame,rates):
    p=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    if not np.isfinite(p.to_numpy()).all() or (p<=0).any().any():raise ValueError('Invalid common prices')
    days=list(p.index);cash=1.;book=CashInterestBook(rates);book.start(days);cash_index=[]
    for day in days:
        cash+=book.before_open(day,cash);cash_index.append(cash)
    logs=np.log(p.to_numpy());ret=np.diff(logs,axis=0);funding=np.log(cash_index)
    maps={k:{} for k in ['inverse_vol','raw_trend','excess_trend']}
    for i in range(252,len(p)):
        cov=LedoitWolf().fit(ret[i-63:i]).covariance_+np.eye(p.shape[1])*1e-12
        vol=np.sqrt(np.diag(cov));inverse=1/vol;inverse=np.minimum(.2,.95*inverse/inverse.sum())
        price_trend=logs[i]-logs[i-252];cash_trend=funding[i]-funding[i-252]
        for mode,raw in [('inverse_vol',inverse),('raw_trend',inverse*(price_trend>0)),('excess_trend',inverse*(price_trend>cash_trend))]:
            w=raw*min(1,.1/max(np.sqrt(raw@cov@raw*252),1e-12))
            assert min(w)>=0 and max(w)<=.2+1e-12 and sum(w)<=.95+1e-12
            for j,s in enumerate(p.columns):maps[mode][str(days[i]),s]=dict(target_weight=float(w[j]),volatility=float(vol[j]),status='ok')
    return maps

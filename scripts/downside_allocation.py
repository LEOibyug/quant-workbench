"""Optimize the portfolio's negative part, not negative parts of individual assets."""
import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
from cash_interest_book import CashInterestBook


def objective(w,x,cov,mode):
    scale=np.diag(cov).mean()
    if mode=='variance': value=w@cov@w;gradient=2*cov@w
    else:
        r=x@w
        selected=np.minimum(r,0) if mode=='downside' else np.maximum(r,0)
        value=np.mean(selected**2);gradient=2*x.T@selected/len(x)
    return value/scale+1e-8*(w@w),gradient/scale+2e-8*w


def allocate(x,cov,mode):
    n=x.shape[1];budget=min(.95,.2*n);initial=np.full(n,budget/n)
    result=minimize(lambda w:objective(w,x,cov,mode),initial,jac=True,method='SLSQP',bounds=[(0,.2)]*n,
                    constraints=[dict(type='eq',fun=lambda w:w.sum()-budget,jac=lambda w:np.ones(n))],
                    options=dict(ftol=1e-10,maxiter=500))
    if not result.success or not np.isfinite(result.x).all() or abs(result.x.sum()-budget)>1e-8 or result.x.min()<-1e-10 or result.x.max()>.2+1e-10:
        raise ValueError('Infeasible optimizer: '+str(result.message))
    assert objective(result.x,x,cov,mode)[0]<=objective(initial,x,cov,mode)[0]+1e-8
    w=np.clip(result.x,0,.2)
    w*=min(1,.1/max(np.sqrt(w@cov@w*252),1e-12))
    return w


def forecasts(frame,rates,start,end):
    p=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    if not np.isfinite(p.to_numpy()).all() or (p<=0).any().any():raise ValueError('Invalid common prices')
    days=list(p.index);cash=1.;index=[];book=CashInterestBook(rates);book.start(days)
    for d in days:cash+=book.before_open(d,cash);index.append(cash)
    values=p.to_numpy();returns=values[1:]/values[:-1]-1
    funding=np.asarray(index[1:])/np.asarray(index[:-1])-1
    excess=returns-funding[:,None]
    decisions=set([d for d in days if start<=d<end][::20]);maps={m:{} for m in ['downside','upside','variance']}
    for i in range(63,len(p)):
        day=days[i]
        if day not in decisions:continue
        cov=LedoitWolf().fit(returns[i-63:i]).covariance_+np.eye(p.shape[1])*1e-12
        for mode in maps:
            w=allocate(excess[i-63:i],cov,mode)
            assert w.sum()<=.95+1e-10 and w.max()<=.2+1e-10
            for j,s in enumerate(p.columns):maps[mode][str(day),s]=dict(target_weight=float(w[j]),volatility=float(np.sqrt(cov[j,j])),status='ok')
    return maps

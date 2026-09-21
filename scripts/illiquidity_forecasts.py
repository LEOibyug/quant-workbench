"""Dollar-volume price-response candidate: causal observations, not suitability proof."""
import argparse
import json
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf


def forecasts(frame,start,end):
    p=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    if p.isna().any().any() or not np.isfinite(p.to_numpy()).all() or (p<=0).any().any():
        raise ValueError('需要完整共同日历与有限正价格')
    days=[str(d) for d in p.index if start<=str(d)<end]
    decisions=set(days[::20])
    syms=list(p.columns)
    if len(syms)<3: raise ValueError('至少需要三支股票')
    v=frame.pivot(index='day',columns='symbol',values='volume').reindex(index=p.index,columns=p.columns)
    if not np.isfinite(v.to_numpy()).all() or (v<=0).any().any(): raise ValueError('需要有限正成交量')
    simple=p.to_numpy()[1:]/p.to_numpy()[:-1]-1
    impact=np.abs(simple)/(p.to_numpy()[1:]*v.to_numpy()[1:])
    logret=np.diff(np.log(p.to_numpy()),axis=0)
    out={k:{} for k in ['low_illiquidity','high_illiquidity','eligible']}
    diagnostics=[]
    for i in range(63,len(p)):
        day=str(p.index[i])
        if day not in decisions: continue
        maxes=np.mean(impact[i-63:i],axis=0)
        order=sorted(range(len(syms)),key=lambda j:(maxes[j],syms[j]))
        n=len(syms)//3
        selected=dict(low_illiquidity=order[:n],high_illiquidity=order[-n:],eligible=list(range(len(syms))))
        if maxes[order[n-1]]>=maxes[order[-n]]: selected={k:[] for k in selected}
        cov=LedoitWolf().fit(logret[i-63:i]).covariance_+np.eye(len(syms))*1e-12
        vol=np.sqrt(np.diag(cov))
        for mode,group in selected.items():
            raw=np.array([1/vol[j] if j in group else 0 for j in range(len(syms))])
            w=np.minimum(.2,min(.95,.2*n)*raw/max(raw.sum(),1e-12))
            w*=min(1,.1/max(np.sqrt(w@cov@w*252),1e-12))
            assert np.min(w)>=0 and np.max(w)<=.2+1e-12 and w.sum()<=min(.95,.2*n)+1e-12
            for j,s in enumerate(syms):
                out[mode][day,s]=dict(target_weight=float(w[j]),volatility=float(vol[j]),status='ok')
        diagnostics.append(dict(day=day,illiquidity_proxy=dict(zip(syms,maxes.tolist())),
                                rank={syms[j]:r+1 for r,j in enumerate(order)},
                                selected={k:[syms[j] for j in v] for k,v in selected.items()}))
    if [r['day'] for r in diagnostics]!=days[::20]: raise ValueError('缺少63交易日预热')
    return out,diagnostics


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prices',required=True)
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--date',required=True)
    a=parser.parse_args(); symbol=a.symbol.upper()
    frame=pd.read_parquet(a.prices)
    pd.Timestamp(a.date)
    frame=frame[frame.day<a.date]
    if frame.empty or symbol not in set(frame.symbol):
        result=dict(symbol=symbol,status='证据不足',reason='股票或历史数据缺失')
    else:
        day=max(frame.day)
        try:
            _,diag=forecasts(frame,day,(pd.Timestamp(day)+pd.Timedelta(days=1)).strftime('%Y-%m-%d'))
        except ValueError as error:
            print(json.dumps(dict(symbol=symbol,asof=a.date,status='证据不足',validated=False,reason=str(error)),ensure_ascii=False,indent=2))
            return
        d=diag[0]
        result=dict(symbol=symbol,asof=a.date,observation_close=day,status='证据不足',validated=False,
                    illiquidity_proxy=d['illiquidity_proxy'][symbol],rank=d['rank'][symbol],pool_size=frame.symbol.nunique(),
                    candidate_group=next((k for k in ['low_illiquidity','high_illiquidity'] if symbol in d['selected'][k]),'middle'),
                    reason='候选排名依赖股票池，尚无已验证适用性；不代表盈利概率',reevaluate='下一交易日或股票池变化')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()

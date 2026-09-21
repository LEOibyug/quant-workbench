"""Fixed pool-relative financial ranks, equal shared budgets before risk scaling."""
import json
import numpy as np
from sklearn.covariance import LedoitWolf
from audit_earnings_stability import universe
from earnings_stability import judge


def forecasts(frame,start,end):
    prices=frame.pivot(index='day',columns='symbol',values='close').sort_index().sort_index(axis=1)
    if not np.isfinite(prices.to_numpy()).all() or (prices<=0).any().any():raise ValueError('Invalid common prices')
    syms=list(prices.columns);entries=universe()
    facts={s:json.loads(entries[s]['path'].read_text()) for s in syms}
    returns=np.diff(np.log(prices.to_numpy()),axis=0)
    days=[str(d) for d in prices.index if start<=str(d)<end];decisions=set(days[::20])
    maps={k:{} for k in ['low_volatility','high_volatility','eligible','low_mean']};audit=[]
    for i in range(63,len(prices)):
        day=str(prices.index[i])
        if day not in decisions:continue
        judgments={s:judge(facts[s],s,day,entries[s]['eligible']) for s in syms}
        eligible=sorted(s for s in syms if judgments[s]['computable'])
        ranked=sorted(eligible,key=lambda s:(judgments[s]['volatility'],s))
        means=sorted(eligible,key=lambda s:(judgments[s]['mean_ratio'],s))
        n=len(eligible)//3
        rejected=n<2 or judgments[ranked[0]]['volatility']==judgments[ranked[-1]]['volatility']
        sets=dict(low_volatility=ranked[:n],high_volatility=ranked[-n:] if n else [],eligible=eligible,low_mean=means[:n])
        if rejected:sets={k:[] for k in sets}
        budget=0. if rejected else min(.95,.2*n)
        cov=LedoitWolf().fit(returns[i-63:i]).covariance_+np.eye(len(syms))*1e-12
        for mode,selected in sets.items():
            w=np.array([budget/len(selected) if s in selected else 0. for s in syms])
            assert np.isclose(sum(w),budget)
            w*=min(1.,.1/max(np.sqrt(w@cov@w*252),1e-12))
            assert min(w)>=0 and max(w)<=.2+1e-12 and sum(w)<=budget+1e-12
            for j,s in enumerate(syms):maps[mode][day,s]=dict(target_weight=float(w[j]),volatility=float(np.sqrt(cov[j,j])),status='ok')
        for r in judgments.values():
            for a in r.get('annual_sources',[]):
                for source in a['sources'].values():
                    assert all(q['filed']<day and q['end']<day for q in source)
        audit.append(dict(day=day,eligible=eligible,selected=sets,budget=budget,rejected=rejected,judgments=judgments))
    return maps,audit

"""Check one-cent rounding feasibility; never infer tradable cash from adjusted bars."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path('docs/research-results');CACHE=Path('artifacts/research/adjustment-audit')


def main():
    path=ROOT/'2026-09-22-dividend-adjustment.json';audit=json.loads(path.read_text())
    raw=pd.read_parquet(CACHE/'raw.parquet');adjusted=pd.read_parquet(CACHE/'dividend.parquet')
    events={x['day']:float(x['issuer_event']['rate']) for x in audit['daily'] if x.get('issuer_event')}
    relative=np.ones(len(raw));product=1.
    for i in range(len(raw)-1,0,-1):
        if raw.index[i] in events:product*=1-events[raw.index[i]]/raw.close.iloc[i-1]
        relative[i-1]=product
    fields=['open','high','low','close'];p=raw[fields].to_numpy();a=adjusted[fields].to_numpy()
    assert np.allclose(a*100,np.round(a*100),atol=1e-8,rtol=0)
    basis=p*relative[:,None]
    # Each rounded observation constrains the same unknown normalization constant.
    low=float(np.max((a-.005)/basis));high=float(np.min((a+.005)/basis))
    feasible=low<=high;anchor=(low+high)/2;error=np.abs(a-basis*anchor)
    # Control: a constant factor with no dividend steps must not explain all bars.
    no_events_low=float(np.max((a-.005)/p));no_events_high=float(np.min((a+.005)/p))
    assert feasible and error.max()<=.005+1e-10 and no_events_low>no_events_high
    exact_close=raw.close.to_numpy()*relative
    exact_return=exact_close[1:]/exact_close[:-1]-1
    entitlement=np.array([(raw.close.iloc[i]+events.get(raw.index[i],0))/raw.close.iloc[i-1]-1 for i in range(1,len(raw))])
    detail=[]
    for i,day in enumerate(raw.index[1:],1):
        if day in events:
            detail.append(dict(day=day,dividend=events[day],unrounded_adjusted_return=float(exact_return[i-1]),gross_entitlement_return=float(entitlement[i-1]),difference_bps=float((exact_return[i-1]-entitlement[i-1])*10000)))
    result=dict(status='completed',input_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [path,CACHE/'raw.parquet',CACHE/'dividend.parquet']},assumed_price_rounding_step=.01,ohlc_observations=int(a.size),issuer_dividend_events=len(events),common_anchor_interval=[low,high],common_anchor_selected_for_audit=anchor,all_observations_within_half_cent=feasible,maximum_absolute_residual_dollars=float(error.max()),no_dividend_step_control_feasible=no_events_low<=no_events_high,unrounded_return_differences=detail,formal_use='arithmetic audit only, not a fitted trading signal or verified total-return account')
    (ROOT/'2026-09-22-adjustment-rounding.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

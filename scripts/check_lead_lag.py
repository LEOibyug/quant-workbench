"""Positive control: a known five-session lead must survive our forecast pipeline."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from study_lead_lag import predict


def main():
    rng=np.random.default_rng(91);n=410
    returns=rng.normal(0,.01,(n,8));returns[5:,-1]=returns[:-5,0]
    close=100*np.exp(np.cumsum(returns,axis=0))
    opening=np.vstack([np.full(8,100.),close[:-1]])
    dates=pd.bdate_range('2023-01-02',periods=n).strftime('%Y-%m-%d')
    frame=pd.concat([pd.DataFrame(dict(day=dates,symbol=s,open=opening[:,j],close=close[:,j])) for j,s in enumerate('ABCDEFGH')],ignore_index=True)
    rows=[r for r in predict(frame,dates[280],dates[-1]) if 'actual' in r]
    mse={m:float(np.mean([(r['predictions'][m][7]-r['actual'][7])**2 for r in rows])) for m in ['mean','own_market','network','shifted']}
    assert mse['network']<.2*mse['mean'] and mse['network']<mse['shifted']
    Path('docs/research-results/2026-09-22-lead-lag-positive-control.json').write_text(json.dumps(dict(seed=91,construction='H daily log returns equal A log returns delayed exactly five sessions; no overnight gap',evaluation_days=len(rows),follower_mse=mse,checks=dict(network_recovers_planted_lead=True)),indent=2)+'\n')
    print(mse)

if __name__=='__main__':main()

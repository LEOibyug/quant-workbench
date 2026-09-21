"""Ex ante calendar gating; next-open targets and separate close-return diagnostic."""
import numpy as np
import pandas as pd
from quant_workbench.market_data import schedule
from eg_allocation import forecasts as base_forecasts
from cash_interest_book import CashInterestBook


def calendar(start,end):
    first=pd.Timestamp(start).replace(day=1)
    finish=pd.Timestamp(end)+pd.offsets.MonthBegin(2)
    days=list(schedule(str(first.date()),str(finish.date())).index.strftime('%Y-%m-%d'))
    flags={}
    for month in sorted({d[:7] for d in days}):
        sessions=[d for d in days if d[:7]==month]
        selected=set(sessions[:3]+sessions[-1:])
        assert len(selected)==4
        flags.update({d:d in selected for d in sessions})
    return flags,dict(zip(days[:-1],days[1:]))


def forecasts(frame,rates,start,end):
    base,_=base_forecasts(frame,rates,start)
    flags,next_day=calendar(str(frame.day.min()),end)
    maps={m:{} for m in ['turn','outside','always']}
    for key,row in base['fixed'].items():
        active=flags[next_day[key[0]]]
        for method,on in [('turn',active),('outside',not active),('always',True)]:
            maps[method][key]={**row,'target_weight':row['target_weight'] if on else 0.}
        assert np.isclose(maps['turn'][key]['target_weight']+maps['outside'][key]['target_weight'],row['target_weight'])
    prices=frame.pivot(index='day',columns='symbol',values='close').sort_index()
    days=list(prices.index);book=CashInterestBook(rates);book.start(days);cash=1.;index=[]
    for d in days:cash+=book.before_open(d,cash);index.append(cash)
    excess=np.log(np.mean(prices.to_numpy()[1:]/prices.to_numpy()[:-1],axis=1))-np.diff(np.log(index))
    observations=[dict(day=str(d),turn=flags[d],excess_log_return=float(excess[i])) for i,d in enumerate(days[1:]) if start<=str(d)<end]
    diagnostic=[]
    for method,active in [('turn',True),('outside',False)]:
        selected=[p['excess_log_return'] for p in observations if p['turn']==active]
        diagnostic.append(dict(method=method,sessions=len(selected),mean_excess_log_bps=float(np.mean(selected)*10000)))
    return maps,diagnostic,observations

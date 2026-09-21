"""Synchronized circular blocks across a fixed, explicitly limited 84-column family."""
import hashlib,json
from pathlib import Path
import numpy as np
from cash_interest_book import CashInterestBook
ROOT=Path('docs/research-results')
SPECS=[('eg-allocation','eg','fixed'),('shadow-reentry','recovery','permanent'),('stability-trading','low_volatility','eligible'),('month-turn','turn','always'),('downside-allocation','downside','variance'),('excess-trend','excess_trend','raw_trend'),('cushion-budget','cushion','constant30')]


def log_returns(equity,initial):
    values=np.asarray(equity,dtype=float)
    if not np.isfinite(values).all() or (values<=0).any() or initial<=0:raise ValueError('Invalid equity')
    result=np.log(values/np.r_[initial,values[:-1]])
    assert np.isclose(result.sum(),np.log(values[-1]/initial),atol=1e-12)
    return result


def indices(n,rng,block=21):
    starts=rng.integers(0,n,size=int(np.ceil(n/block)))
    return ((starts[:,None]+np.arange(block))%n).ravel()[:n]


def main():
    assert np.allclose(log_returns([110,121],100),np.log([1.1,1.1]))
    rng=np.random.default_rng(20260922)
    probe=indices(751,rng)
    assert len(probe)==751 and probe.min()>=0 and probe.max()<751
    for i in range(0,751,21):assert np.all(np.diff(probe[i:i+21])%751==1)
    ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    hashes={str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    labels=[];columns=[];dates=None;cash_log=None;cash_final=None
    for study,method,control in SPECS:
        path=ROOT/f'2026-09-22-{study}.json';hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        payload=json.loads(path.read_text());assert payload['status']=='completed'
        for cost in [1,2]:
            for pool in ['random10','transfer12','new12']:
                def find(m):
                    matches=[r for r in payload['results'] if (r['method'],r['cost_multiplier'],r['pool'],r['start'],r['end_exclusive'])==(m,cost,pool,'2022-09-01','2025-09-01')]
                    assert len(matches)==1
                    return matches[0]
                candidate,baseline=find(method),find(control)
                ds=[p['date'] for p in candidate['curve']]
                assert ds==[p['date'] for p in baseline['curve']]
                assert candidate['config']==baseline['config']
                if dates is None:
                    dates=ds;cash=100000.;book=CashInterestBook(rates);book.start(ds);equity=[]
                    for d in ds:cash+=book.before_open(d,cash);equity.append(cash)
                    cash_log=log_returns(equity,100000.);cash_final=(cash/100000-1)*100
                assert dates==ds and len(dates)==751
                assert candidate['config']['costs']['initial_cash']==100000
                own=log_returns([p['equity'] for p in candidate['curve']],100000.)
                other=log_returns([p['equity'] for p in baseline['curve']],100000.)
                for comparator,series,terminal in [(control,other,baseline['metrics']['return_pct']),('cash',cash_log,cash_final)]:
                    columns.append(own-series)
                    labels.append(dict(study=study,method=method,baseline=comparator,pool=pool,cost_multiplier=cost,terminal_return_difference_pp=candidate['metrics']['return_pct']-terminal))
    x=np.asarray(columns).T;assert x.shape==(751,84)
    mean=x.mean(axis=0);rng=np.random.default_rng(20260922)
    boot=np.asarray([x[indices(len(x),rng)].mean(axis=0) for _ in range(2000)])
    se=boot.std(axis=0,ddof=1)
    if (se<=1e-15).any():raise ValueError('Degenerate comparison')
    q=float(np.quantile(np.max(np.abs((boot-mean)/se),axis=1),.95))
    lower=mean-q*se;upper=mean+q*se
    for j,label in enumerate(labels):label.update(annualized_log_difference_pp=float(mean[j]*25200),simultaneous_95_interval_pp=[float(lower[j]*25200),float(upper[j]*25200)])
    grouped=[]
    for study,method,control in SPECS:
        for baseline in [control,'cash']:
            selected=[j for j,l in enumerate(labels) if l['study']==study and l['baseline']==baseline]
            assert len(selected)==6
            grouped.append(dict(study=study,baseline=baseline,positive_point_estimates=int(sum(mean[j]>0 for j in selected)),positive_simultaneous_lower_bounds=int(sum(lower[j]>0 for j in selected)),weakest_annualized_log_difference_pp=float(min(mean[selected])*25200),weakest_simultaneous_lower_bound_pp=float(min(lower[selected])*25200)))
    # Verify duplication preserves every sampled mean using the same indices.
    sample=indices(751,np.random.default_rng(13));duplicate=np.c_[x[:,0],x[:,0]][sample].mean(axis=0)
    assert duplicate[0]==duplicate[1]
    result=dict(source_sha256=hashes,dates=dates,block=21,replicates=2000,seed=20260922,critical_max_absolute_statistic=q,cash_return_pct=cash_final,comparisons=labels,groups=grouped,checks=dict(telescoping=True,common_calendar=True,circular_blocks=True,duplicate_columns=True),note='Limited-family descriptive bootstrap; not full-search correction, not independent confirmation, not reexecuted paths')
    (ROOT/'2026-09-22-recent-uncertainty.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(grouped,indent=2));print('positive simultaneous bounds',sum(lower>0),'of',len(lower))


if __name__=='__main__':main()

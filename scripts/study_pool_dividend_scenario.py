"""Explicit gross-USD cash-right scenarios; raw flags retained, never verified data."""
from collections import defaultdict
from decimal import Decimal
import gzip,hashlib,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from prepare_adjusted_trend import PATHS,CACHE
from adjusted_trend_forecasts import forecasts
from cash_dividend_book import CashDividendBook
from cash_interest_book import CashInterestBook
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def events_for(symbols,start,end):
    source=json.loads((ROOT/'2026-09-22-dividend-factor-coverage.json').read_text())['rows'];groups=defaultdict(list);excluded=[]
    for row in source:
        if row['symbol'] not in symbols:continue
        for e in row['events']:
            if not start<=e['ex_date']<end:continue
            if e.get('due_bill_on_date') or e.get('due_bill_off_date'):raise ValueError('Due bill needs separate modeling')
            if e['symbol']=='LIN' and e['ex_date']=='2023-03-13' and e['cusip']!='G54950103':
                excluded.append(dict(event=e,reason='Issuer-confirmed same economic entitlement after 1:1 reorganization'));continue
            groups[e['symbol'],e['ex_date']].append(e)
    events=[]
    for (s,d),parts in sorted(groups.items()):
        assert len({p['id'] for p in parts})==len(parts) and len({p['payable_date'] for p in parts})==1
        amount=sum((Decimal(str(p['rate'])) for p in parts),Decimal(0))
        assert amount>0
        events.append(dict(id=f'{s}-gross-scenario-{d}',symbol=s,ex_date=d,payable_date=parts[0]['payable_date'],rate=str(amount),currency=None,kind='ordinary_cash',amount_basis='gross',verified=False,scenario_assumption='USD gross source rate',entitlement_rule_assumption='Assume standard cash rights for every component; source foreign/special flags retained below and not legally resolved',evidence=['2026-09-22-dividend-factor-coverage.json','2026-09-22-linde-dividend-reconciliation.json'],components=parts))
    if 'LIN' in symbols:
        e=next(e for e in events if e['symbol']=='LIN' and e['ex_date']=='2023-03-13')
        assert Decimal(e['rate'])==Decimal('1.275') and len(excluded)==1
    assert sum((Decimal(e['rate']) for e in events),Decimal(0))==sum((Decimal(str(p['rate'])) for e in events for p in e['components']),Decimal(0))
    return events,excluded


def main():
    reference_path=ROOT/'2026-09-22-adjusted-trend.full.json.gz';base=json.loads(gzip.decompress(reference_path.read_bytes()))['results']
    adjusted=pd.read_parquet(CACHE/'dividend.parquet');ratepath=Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates={r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    rows=[];checks=[]
    for pool,path in PATHS.items():
        f=pd.read_parquet(path);start,end='2022-09-01','2025-09-01';prior=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=prior[0])&(f.day<end)]
        maps,_=forecasts(f,adjusted);events,excluded=events_for(set(f.symbol),start,end)
        for mult in [1,2]:
            for method,mapping in maps.items():
                ref=next(r for r in base if (r['pool'],r['method'],r['cost_multiplier'])==(pool,method,mult));cfg=PositionConfig(**ref['config'])
                for scenario in ['no_dividend','gross_source_cash']:
                    book=CashInterestBook(rates);div=CashDividendBook(events,source_rate_scenario=True) if scenario=='gross_source_cash' else None
                    with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                        r=simulate_positions(f,cfg,start,end,daily_bars=True,research_cash_interest=book,research_dividends=div)
                    if scenario=='no_dividend':
                        for key in ['metrics','curve','trades','contributions']:assert r[key]==ref[key]
                    else:assert r['research_dividends']['data_status']=='unverified_source_rate_scenario'
                    for p in r['curve']:
                        dd=p.get('dividends',{})
                        assert np.isclose(p['equity'],p['cash']+sum(a['market_value'] for a in p['assets'].values())+dd.get('receivable',0),atol=1e-7,rtol=0)
                        assert np.isclose(p['equity']-100000,p['realized_pnl']+p['unrealized_pnl']+dd.get('income',0)+p['cash_interest']['income'],atol=1e-7,rtol=0)
                    for a,b in zip(book.audit,r['curve'][:-1]):assert a['cash_basis']==b['cash']
                    assert np.isclose(sum(c['net_profit'] for c in r['contributions'])+book.income,r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
                    rows.append(dict(pool=pool,start=start,end_exclusive=end,method=method,cost_multiplier=mult,scenario=scenario,cash_return_pct=ref['cash_return_pct'],dividend_audit=r.get('research_dividends'),**{k:r[k] for k in ['config','metrics','curve','trades','contributions']}))
                    save_results(ROOT/'2026-09-22-pool-dividend-scenario.json',rows)
                    print(pool,mult,method,scenario,round(r['metrics']['return_pct'],4),round(r['metrics'].get('dividend_income',0),2),flush=True)
        checks.append(dict(pool=pool,events=events,excluded=excluded,controls_exact=True,conservation=True,interest_cash_basis_exact=True))
    assert len(rows)==24
    save_results(ROOT/'2026-09-22-pool-dividend-scenario.json',rows,completed=True)
    paths=[reference_path,ratepath,ROOT/'2026-09-22-dividend-factor-coverage.json',ROOT/'2026-09-22-linde-dividend-reconciliation.json']
    (ROOT/'2026-09-22-pool-dividend-scenario-checks.json').write_text(json.dumps(dict(checks=checks,source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}),indent=2)+'\n')


if __name__=='__main__':main()

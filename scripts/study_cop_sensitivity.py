"""Unverified COP cash-rights scenarios, never promoted to verified dividends."""
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from cash_dividend_book import CashDividendBook
from cash_interest_book import CashInterestBook
from asset_growth_forecasts import forecasts
from verified_liability_features import judge
from prepare_liability_transfer import CACHE
from quant_workbench.market_data import schedule
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def events_for(start,end,offset):
    raw=json.loads((ROOT/'2026-09-22-cop-dividend-api.json').read_text())['events']
    known={r['vendor_id']:r['issuer_classification'] for r in json.loads((ROOT/'2026-09-22-cop-components-confirmed.json').read_text())['components']}
    days=schedule('2021-07-01','2026-09-23').index.strftime('%Y-%m-%d').tolist()
    assert len({e['id'] for e in raw})==len(raw)
    groups=defaultdict(list)
    for e in raw:
        assert not any(e.get(k) for k in ['special','foreign','due_bill_on_date','due_bill_off_date'])
        ex=days[days.index(e['ex_date'])+offset]
        assert ex<=e['payable_date']
        if start<=ex<end:groups[ex,e['payable_date']].append(e)
    out=[]
    for (ex,pay),parts in sorted(groups.items()):
        rate=sum((Decimal(str(e['rate'])) for e in parts),Decimal(0))
        out.append(dict(id='COP-scenario-'+ex+'-'+pay,symbol='COP',ex_date=ex,payable_date=pay,rate=str(rate),currency=None,kind='ordinary_cash',amount_basis='gross',verified=False,scenario_assumption='USD gross source rate',evidence=['2026-09-22-cop-dividend-api.json','2026-09-22-cop-components-confirmed.json'],entitlement_rule_assumption='Treat all components, including VROC, as standard cash rights; not verified legal classification',components=[dict(id=e['id'],rate=e['rate'],source_ex_date=e['ex_date'],issuer_classification=known.get(e['id'],'unverified')) for e in parts]))
    assert len({e['ex_date'] for e in out})==len(out)
    assert sum((Decimal(e['rate']) for e in out),Decimal(0))==sum((Decimal(str(p['rate'])) for e in out for p in e['components']),Decimal(0))
    return out


def main():
    info=json.loads((ROOT/'2026-09-22-liability-transfer-fundamentals.json').read_text());ids={s:dict(identity_verified=v['current_identity_matched']) for s,v in info['issuers'].items()}
    rates={}
    for name in ['sofr-extended.json','sofr-latest.json']:
        for r in json.loads((Path('artifacts/research/cash-benchmark')/name).read_text())['refRates']:
            if r['effectiveDate'] in rates:assert rates[r['effectiveDate']]==r['percentRate']
            rates[r['effectiveDate']]=r['percentRate']
    refs=json.loads((ROOT/'2026-09-22-cash-feedback.json').read_text())['results']
    rows=[];pure=[];event_sets=[]
    for start,end,path in [('2022-09-01','2025-09-01','artifacts/research/liability-transfer-temporal/combined.parquet'),('2025-09-01','2026-09-01','artifacts/research/liability-transfer/daily.parquet')]:
        f=pd.read_parquet(path);prior=sorted(f.loc[f.day<start,'day'].unique())[-273:];f=f[(f.day>=prior[0])&(f.day<end)]
        maps,_,_=forecasts(f,start,end,facts_root=CACHE,identities=ids,judge_fn=judge,ratio_key='burden')
        days=sorted(f.loc[f.day>=start,'day'].unique());cb=CashInterestBook(rates);cb.start(days);cash=100000.
        for d in days:cash+=cb.before_open(d,cash)
        pure.append(dict(start=start,end=end,last_close=days[-1],return_pct=(cash/100000-1)*100))
        for cost in [1,2]:
            reference=next(r for r in refs if r['method']=='low_liability' and r['scenario']=='sofr' and r['cost_multiplier']==cost)
            cfg=PositionConfig(**reference['config'])
            for offset in [None,-1,0,1]:
                events=events_for(start,end,offset) if offset is not None else []
                div=CashDividendBook(events,source_rate_scenario=True) if offset is not None else None
                book=CashInterestBook(rates)
                with patch('quant_workbench.position.daily_forecasts',return_value=maps['low_growth']):
                    r=simulate_positions(f,cfg,start,end,daily_bars=True,research_dividends=div,research_cash_interest=book)
                if offset is None and start=='2022-09-01':assert r['metrics']==reference['metrics'] and r['contributions']==reference['contributions']
                for p in r['curve']:
                    assert all(a['shares']==0 for s,a in p['assets'].items() if s!='COP')
                    dd=p.get('dividends',{})
                    assert np.isclose(p['equity'],p['cash']+sum(a['market_value'] for a in p['assets'].values())+dd.get('receivable',0),atol=1e-7,rtol=0)
                    assert np.isclose(p['equity']-100000,p['realized_pnl']+p['unrealized_pnl']+dd.get('income',0)+p['cash_interest']['income'],atol=1e-7,rtol=0)
                assert np.isclose(sum(c['net_profit'] for c in r['contributions'])+book.income,r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
                for a,b in zip(book.audit,r['curve'][:-1]):assert a['cash_basis']==b['cash']
                if div:assert r['research_dividends']['data_status']=='unverified_source_rate_scenario'
                rows.append(dict(start=start,end_exclusive=end,cost_multiplier=cost,offset=offset,method='no_dividend' if offset is None else 'assumed_cash_rights',**{k:r[k] for k in ['config','metrics','curve','contributions']}))
                event_sets.append(dict(start=start,end=end,offset=offset,cost_multiplier=cost,events=events))
                print(start,cost,offset,round(r['metrics']['return_pct'],5),r['metrics'].get('dividend_income'),flush=True)
    assert len(rows)==16
    save_results(ROOT/'2026-09-22-cop-sensitivity.json',rows,completed=True)
    (ROOT/'2026-09-22-cop-sensitivity-checks.json').write_text(json.dumps(dict(pure_cash=pure,event_sets=event_sets,conservation=True,no_other_holdings=True,baseline_exact=True),indent=2)+'\n')

if __name__=='__main__':main()

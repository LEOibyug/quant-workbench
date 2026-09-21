"""Partial verified MSFT dividends plus cash interest, with exact legacy controls."""
import hashlib,json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from cash_interest_book import CashInterestBook
from cash_dividend_book import CashDividendBook
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig,simulate_positions
from study_covariance_allocation import save_results
ROOT=Path('docs/research-results')


def main():
    f=pd.read_parquet('artifacts/research/annual-momentum/original20.parquet')
    start,end='2025-09-01','2026-09-01'
    refs=json.loads((ROOT/'2026-09-22-msft-dividend-study.json').read_text())['results']
    events=[e for e in json.loads((ROOT/'2026-09-22-msft-dividends.json').read_text())['events'] if start<=e['ex_date']<end]
    source=Path('artifacts/research/cash-benchmark/sofr-latest.json');snapshot=json.loads(source.read_text())
    rates={r['effectiveDate']:r['percentRate'] for r in snapshot['refRates']}
    rows=[];checks=[]
    for cost in [1,2]:
        ref=next(r for r in refs if r['method']=='raw' and r['cost_multiplier']==cost)
        cfg=PositionConfig(**ref['config']);mapping=rule_forecasts(f,cfg)
        for mode in ['raw','cash','dividend','joint']:
            div=CashDividendBook(events) if mode in ['dividend','joint'] else None
            cash=CashInterestBook(rates) if mode in ['cash','joint'] else None
            with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
                r=simulate_positions(f,cfg,start,end,daily_bars=True,research_dividends=div,research_cash_interest=cash)
            if mode in ['raw','dividend']:
                old=next(x for x in refs if x['method']==('raw' if mode=='raw' else 'msft_book') and x['cost_multiplier']==cost)
                assert r['metrics']==old['metrics'] and r['contributions']==old['contributions']
            for p in r['curve']:
                dividends=p.get('dividends',{});interest=p.get('cash_interest',{}).get('income',0)
                assert np.isclose(p['equity'],p['cash']+sum(a['market_value'] for a in p['assets'].values())+dividends.get('receivable',0),atol=1e-7,rtol=0)
                assert np.isclose(p['equity']-100000,p['realized_pnl']+p['unrealized_pnl']+dividends.get('income',0)+interest,atol=1e-7,rtol=0)
            assert np.isclose(sum(x['net_profit'] for x in r['contributions'])+(cash.income if cash else 0),r['metrics']['final_equity']-100000,atol=1e-7,rtol=0)
            if cash:
                for event,previous in zip(cash.audit,r['curve'][:-1]):assert event['cash_basis']==previous['cash']
            rows.append(dict(pool='original20',start=start,end_exclusive=end,method=mode,cost_multiplier=cost,**{k:r[k] for k in ['config','metrics','curve','contributions']},dividend_events=div.audit if div else [],cash_events=cash.audit if cash else []))
            checks.append(dict(method=mode,cost_multiplier=cost,conservation=True,legacy_exact=mode in ['raw','dividend']))
            print(mode,cost,r['metrics']['return_pct'],r['metrics'].get('cash_interest_income'),r['metrics'].get('dividend_income'),flush=True)
    assert len(rows)==8
    save_results(ROOT/'2026-09-22-joint-cash-dividend.json',rows,completed=True)
    (ROOT/'2026-09-22-joint-cash-dividend-checks.json').write_text(json.dumps(dict(checks=checks,rate_snapshot=snapshot,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),indent=2)+'\n')

if __name__=='__main__':main()

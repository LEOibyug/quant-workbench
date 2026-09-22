"""Frozen passive controls and complete position episodes, no parameter selection."""
import gzip, hashlib, json, math
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from quant_workbench.daily_strategies import rule_forecasts
from quant_workbench.position import PositionConfig, simulate_positions

ROOT=Path('docs/research-results')
SOURCE=ROOT/'2026-09-22-joint-cash-dividend.full.json.gz'
OUT=ROOT/'2026-09-22-original20-path.json'
DATA=Path('artifacts/research/annual-momentum/original20.parquet')


def main():
    refs=json.loads(gzip.decompress(SOURCE.read_bytes()))['results']
    base=next(r for r in refs if r['method']=='raw' and r['cost_multiplier']==1)
    cfg=PositionConfig(**base['config']);data=pd.read_parquet(DATA)
    mapping=rule_forecasts(data,cfg)
    with patch('quant_workbench.position.daily_forecasts',return_value=mapping):
        actual=simulate_positions(data,cfg,'2025-09-01','2026-09-01',daily_bars=True)
    for k in ['curve','metrics','contributions']:assert actual[k]==base[k],k
    curve=actual['curve'];symbols=sorted(curve[0]['assets']);initial=cfg.costs.initial_cash
    passive=[]
    for cost in [1,2]:
        ref=next(r for r in refs if r['method']=='raw' and r['cost_multiplier']==cost)
        c=ref['config']['costs'];impact=(c['spread_bps']/2+c['slippage_bps'])/10000
        for fraction in [.5,1.]:
            cash=initial;holdings={};fees=0;impact_paid=0
            for s in symbols:
                a=curve[1]['assets'][s];price=a['open']*(1+impact);budget=initial*fraction/len(symbols)
                q=math.floor(budget/price)
                while q and q*price+max(c['minimum_commission'],q*c['commission_per_share'])>budget:q-=1
                assert q<=math.floor(a['volume']*c['participation'])
                fee=max(c['minimum_commission'],q*c['commission_per_share']) if q else 0
                holdings[s]=q;cash-=q*price+fee;fees+=fee;impact_paid+=q*a['open']*impact
            assert cash>=0
            path=[];peak=initial
            for i,p in enumerate(curve):
                mv=0 if i==0 else sum(holdings[s]*p['assets'][s]['close'] for s in symbols)
                equity=initial if i==0 else cash+mv;peak=max(peak,equity)
                path.append(dict(date=p['date'],equity=equity,drawdown_pct=(peak-equity)/peak*100,exposure=mv/equity))
            liquidation=sum(holdings[s]*curve[-1]['assets'][s]['close']*(impact+c['sell_fee_bps']/10000)+max(c['minimum_commission'],holdings[s]*c['commission_per_share']) for s in symbols if holdings[s])
            passive.append(dict(cost_multiplier=cost,initial_fraction=fraction,entry_date=curve[1]['date'],shares=holdings,cash=cash,fees=fees,impact_cost=impact_paid,curve=path,return_pct=(path[-1]['equity']/initial-1)*100,max_drawdown_pct=max(p['drawdown_pct'] for p in path),average_exposure_pct=np.mean([p['exposure'] for p in path])*100,estimated_liquidation_return_pct=(path[-1]['equity']-liquidation-initial)/initial*100))
    episodes=[];active={}
    for t in actual['trades']:
        s=t['symbol']
        if s not in active:
            assert t['side']=='buy'
            active[s]=dict(symbol=s,start=t['date'],end=None,open=False,flows=0.,trades=[],shares=0)
        e=active[s];q=t['quantity'];buy=t['side']=='buy'
        e['shares']+=q if buy else -q
        assert e['shares']==t['position_after']
        e['flows']+=(-q*t['price'] if buy else q*t['price'])-t['fee']
        e['trades'].append(t)
        if e['shares']==0:
            e['end']=t['date'];e['net_profit']=e['flows'];episodes.append(active.pop(s))
    for s,e in active.items():
        e['end']=curve[-1]['date'];e['open']=True
        e['net_profit']=e['flows']+e['shares']*curve[-1]['assets'][s]['close'];episodes.append(e)
    for x in actual['contributions']:
        assert abs(sum(e['net_profit'] for e in episodes if e['symbol']==x['symbol'])-x['net_profit'])<1e-6
    assert abs(sum(e['net_profit'] for e in episodes)-(actual['metrics']['final_equity']-initial))<1e-6
    payload=dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),passive=passive,episodes=episodes,actual_metrics=actual['metrics'],checks=dict(exact_baseline=True,episode_conservation=True,passive_affordability_and_volume=True))
    OUT.write_text(json.dumps(payload,indent=2)+'\n')
    print('passive',[(p['cost_multiplier'],p['initial_fraction'],p['return_pct'],p['max_drawdown_pct']) for p in passive])
    print('episodes',len(episodes))

if __name__=='__main__':main()

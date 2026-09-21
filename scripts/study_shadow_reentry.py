"""Frozen high-water shadow recovery, permanent exit, and continued trading."""
import gzip
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from cash_interest_book import CashInterestBook
from eg_allocation import forecasts
from quant_workbench.position import PositionConfig, simulate_positions
from study_covariance_allocation import save_results

ROOT = Path('docs/research-results')


def recovery(curve):
    peak = 100000.
    result = {}
    for p in curve:
        peak = max(peak, p['equity'])
        result[p['date']] = p['equity'] >= peak
    return result


def main():
    previous = json.loads(gzip.decompress((ROOT/'2026-09-22-eg-allocation.full.json.gz').read_bytes()))['results']
    ratepath = Path('artifacts/research/cash-benchmark/sofr-extended.json')
    rates = {r['effectiveDate']:r['percentRate'] for r in json.loads(ratepath.read_text())['refRates']}
    paths = dict(random10='artifacts/research/annual-momentum/random10-temporal.parquet',transfer12='artifacts/research/transfer12-temporal-2026-09-21/combined.parquet',new12='artifacts/research/liability-transfer-temporal/combined.parquet')
    rows = []; checks = []; hashes = {str(ratepath):hashlib.sha256(ratepath.read_bytes()).hexdigest()}
    for pool,path in paths.items():
        f = pd.read_parquet(path); hashes[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        start,end = '2022-09-01','2025-09-01'
        history = sorted(f.loc[f.day<start,'day'].unique())[-273:]
        f = f[(f.day>=history[0])&(f.day<end)]
        maps,_ = forecasts(f,rates,start); mapping = maps['fixed']
        days = sorted(f.loc[f.day>=start,'day'].unique()); cutoff = days[len(days)//2]
        for mult in [1,2]:
            ref = next(r for r in previous if (r['pool'],r['cost_multiplier'],r['method']) == (pool,mult,'fixed'))
            cfg = PositionConfig(**ref['config'])
            continuous_cfg = cfg.model_copy(update={'max_drawdown_pct':100})
            def run(config, callback=None, stop=end):
                with patch('quant_workbench.position.daily_forecasts',return_value={k:v for k,v in mapping.items() if k[0]<stop}):
                    return simulate_positions(f[f.day<stop],config,start,stop,daily_bars=True,research_cash_interest=CashInterestBook(rates),research_reentry=callback)
            shadow = run(continuous_cfg)
            signals = recovery(shadow['curve'])
            permanent = run(cfg)
            disabled = run(cfg, lambda day: False)
            for key in ['metrics','curve','trades','contributions']:
                assert permanent[key] == disabled[key] == ref[key]
            restarted = run(cfg, lambda day: signals[day])
            short_shadow = run(continuous_cfg,stop=cutoff)
            short_signals = recovery(short_shadow['curve'])
            assert short_signals == {d:v for d,v in signals.items() if d<cutoff}
            assert short_shadow['curve'] == [p for p in shadow['curve'] if p['date']<cutoff]
            short = run(cfg,lambda day: short_signals[day],stop=cutoff)
            assert short['curve'] == [p for p in restarted['curve'] if p['date']<cutoff]
            assert short['trades'] == [t for t in restarted['trades'] if t['date']<cutoff]
            for method,r in [('permanent',permanent),('continuous',shadow),('recovery',restarted)]:
                peak = 100000.
                for p in r['curve']:
                    peak = max(peak,p['equity'])
                    assert np.isclose(p['drawdown_pct'],(1-p['equity']/peak)*100,atol=1e-12)
                    pnl = sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())
                    assert np.isclose(pnl+p['cash_interest']['income'],p['equity']-100000,atol=1e-7,rtol=0)
                events = r.get('research_reentry',[])
                for e in events:
                    point = next(p for p in r['curve'] if p['date']==e['date'])
                    assert not any(point['positions'].values())
                    assert e['restart'] == signals[e['date']]
                rows.append(dict(pool=pool,start=start,end_exclusive=end,cost_multiplier=mult,method=method,cash_return_pct=ref['cash_return_pct'],reentry_events=events,**{k:r[k] for k in ['config','metrics','curve','trades','contributions']}))
                save_results(ROOT/'2026-09-22-shadow-reentry.json',rows)
                print(pool,mult,method,round(r['metrics']['return_pct'],4),round(r['metrics']['max_drawdown_pct'],4),sum(e['restart'] for e in events),flush=True)
            checks.append(dict(pool=pool,cost_multiplier=mult,old_control_exact=True,false_callback_exact=True,shadow_and_actual_prefix_exact=True,global_drawdown_preserved=True,conservation=True))
    assert len(rows)==18
    save_results(ROOT/'2026-09-22-shadow-reentry.json',rows,completed=True)
    (ROOT/'2026-09-22-shadow-reentry-checks.json').write_text(json.dumps(dict(checks=checks,hashes=hashes),indent=2)+'\n')


if __name__=='__main__': main()

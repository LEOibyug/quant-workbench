"""Report merged liability pools and actual stock concentration."""
import gzip
import json
from pathlib import Path
import numpy as np
ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-liability-pool.json'
    data=json.loads(path.read_text());full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    rows=data['results']
    assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==30
    key=lambda r:(r['pool'],r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])
    assert len({key(r) for r in rows})==30
    concentration=[]
    for a,b in zip(rows,full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
        effective=[]; counts=[]; maximum=[]; held=set()
        for p in b['curve']:
            values=[v['market_value'] for v in p['assets'].values() if v['market_value']>0]
            held|={s for s,v in p['assets'].items() if v['market_value']>0}
            if values:
                w=np.array(values)/sum(values)
                effective.append(float(1/(w@w)));counts.append(len(values));maximum.append(float(max(w)))
        concentration.append(dict(pool=a['pool'],start=a['start'],end=a['end_exclusive'],method=a['method'],cost_multiplier=a['cost_multiplier'],active_days=len(effective),all_days=len(b['curve']),mean_effective_stocks=float(np.mean(effective)) if effective else None,mean_stock_count=float(np.mean(counts)) if counts else None,mean_largest_stock_fraction=float(np.mean(maximum)) if maximum else None,held_symbols=sorted(held)))
    windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows));assert len(windows)==5
    lines=['# 合并股票池的低负债筛选','',
           '协议cb34ef7在运行前冻结。使用同一100000共享资金账户、相同负债比率/财报核实范围、20日决策及原风险/执行约束。62股最新一年与22股三个历史年度及连续三年，低/高/同资格两费用共30账户。不是独立账户收益拼接或平均。','',
           '## 全部结果','',
           '|池|起点/终点不含|费用|低负债收益%|高负债收益%|同资格收益%|低组回撤%|低组停机|',
           '|---|---|---:|---:|---:|---:|---:|---|']
    for pool,start,end in windows:
        for mult in [1,2]:
            p={r['method']:r['metrics'] for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
            assert set(p)=={'low_liability','high_liability','eligible'}
            a,b,c=[p[k] for k in ['low_liability','high_liability','eligible']]
            lines.append(f"|{pool}|{start}/{end}|{mult}|{a['return_pct']:+.3f}|{b['return_pct']:+.3f}|{c['return_pct']:+.3f}|{a['max_drawdown_pct']:.3f}|{a['halted']}|")
    coverage=json.loads((ROOT/'2026-09-22-liability-pool-coverage.json').read_text())
    lines+=['','## 正常费用低组实际集中度','', '|池/区间|可计算股票数|曾持股|平均有效持股数|持股活跃日/总日|平均权益暴露%|','|---|---|---|---:|---|---:|']
    for pool,start,end in windows:
        c=next(x for x in concentration if (x['pool'],x['start'],x['end'],x['method'],x['cost_multiplier'])==(pool,start,end,'low_liability',1))
        cov=next(x['coverage'] for x in coverage if (x['pool'],x['start'],x['end'])==(pool,start,end))
        n=[len(d['eligible']) for d in cov]
        r=next(x for x in rows if (x['pool'],x['start'],x['end_exclusive'],x['method'],x['cost_multiplier'])==(pool,start,end,'low_liability',1))
        lines.append(f"|{pool}/{start}/{end}|{min(n)}—{max(n)}|{', '.join(c['held_symbols'])}|{c['mean_effective_stocks']:.2f}|{c['active_days']}/{c['all_days']}|{r['metrics']['average_gross_exposure_pct']:.2f}|")
    lines+=['','有效持股数以每日股票市值份额q计算1/Σq²，再仅对非空持仓日平均；现金不当成股票，空仓日不伪记为分散。它只衡量资金集中度，不能代表股票经济风险相互独立。','',
            '## 解释与边界','',
            '正常费用最新62股低组+5.96%，低于高组+10.46%和同资格+13.61%；22股连续三年低组+14.99%优于同资格+10.59%，但2024年度−1.72%。历史低组平均有效持股仅约1.95、曾持有INTU/MDT/SPGI三股，连续盈利仍不足以证明广泛企业适用性。','',
            '合并池改变排名与共同预算，不能把与小池差异当作只改变分散化的因果效应。尤其历史22股仍有会计字段覆盖缺口；更多名义股票不保证实际低组覆盖更多企业类型。长期连续账户与年度从现金重启不同，不能拼接年度收益代替连续结果。','',
            '全部股票和窗口已用于开发，不能作为独立确认。原价/分红/公司行动及当前身份核验的历史边界沿用；五份原表核实范围没有扩展至未经核实的新申报。尚未建立经过独立确认的企业适用性判别方法，正式判断仍是证据不足。总体目标未完成。','',
            '## 核验与复现','',
            '每窗口真实价格前缀不改变过去目标，股权重/共同预算、分组互斥、同申报公开时间均检查；30方法费用组合与完整档案逐项核验。行情和财报SHA256保存于data文件。','',
            '`uv run --locked python scripts/study_liability_pool.py`；`uv run --locked python scripts/report_liability_pool.py`。未改生产策略。']
    (ROOT/'2026-09-22-liability-pool.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-liability-pool-concentration.json').write_text(json.dumps(concentration,indent=2)+'\n')
    print('\n'.join(lines[4:]))

if __name__=='__main__':main()

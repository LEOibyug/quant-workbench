"""Report all verified-component coverage sensitivity results."""
import gzip
import json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-liability-expanded.json'
    result=json.loads(path.read_text());full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    rows=result['results'];old=json.loads((ROOT/'2026-09-22-liability-burden.json').read_text())['results']
    assert result['status']==full['status']=='completed' and len(rows)==len(full['results'])==72
    key=lambda r:(r['pool'],r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])
    assert len({key(r) for r in rows})==72 and {key(r) for r in rows}=={key(r) for r in old}
    for a,b in zip(rows,full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
    checks=json.loads((ROOT/'2026-09-22-liability-expanded-checks.json').read_text())
    identical=sum(c['identical_targets'] for c in checks)
    assert len(checks)==72
    lines=['# 已核实分项扩展：负债策略覆盖敏感性','',
           '协议329b62d运行前冻结，仅允许VZ2021—2024与ORCL2024五份核实原表的同申报分项合计。直接总负债优先；新年度未核实则拒绝，不沿用旧核实。没有更改因子、资金、20日调仓或风险规则。所有窗口已用于开发，非独立确认。','',
           '## 低负债组全部结果','',
           '|池|起点/终点不含|费用|原收益%|扩展收益%|扩展回撤%|',
           '|---|---|---:|---:|---:|---:|']
    diffs=[]
    for r in rows:
        ref=next(x for x in old if key(x)==key(r))
        diff=r['metrics']['return_pct']-ref['metrics']['return_pct']
        diffs.append(dict(pool=r['pool'],start=r['start'],end=r['end_exclusive'],method=r['method'],cost_multiplier=r['cost_multiplier'],return_difference_pp=diff))
        if r['method']=='low_liability':
            lines.append(f"|{r['pool']}|{r['start']} / {r['end_exclusive']}|{r['cost_multiplier']}|{ref['metrics']['return_pct']:+.4f}|{r['metrics']['return_pct']:+.4f}|{r['metrics']['max_drawdown_pct']:.4f}|")
    coverage=json.loads((ROOT/'2026-09-22-liability-expanded-coverage.json').read_text())
    prior=json.loads((ROOT/'2026-09-22-liability-burden-coverage.json').read_text())
    lines+=['','## 资格变化与对照','', '|池/起点/终点|增加资格的股票日期数|低组变化决策日数|名义预算变化日数|','|---|---:|---:|---:|']
    for c in coverage:
        p=next(x for x in prior if (x['pool'],x['start'],x['end'])==(c['pool'],c['start'],c['end']))
        assert [d['day'] for d in c['coverage']]==[d['day'] for d in p['coverage']]
        added=changed=budget=0
        for d,b in zip(c['coverage'],p['coverage']):
            added+=len(set(d['eligible'])-set(b['eligible']))
            changed+=d['selected']['low_growth']!=b['selected']['low_growth']
            budget+=d['budget']!=b['budget']
        lines.append(f"|{c['pool']}/{c['start']}/{c['end']}|{added}|{changed}|{budget}|")
    changed=[d for d in diffs if abs(d['return_difference_pp'])>1e-12]
    lines+=['','## 收益发生变化的账户','', '|池/起点/终点|方法|费用|扩展减原收益百分点|','|---|---|---:|---:|']
    for d in changed:lines.append(f"|{d['pool']}/{d['start']}/{d['end']}|{d['method']}|{d['cost_multiplier']}|{d['return_difference_pp']:+.4f}|")
    lines+=['','## 验证与判断','',f'{identical}/72个账户目标映射完全不变，已逐项断言全部指标和逐股贡献精确复现；其余账户完整结果保留。72档案逐项核验。VZ真实数据确认新未核实申报、身份失败、原表数值不符均拒绝，未来申报扰动不改变过去判断。','',
            '这里扩展的是可核实财报覆盖，不是收益信号优化。新12最新年只有部分时期VZ核实申报有效；更新为2025财报后若未核实就退出扩展资格，不回退旧表。ORCL2024原表核实不覆盖2025申报，因此不能假定最新一年一定新增ORCL。','',
            '低组仍集中少数企业，原两个亏损窗口及开发样本限制未被消除；不能建立通用适用性。高组或全部组的变化也不能当作低负债因子证实。原价、分红、公司行动与历史身份限制继续保留。总体目标未完成。','',
            '复现：`uv run --locked python scripts/study_liability_expanded.py`；`uv run --locked python scripts/report_liability_expanded.py`。未改生产系统默认策略。']
    (ROOT/'2026-09-22-liability-expanded.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-liability-expanded-comparison.json').write_text(json.dumps(diffs,indent=2)+'\n')
    print('Identical target accounts:',identical,'changed returns:',len(changed))
    print('Low group differences:',[d for d in changed if d['method']=='low_liability'])

if __name__=='__main__':main()

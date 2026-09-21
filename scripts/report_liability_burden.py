"""Complete reporting for the fixed liability burden study, including negative evidence."""
import gzip
import json
from pathlib import Path

ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-liability-burden.json'
    data=json.loads(path.read_text())
    full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    rows=data['results']
    assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==72
    for a,b in zip(rows,full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
    windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows))
    assert len(windows)==12
    lines=['# 总负债负担：企业财务筛选实验','',
           '## 机制、定义与限制','',
           '协议d6735d2运行前冻结。Campbell/Hilscher/Szilagyi《In Search of Distress Risk》，DOI10.2139/ssrn.770805和10.1111/j.1540-6261.2008.01416.x，本轮仅读取Crossref摘要。困境股低收益的研究激发此候选，但原文是多变量失败概率模型，并非仅按负债比率。本文不声称复现论文。','',
           '比率B=Liabilities/Assets，来自同一已公开10-K/10-K/A、同一天的USD瞬时字段。filed严格早于决策日、资产日期不陈旧、冲突或缺失拒绝。不用总负债冒充有息债务，不填补缺字段，不剔除负权益高比率。金融/REIT等会计不可比范围和身份检查沿用既有规则。','',
           '低/高三分组及同资格全部组，共享100000现金、63日逆波动和协方差风险预算、20日决策，保留原费用、整股分批、止损与停机。虽然名义预算相同，实际暴露与风险仍不同，组间收益差不构成纯负债比率的因果效应。','',
           '## 全部结果','',
           '|股票池|区间（终点不含）|费用倍数|低负债%|高负债%|同资格全部%|低组回撤%|低组停机|',
           '|---|---|---:|---:|---:|---:|---:|---|']
    comparisons=[]
    for pool,start,end in windows:
        for mult in [1,2]:
            part={r['method']:r for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
            assert set(part)=={'low_liability','high_liability','eligible'}
            a,b,c=(part[k]['metrics'] for k in ['low_liability','high_liability','eligible'])
            lines.append(f"|{pool}|{start}—{end}|{mult}|{a['return_pct']:+.3f}|{b['return_pct']:+.3f}|{c['return_pct']:+.3f}|{a['max_drawdown_pct']:.3f}|{'是' if a['halted'] else '否'}|")
            comparisons.append(dict(pool=pool,start=start,end=end,cost_multiplier=mult,negative=a['return_pct']<0,low_minus_high_pp=a['return_pct']-b['return_pct'],low_minus_eligible_pp=a['return_pct']-c['return_pct']))
    normal=[x for x in comparisons if x['cost_multiplier']==1]
    summary=dict(negative=sum(x['negative'] for x in normal),beat_high=sum(x['low_minus_high_pp']>0 for x in normal),beat_eligible=sum(x['low_minus_eligible_pp']>0 for x in normal))
    lines+=['','## 覆盖与实际配置','',
            '|池/开始日|可计算股票数范围|低组曾入选股票|正常费用平均股票暴露%|',
            '|---|---|---|---:|']
    coverage=json.loads((ROOT/'2026-09-22-liability-burden-coverage.json').read_text())
    for c in coverage:
        rr=next(r for r in rows if r['pool']==c['pool'] and r['start']==c['start'] and r['end_exclusive']==c['end'] and r['method']=='low_liability' and r['cost_multiplier']==1)
        ds=c['coverage']; n=[len(d['eligible']) for d in ds]
        symbols=sorted({s for d in ds for s in d['selected']['low_growth']})
        lines.append(f"|{c['pool']}/{c['start']}至{c['end']}|{min(n)}—{max(n)}|{', '.join(symbols)}|{rr['metrics']['average_gross_exposure_pct']:.2f}|")
    lines+=['','## 结论','',f"正常费用12窗口，低负债组亏损{summary['negative']}个，超过高组{summary['beat_high']}个、超过同资格全部组{summary['beat_eligible']}个。窗口重叠，不能作为12次独立统计试验。",'',
            '随机10股池仅3股可计算且低组始终INTU，新12历史低组集中MDT/SPGI。看起来跨年份稳定的部分实际上只有少数公司、低资金暴露。不能从此定义广泛企业适用边界，更不能按事后盈利改为只选这些股票。缺财报字段不等于企业差；低负债也可能昂贵，高负债可能来自预收款或回购，不能直接贴困境标签。','',
            '旧三个股票池与新12均已查看，为开发诊断而非独立确认。新12的2024年度以及随机最新年度仍负，不支持已完成跨池跨期有效策略。后续需增加事前确定的企业范围并核实字段口径，检验筛选增量是否超出少数个股和仓位差异。原价分红/公司行动限制保留。','',
            '## 可调用判断和核验','',
            '`uv run --locked python scripts/liability_burden_features.py --symbol AAPL --date 2025-09-01`输出指标、同申报来源及正式证据不足。该比率不是破产概率，独立单股也不能给出池内排名；排名与分配来自组合模块。未确认前不输出已验证适用。','',
            '对缓存62企业四日期检查未来申报扰动、同申报同日、缺字段与冲突拒绝；对真实62股行情检查前缀不变。72账户边界及紧凑/完整档案一致性核验通过。coverage沿用通用分组键low_growth/high_growth，其本实验含义为低/高负债，非资产增长；结果method已明确为low_liability/high_liability。','',
            '复现：`uv run --locked python scripts/audit_liability_burden.py`；`uv run --locked python scripts/study_liability_burden.py`；`uv run --locked python scripts/report_liability_burden.py`。总体研究目标未完成。']
    (ROOT/'2026-09-22-liability-burden.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-liability-burden-comparison.json').write_text(json.dumps(dict(summary=summary,comparisons=comparisons),indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':main()

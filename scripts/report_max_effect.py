"""Complete reporting for the fixed MAX study, including negative evidence."""
import gzip
import json
from pathlib import Path

ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-max-effect.json'
    data=json.loads(path.read_text())
    full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    rows=data['results']
    assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==72
    for a,b in zip(rows,full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
    windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows))
    assert len(windows)==12
    lines=['# MAX：避开短期极端上涨股票是否有效？','',
           '## 经济假设与文献','',
           'Bali、Cakici、Whitelaw，NBER WP14804（2009，后发表于JFE 2011），DOI10.3386/w14804。读取NBER原始摘要：投资者偏好彩票式收益，过去一月最大单日涨幅MAX与后续收益负相关。本文仅以此提出固定候选，不声称复现论文的全市场十分组、长短组合或风险调整结果。', '',
           '协议2431665在运行前冻结。MAX=max(最近21交易日简单收盘收益)，每20日选最低三分组；最高组及全部股票为对照。63日逆波动、LedoitWolf协方差与10%波动缩放、20%单股上限及相同名义预算，单一共享现金100000，保留原执行、费用和停机机制。收盘信号只能次日成交。', '',
           '相同名义预算不意味着各组实际风险、持仓或行业相同，低MAX与高MAX收益差不是纯粹因果效应。仅使用既有价格，不继承资产扩张策略的财务行业剔除。股票池排名是相对状态，不是企业永久属性。','',
           '## 全部账户结果','',
           '|股票池|区间（终点不含）|费用倍数|低MAX%|高MAX%|不筛选%|低MAX回撤%|低MAX停机|',
           '|---|---|---:|---:|---:|---:|---:|---|']
    comparisons=[]
    for pool,start,end in windows:
        for mult in [1,2]:
            part={r['method']:r for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
            assert set(part)=={'low_max','high_max','eligible'}
            a,b,c=(part[k]['metrics'] for k in ['low_max','high_max','eligible'])
            lines.append(f"|{pool}|{start}—{end}|{mult}|{a['return_pct']:+.3f}|{b['return_pct']:+.3f}|{c['return_pct']:+.3f}|{a['max_drawdown_pct']:.3f}|{'是' if a['halted'] else '否'}|")
            comparisons.append(dict(pool=pool,start=start,end=end,cost_multiplier=mult,negative=a['return_pct']<0,low_minus_high_pp=a['return_pct']-b['return_pct'],low_minus_eligible_pp=a['return_pct']-c['return_pct']))
    normal=[x for x in comparisons if x['cost_multiplier']==1]
    summary=dict(negative=sum(x['negative'] for x in normal),beat_high=sum(x['low_minus_high_pp']>0 for x in normal),beat_eligible=sum(x['low_minus_eligible_pp']>0 for x in normal))
    lines+=['','## 结论','',f"正常费用12个窗口，低MAX亏损{summary['negative']}个，超过高组{summary['beat_high']}个、超过不筛选{summary['beat_eligible']}个。窗口有重叠、池规模小，不能当成12次独立统计试验。未获得跨池跨期稳定正向作用，也未证实股票适用性；不会根据本轮结果反选高MAX。",'',
            '所有样本此前均已查看，只能作为开发诊断。原价/拆股调整数据口径以及未完整核实的分红、公司行动限制沿用；单日极值还可能受公司行动影响。本实验不否定文献对其原始样本的结论，亦不是完整总回报复现。','',
            '## 判断器与验证','',
            '`uv run --locked python scripts/max_effect_forecasts.py --prices artifacts/research/annual-momentum/original20.parquet --symbol AAPL --date 2025-09-01`。严格使用日期之前已完成的收盘数据，输出MAX、当前池排名、候选分组和正式“证据不足”。候选低组不等于已验证适用；下个交易日或股票池变化需重算。','',
            '合成序列核对简单收益而非对数收益MAX；六份真实输入的价格单位变化、前缀截断及分组互斥通过。权重边界在每次计算中核验；72账户方法×费用组合、完整档案与紧凑结果逐项一致。没有新增生产策略或改变网页默认设置。','',
            '复现：`uv run --locked python scripts/audit_max_effect.py`；`uv run --locked python scripts/study_max_effect.py`；`uv run --locked python scripts/report_max_effect.py`。总体研究目标尚未完成。']
    (ROOT/'2026-09-22-max-effect.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-max-effect-comparison.json').write_text(json.dumps(dict(summary=summary,comparisons=comparisons),indent=2)+'\n')
    print(json.dumps(summary))

if __name__=='__main__':main()

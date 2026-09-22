"""Report the complete frozen mechanism experiment, including unfavorable results."""
import gzip
import json
from pathlib import Path

ROOT=Path('docs/research-results')
P=ROOT/'2026-09-22-original20-mechanism'


def main():
    payload=json.loads(gzip.decompress(P.with_suffix('.full.json.gz').read_bytes()))
    assert payload['status']=='completed' and len(payload['results'])==28
    rows=payload['results']
    base=next(r for r in rows if r['method']=='fixed_ensemble' and r['excluded'] is None and r['cost_multiplier']==1)
    contributions={x['symbol']:x['net_profit']/1000 for x in base['contributions']}
    lines=['# 原20股：分支消融与共享资金排除诊断','',
        '运行前方案见同日前缀 protocol。固定2025-09-01至2026-09-01（右端不含），20股、初始10万美元、原价格，不含股息与现金计息。全部28账户完成，原组合两费用的曲线、指标、贡献精确复现；全部逐日和期末资金守恒通过。', '',
        '## 三个分支独立交易与组合', '',
        '|策略|费用倍数|收益%|最大回撤%|平均仓位%|交易数|费用美元|冲击成本美元|停机|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        if r['excluded'] is not None:continue
        m=r['metrics']
        lines.append(f"|{r['method']}|{r['cost_multiplier']}|{m['return_pct']:.3f}|{m['max_drawdown_pct']:.3f}|{m['average_gross_exposure_pct']:.2f}|{m['trade_count']}|{m['fees']:.2f}|{m['impact_cost']:.2f}|{m['halted']}|")
    lines += ['', '每个分支独立运行都有自己的风险缩放、仓位、费用和止损。其结果不能乘以1/3后相加来解释混合组合；它们是机制对照。', '',
        '## 逐一排除股票后重新运行', '',
        '所有19股账户重新计算横截面排名、池内市场残差、协方差和共享资金。变化=排除后收益−原组合收益；负值表示排除该股降低这条历史路径的收益。右列为原账本该股贡献，仅供比较，不是排除后收益变化的预测。', '',
        '|排除股票|收益%|相对原组合变化百分点|回撤%|平均仓位%|停机|原账本该股贡献百分点|',
        '|---|---:|---:|---:|---:|---|---:|']
    effects=[]
    for r in rows:
        if r['excluded'] is None:continue
        m=r['metrics'];s=r['excluded'];delta=m['return_pct']-base['metrics']['return_pct']
        effects.append((delta,s,m['return_pct']))
        lines.append(f"|{s}|{m['return_pct']:.3f}|{delta:+.3f}|{m['max_drawdown_pct']:.3f}|{m['average_gross_exposure_pct']:.2f}|{m['halted']}|{contributions[s]:+.3f}|")
    lines += ['', '## 共享组合变化的账本分解', '',
        '组合变化 = 移除原股票贡献 + 其余19股贡献变化。后者同时含信号重算和资金路径变化，不能单独称为资金竞争效应。全部股票均列出；三个变化最大的其余股票按美元变化绝对值排序。', '',
        '|排除股票|移除原贡献美元|其余股票合计变化美元|其余股票变化最大的三项（美元）|',
        '|---|---:|---:|---|']
    for r in rows:
        s=r['excluded']
        if s is None:continue
        delta=[(x['symbol'],x['net_profit']-contributions[x['symbol']]*1000) for x in r['contributions']]
        rest=sum(v for _,v in delta)
        removed=-contributions[s]*1000
        assert abs(rest+removed-(r['metrics']['final_equity']-base['metrics']['final_equity']))<1e-6
        top=sorted(delta,key=lambda x:-abs(x[1]))[:3]
        detail=' / '.join(f'{sym} {v:+.2f}' for sym,v in top)
        lines.append(f'|{s}|{removed:+.2f}|{rest:+.2f}|{detail}|')
    lo=min(effects);hi=max(effects)
    lines += ['', '## 能解释什么', '',
        f'单股排除后收益范围为{lo[2]:.3f}%（排除{lo[1]}）至{hi[2]:.3f}%（排除{hi[1]}）。这检验的是单点删除敏感性，不覆盖多只股票同时删除、不同时间段或不同市场环境。', '',
        '原组合正常费用收益22.15%，独立动量21.80%、独立反转21.87%，而通道仅5.87%。因此，“上涨趋势跟随统一解释所有利润”缺乏支持；横截面动量与相对回落后的交易均有正历史收益。但分支不是相同暴露，仍不能把绝对收益当作择时alpha。双费下组合20.55%低于动量20.94%，不能宣称三者混合在成本压力下严格占优。', '',
        '逐股贡献集中于JNJ、LLY、XOM、GOOGL、AMD，跨医疗、能源、科技；策略输入没有行业或基本面，不能据此构造“这些行业永远适用”的规则。机制目前应表述为：在这个窗口内，价格路径、信号触发与组合资金分配相互作用获得利润，而不是20家企业共享某个已证明的结构优势。', '',
        '仍需补充相同时间/风险口径的市场或被动持有对照，以及ORCL、SOFI等价格下跌但交易赚钱的分阶段持仓证据，才能更具体地区分方向暴露与择时机制。不会依据本轮结果删股或替换生产配置。', '',
        '完整逐日持仓、贡献、配置在同名 full.json.gz，源数据与代码SHA在 sources.json。复现：`uv run --locked python scripts/study_original20_mechanism.py`，然后 `uv run --locked python scripts/report_original20_mechanism.py`。']
    P.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    print('exclusion extrema',lo,hi)

if __name__=='__main__':main()

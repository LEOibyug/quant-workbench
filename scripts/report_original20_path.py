"""Explain passive controls and all episodes without selecting profitable trades."""
import json
from pathlib import Path
ROOT=Path('docs/research-results')
P=ROOT/'2026-09-22-original20-path'


def main():
    d=json.loads(P.with_suffix('.json').read_text());episodes=d['episodes']
    lines=['# 原20股：被动持有与持仓阶段证据','',
        '固定方案540b1c0。使用2025-09-01至2026-09-01原价数据，未计股息与现金利息。原策略完整重跑与冻结账本精确一致，115段持仓全部按真实成交重建、逐股及总利润守恒。', '',
        '## 被动持有对照', '',
        '在策略首个可成交日2025-09-03开盘，按相同点差、滑点、佣金买入整数股，各股分配相同初始美元预算。买入后不调仓、不止损，剩余现金不计息。全部买入通过现金与成交量参与限制检查。期末按收盘市值，与策略账面收益口径相同；另列估计清算收益。', '',
        '|初始股票预算|费用倍数|收益%|最大回撤%|平均仓位%|估计清算收益%|',
        '|---|---:|---:|---:|---:|---:|']
    for p in d['passive']:
        lines.append(f"|{p['initial_fraction']:.0%}|{p['cost_multiplier']}|{p['return_pct']:.3f}|{p['max_drawdown_pct']:.3f}|{p['average_exposure_pct']:.2f}|{p['estimated_liquidation_return_pct']:.3f}|")
    lines += ['',
        '原策略正常费用收益22.147%、回撤4.708%、平均仓位62.34%；双费用收益20.551%、回撤4.793%。满额被动收益21.813%、回撤10.725%；双費21.760%、10.726%。正常费用下策略仅多0.333个百分点，但历史最大回撤较低；双费下策略收益低于满额被动。50%被动回撤5.622%与策略较接近，但这不是波动、beta或动态风险严格匹配，不能据此计算已验证alpha。', '',
        '## 所有股票的持仓阶段', '',
        '阶段定义为从零持仓开始到再次归零；分批加减仓不拆段，末日未清仓阶段按收盘市值计价。利润包括全部佣金与成交价冲击，未实现利润单独体现在未闭合阶段。阶段数量不是独立样本数。', '',
        '|股票|阶段数|正利润阶段数|未闭合阶段数|合计利润美元|最好阶段美元|最差阶段美元|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for s in sorted({e['symbol'] for e in episodes}):
        es=[e for e in episodes if e['symbol']==s];pnls=[e['net_profit'] for e in es]
        lines.append(f"|{s}|{len(es)}|{sum(x>0 for x in pnls)}|{sum(e['open'] for e in es)}|{sum(pnls):.2f}|{max(pnls):.2f}|{min(pnls):.2f}|")
    for s in ['ORCL','SOFI']:
        lines += ['',f'## {s} 全部持仓阶段','', '|开始|结束/估值日|期末仍持仓|成交笔数|净利润美元|', '|---|---|---|---:|---:|']
        for e in sorted((e for e in episodes if e['symbol']==s),key=lambda e:e['start']):
            lines.append(f"|{e['start']}|{e['end']}|{e['open']}|{len(e['trades'])}|{e['net_profit']:.2f}|")
    lines += ['', '## 机制解释及边界', '',
        '全年首尾价格下跌不代表每个可交易子区间都下跌。策略可以在反弹段持有，在其他阶段空仓；这里有真实分批成交与资金流重建证据，不是事后拿局部最高最低价虚构交易。ORCL、SOFI所有盈亏阶段均列出，不能只保留赢家。', '',
        '这仍不是前瞻选择ORCL/SOFI的理由：逐股排除实验表明移除它们后原组合收益反而更高。交易阶段盈利、加入共享账户的历史边际贡献、未来适用性必须分开判断。', '',
        '结合三项研究，目前解释是：原20股的同期上涨提供较强方向收益底座；动量、反转与动态仓位在这个窗口捕捉部分局部价格路径并降低历史回撤；利润集中于JNJ/LLY/XOM/GOOGL/AMD，组合内部相互作用显著。企业行业/质量不是模型输入，也没有被证明为适用边界。', '',
        '仍未证明跨股票池或跨时期的稳定优势。当前区间被反复观察、股票池由现有名单构成，存在选择与搜索偏差；被动对照也未计完整股息。不要把本报告解读为未来回报承诺或可直接部署的股票筛选规则。', '',
        '复现：`uv run --locked python scripts/study_original20_path.py`；`uv run --locked python scripts/report_original20_path.py`。同名JSON包含全部115阶段的实际成交及四个被动账户逐日曲线。']
    P.with_suffix('.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()

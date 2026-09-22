"""Report every frozen candidate, costs and transfer gates without winner retuning."""
import json, math
from pathlib import Path
import numpy as np
ROOT=Path('docs/research-results')


def main():
    first=json.loads((ROOT/'2026-09-22-trend-pullback.json').read_text())
    second=json.loads((ROOT/'2026-09-22-smoothed-ensemble.json').read_text())
    assert first['status']==second['status']=='completed'
    assert len(first['results'])==48 and len(second['results'])==12
    third=json.loads((ROOT/'2026-09-22-banded-execution.json').read_text())
    assert third['status']=='completed' and len(third['results'])==12
    rows=first['results']+second['results']+third['results']
    controls={(r['pool'],r['cost_multiplier']):r for r in rows if r['method']=='fixed_ensemble' and r['policy']=='legacy'}
    methods=[('fixed_ensemble','cost_aware'),('trend_reversal','legacy'),('trend_reversal','cost_aware'),('smoothed_ensemble','legacy'),('fixed_ensemble','banded')]
    gates=[]
    for method,policy in methods:
        for cost in [1,2]:
            subset=[r for r in rows if r['method']==method and r['policy']==policy and r['cost_multiplier']==cost and r['pool']!='original20']
            delta=[r['metrics']['return_pct']-controls[r['pool'],cost]['metrics']['return_pct'] for r in subset]
            dd=[r['metrics']['max_drawdown_pct']-controls[r['pool'],cost]['metrics']['max_drawdown_pct'] for r in subset]
            wins=sum(x>0 for x in delta)
            gates.append(dict(method=method,policy=policy,cost_multiplier=cost,pools=len(subset),wins=wins,median_return_difference_pp=float(np.median(delta)),all_drawdowns_worse=all(x>0 for x in dd),passed=wins>=math.ceil(len(subset)*2/3) and np.median(delta)>0 and not all(x>0 for x in dd)))
    lines=['# 盈利机制驱动的模型改进：完整对照结果','',
        '原20股分析提出三种不同机制候选，先冻结方案再运行各自实验，没有按结果调窗口或选股票。已有历史都属于开发数据。本报告包含六池、两费用、共72账户，不能称为新样本外确认。', '',
        '## 变更', '',
        '- trend_reversal：动量/反转目标各半，反转要求当前价不低于63日前；通道不再单独占资金。假设是减少持续下跌中的逆势交易。',
        '- smoothed_ensemble：保留原三分支，以调仓间隔为半衰期指数平滑目标，之后按当前协方差限风险。假设是减少快于执行周期的目标跳动；会造成入退出滞后。止损和熔断仍由引擎执行。',
        '- banded：保留原三策略，在实际执行中复用调仓缓冲与按比例共享买单资金，不调用成本优化器。用原配置2%调仓门槛、0.5%首次建仓门槛、100%日换手上限。',
        '- cost_aware：复用现有共享资金、相关风险和换手成本优化器，独立于信号变化测试。优化的是目标跟踪与费用折衷，不是准确预测收益。', '',
        '第二方案在看到第一方案原20股和另一20股初步结果后提出，顺序已在独立协议记录。第三方案在发现平滑增加成交后，依据基础执行缺少缓冲的代码检查提出。三个方案按顺序记录，没有回写先前假设或隐藏失败。', '',
        '## 预先规定的跨池推荐门槛', '',
        '排除original20后五个池，至少4/5收益改善、收益差中位数为正、回撤不能全部变差，正常和双倍费用均需通过。门槛仅为开发期筛查，不是统计显著性或未来盈利保证。不同区间累计收益不直接合并成年化收益。', '',
        '|模型|执行|费用倍数|改善池数|收益差中位数百分点|通过|', '|---|---|---:|---:|---:|---|']
    for g in gates:lines.append(f"|{g['method']}|{g['policy']}|{g['cost_multiplier']}|{g['wins']}/{g['pools']}|{g['median_return_difference_pp']:+.3f}|{g['passed']}|")
    accepted=[(m,p) for m,p in methods if all(g['passed'] for g in gates if g['method']==m and g['policy']==p)]
    lines += ['',f'同时通过两费用门槛的候选：{accepted or "无"}。默认及已发布版本不自动替换；两个新模型及缓冲执行在开发页可选择、运行并发布冻结版本。', '',
        '## 全部账户', '',
        '|股票池|模型|执行|费用|收益%|回撤%|均仓位%|交易数|费用+冲击美元|停机|', '|---|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in sorted(rows,key=lambda x:(x['pool'],x['cost_multiplier'],x['method'],x['policy'])):
        m=r['metrics'];lines.append(f"|{r['pool']}|{r['method']}|{r['policy']}|{r['cost_multiplier']}|{m['return_pct']:.3f}|{m['max_drawdown_pct']:.3f}|{m['average_gross_exposure_pct']:.2f}|{m['trade_count']}|{m['fees']+m['impact_cost']:.2f}|{m['halted']}|")
    lines += ['', '## 本轮结论与使用建议', '',
        '优先试用的是原fixed_ensemble + banded缓冲执行，不是更换信号。原20股正常费用收益22.147→22.532%，回撤4.708→4.374%，交易593→410，费用+冲击1367.06→1134.55美元。12账户交易数全部减少，11/12费用降低，但正常费用非原池仅3/5收益改善、双费4/5，未满足两费用均4/5的完整门槛。原20股双费收益20.551→20.348%，也需明确保留。', '',
        '趋势过滤与目标平滑均不推荐替代原组合。尤其平滑将原20股交易数增加到852，说明平滑目标并不等于减少实际成交。两者作为研究候选保留，不能以“已优化”包装为收益提升。', '',
        '网页：长期策略选择“固定三策略组合”，共享资金执行政策选择“共享资金 · 调仓缓冲执行”。复现实验时调仓5日、每日单股最大调整10%、首次建仓门槛0.5%、调仓缓冲2%、日换手上限100%，关闭额外轮换优化，其他使用冻结原配置。模型改为新候选时请单独比较，不混同已发布旧版本。当前未更改默认策略或已发布配置。', '',
        '缓冲带跳过小额非零目标调整；零目标退出、止损与组合熔断继续执行，并受成交量限制。该政策也按可用资金比例满足买单，故改善不能全部归因于缓冲带本身。', '',
        '## 可复核范围', '',
        '同年度original20/alternate20/random10为2025-09至2026-09，三个temporal池为2022-09至2025-09连续区间。无股息和现金利息，长时间停机后的持币不计息；不是完整总回报。原20股两费用旧组合精确复现，全部72账户核对现金+市值=权益及逐股盈亏=权益变化。新模型复用前缀因果性、输入排序不变、仓位约束、真实引擎账本测试。', '',
        '收益提升不能仅凭更低费用解释：更少或更晚交易会改变整个资金路径。反之，减少亏损但仍为负也不构成可部署盈利策略。股票池内的单股利润不能被当作独立投资机会分数。', '',
        '复现：study_trend_pullback.py、study_smoothed_ensemble.py（另加--banded运行缓冲实验）、report_strategy_refinement.py（均用uv run --locked python scripts/前缀运行）。三实验同名full.json.gz保存完整逐日持仓、贡献及配置，sources.json保存数据与代码哈希。']
    (ROOT/'2026-09-22-strategy-refinement.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-strategy-refinement-gates.json').write_text(json.dumps(dict(gates=gates,accepted=accepted),indent=2)+'\n')
    print(json.dumps(dict(gates=gates,accepted=accepted),indent=2))

if __name__=='__main__':main()

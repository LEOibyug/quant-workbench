"""Descriptive attribution of frozen accounts; no selection or parameter tuning."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path('docs/research-results')
SOURCE = ROOT / '2026-09-22-joint-cash-dividend.full.json.gz'
OUT = ROOT / '2026-09-22-original20-attribution'


def main():
    archive = json.loads(gzip.decompress(SOURCE.read_bytes()))
    accounts = []
    for r in archive['results']:
        if r['method'] != 'raw':
            continue
        curve = r['curve']
        initial = r['config']['costs']['initial_cash']
        rows, months = [], {}
        for item in r['contributions']:
            symbol = item['symbol']
            assets = [p['assets'][symbol] for p in curve]
            pnl = np.array([a['realized_pnl'] + a['unrealized_pnl'] for a in assets])
            increments = np.diff(np.r_[0, pnl])
            assert abs(float(pnl[-1]) - item['net_profit']) < 1e-7
            for p, inc in zip(curve, increments):
                months.setdefault(p['date'][:7], {})[symbol] = months.setdefault(p['date'][:7], {}).get(symbol, 0) + float(inc)
            rows.append(dict(symbol=symbol, net_profit=item['net_profit'], contribution_pp=item['net_profit']/initial*100,
                average_weight_pct=float(np.mean([a['weight'] for a in assets]))*100,
                held_close_days=sum(a['shares'] > 0 for a in assets),
                close_price_change_pct=(assets[-1]['close']/assets[0]['close']-1)*100,
                fees=assets[-1]['fees'], impact_cost=assets[-1]['impact_cost']))
        rows.sort(key=lambda x: -x['net_profit'])
        for i, p in enumerate(curve):
            assert abs(sum(a['realized_pnl']+a['unrealized_pnl'] for a in p['assets'].values())-(p['equity']-initial)) < 1e-6
        total = sum(x['net_profit'] for x in rows)
        assert abs(total - (curve[-1]['equity']-initial)) < 1e-6
        assert abs(sum(sum(v.values()) for v in months.values())-total) < 1e-6
        accounts.append(dict(cost_multiplier=r['cost_multiplier'], config=r['config'], metrics=r['metrics'], first_session=curve[0]['date'],last_session=curve[-1]['date'],
            rows=rows, monthly_pnl=months, positive_stocks=sum(x['net_profit']>0 for x in rows),
            top3_share_of_net_profit=sum(x['net_profit'] for x in rows[:3])/total,
            top5_share_of_net_profit=sum(x['net_profit'] for x in rows[:5])/total,
            checks={'daily_pnl_conservation':True,'terminal_contribution_match':True,'monthly_conservation':True}))
    payload=dict(source=str(SOURCE),sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),accounts=accounts,
        scope='Descriptive frozen-path accounting, not causal exclusion, forecast or suitability validation; raw prices exclude dividends and cash interest.')
    OUT.with_suffix('.json').write_text(json.dumps(payload,indent=2)+'\n')
    lines=['# 原20股固定策略组合：收益来源审计','',
        '冻结现有账本进行描述性归因，不重新选择股票、调参或训练。区间2025-09-01至2026-09-01（右端不含），起始资金100,000美元；原价格、未计股息与现金利息。不是完整总回报，也不是适用性证明。', '',
        '## 策略机制', '',
        '代码中的 fixed_ensemble 将横截面动量、通道趋势、残差反转三个目标等权平均。动量用63日至5日前的对数涨幅选正收益前25%；通道突破此前55日高点开启、跌破此前20日低点关闭；残差反转用63日对池内等权市场回归，最近5日标准化残差低于−1时介入。各分支按逆波动分配、单股上限20%，组合以收缩协方差估计控制年化波动至10%。实际每5个交易日调仓，并受分批、成本、止损及共享资金约束。', '',
        '这些是价格行为机制，不直接判断企业质量。动量和通道可能捕获持续上涨，反转可能捕获相对回落后的修复；是否真正创造超额收益仍需分支消融和匹配风险的对照，不能从总收益直接推断。', '']
    for a in accounts:
        lines += [f"## 费用倍数 {a['cost_multiplier']}",'',f"收益 {a['metrics']['return_pct']:.4f}%，最大回撤 {a['metrics']['max_drawdown_pct']:.4f}%；{a['positive_stocks']}/20 股贡献为正。事后前3/前5名占组合净利润 {a['top3_share_of_net_profit']:.2%}/{a['top5_share_of_net_profit']:.2%}。",'',
        '|股票|净贡献美元|账户收益贡献百分点|平均收盘权重%|持仓收盘日|区间收盘价涨跌%|', '|---|---:|---:|---:|---:|---:|']
        for x in a['rows']:
            lines.append(f"|{x['symbol']}|{x['net_profit']:.2f}|{x['contribution_pp']:.3f}|{x['average_weight_pct']:.2f}|{x['held_close_days']}|{x['close_price_change_pct']:.2f}|")
        lines += ['', '|月份|组合净贡献美元|当月最大贡献股票|该股贡献美元|','|---|---:|---|---:|']
        for month, v in sorted(a['monthly_pnl'].items()):
            best=max(v,key=v.get)
            lines.append(f'|{month}|{sum(v.values()):.2f}|{best}|{v[best]:.2f}|')
        lines.append('')
    lines += ['## 解释边界与下一步','',
        '贡献含已实现和期末未实现盈亏，已扣账本成本；百分点以初始资金为分母，可以相加。区间价格涨跌仅为首尾收盘描述，不是按相同成交时点和费用构建的买入持有基准。持仓日按收盘统计，不代表所有盘中交易。', '',
        '事后贡献排名只解释这个已实现路径。删掉赢家后直接减去其利润，不等于真正排除该股再回测：共享资金、横截面排名、市场残差与协方差都会变化。下一步应在固定配置下跑三个分支及逐股排除对照，区分市场上涨、策略择时和资金竞争；这些已观察数据上的诊断仍不能升级为前瞻适用性。', '',
        '逐日单股盈亏和账户权益、终值贡献、逐月贡献守恒均检查通过。源档案SHA及所有逐股逐月数值见同名JSON。复现：`uv run --locked python scripts/report_original20_attribution.py`。']
    OUT.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    for a in accounts:
        print(a['cost_multiplier'], a['positive_stocks'], a['top3_share_of_net_profit'], [(x['symbol'],round(x['net_profit'],2)) for x in a['rows'][:5]])


if __name__ == '__main__':
    main()

"""Complete buffer geometry results, with separate legacy and banded gates."""
import json,math
from pathlib import Path
import numpy as np
ROOT=Path('docs/research-results')


def main():
    payload=json.loads((ROOT/'2026-09-22-buffer-geometry.json').read_text())
    assert payload['status']=='completed' and len(payload['results'])==84
    rows=payload['results'];index={(r['pool'],r['cost_multiplier'],r['method']):r for r in rows}
    gates=[]
    for candidate in ['pooled_only','fixed_entry','risk','boundary','risk_boundary']:
        for control in ['legacy','banded']:
            for cost in [1,2]:
                subset=[r for r in rows if r['method']==candidate and r['cost_multiplier']==cost and r['pool']!='original20']
                delta=[r['metrics']['return_pct']-index[r['pool'],cost,control]['metrics']['return_pct'] for r in subset]
                dd=[r['metrics']['max_drawdown_pct']-index[r['pool'],cost,control]['metrics']['max_drawdown_pct'] for r in subset]
                wins=sum(x>0 for x in delta)
                gates.append(dict(candidate=candidate,control=control,cost_multiplier=cost,wins=wins,pools=len(subset),median_difference_pp=float(np.median(delta)),passed=bool(wins>=math.ceil(len(subset)*2/3) and np.median(delta)>0 and not all(x>0 for x in dd))))
    accepted=[m for m in ['risk','boundary','risk_boundary'] if all(g['passed'] for g in gates if g['candidate']==m)]
    equivalence={}
    for method in ['pooled_only','fixed_entry']:
        same=[]
        for r in rows:
            if r['method']!=method:continue
            base=index[r['pool'],r['cost_multiplier'],'legacy']
            same.append(all(r[k]==base[k] for k in ['curve','metrics','contributions']))
        equivalence[method]=dict(exact_accounts=sum(same),total=len(same))
    lines=['# 固定缓冲能否继续提高：风险缩放与边缘交易','',
        '方案0a9687a在本轮运行前冻结。固定原三策略、股票池和所有比例阈值，共84账户：24旧对照精确复现、60新增执行变体。所有逐日现金/市值/盈亏和期末逐股贡献守恒通过。已观察开发数据，非独立确认，不按结果调阈值。', '',
        '## 原理', '',
        '固定2%权重缓冲对高低波动股票并不产生相同跟踪风险。risk以截至上一收盘63日简单收益波动率计算 b_i=b×median(sigma)/sigma_i，高波动股票缓冲较窄。缺失/零风险回退固定值。只对已有仓位生效，首次建仓门槛不变。它均衡的是独立风险近似，不是完整组合相关风险。', '',
        'boundary在偏离越界后只交易到缓冲边缘，保留一部分目标偏离；risk_boundary联合两者。首次建仓、零目标退出、止损与熔断不被边缘缓冲拦截，仍受实际流动性限制。目的是减少交易，但会造成长期跟踪偏差，不能从理论动机直接推导回报改善。', '',
        'pooled_only仅保留共享买单分配、日换手约束；fixed_entry再保留0.5%首次门槛，两者已有仓位门槛为0。这两个消融用于解释此前收益变化。', '',
        '## 精确归因', '',
        f'与legacy曲线、全部指标、逐股贡献同时完全相同：{equivalence}。这种相同只证明本组资金/订单条件下未产生变化，不等于共享分配在资金紧张时永远无效。', '',
        '## 原20股', '',
        '|执行|费用倍数|收益%|回撤%|交易数|费用与冲击美元|','|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['pool']!='original20':continue
        m=r['metrics'];lines.append(f"|{r['method']}|{r['cost_multiplier']}|{m['return_pct']:.3f}|{m['max_drawdown_pct']:.3f}|{m['trade_count']}|{m['fees']+m['impact_cost']:.2f}|")
    lines += ['', '## 非原20股跨池门槛', '',
        '其余5池至少4/5收益改善、中位差>0、回撤不能全部恶化；正常与双费都需通过，分别相对原legacy与上轮banded报告。', '',
        '|候选|对照|费用倍数|改善池数|收益差中位数百分点|通过|','|---|---|---:|---:|---:|---|']
    for g in gates:lines.append(f"|{g['candidate']}|{g['control']}|{g['cost_multiplier']}|{g['wins']}/5|{g['median_difference_pp']:+.3f}|{g['passed']}|")
    lines += ['',f'同时通过两费用、两对照的新增缓冲候选：{accepted or "无"}。', '', '## 全部84账户','',
        '|池|执行|费用|收益%|回撤%|平均仓位%|交易数|费用与冲击美元|停机|','|---|---|---:|---:|---:|---:|---:|---:|---|']
    for r in rows:
        m=r['metrics'];lines.append(f"|{r['pool']}|{r['method']}|{r['cost_multiplier']}|{m['return_pct']:.3f}|{m['max_drawdown_pct']:.3f}|{m['average_gross_exposure_pct']:.2f}|{m['trade_count']}|{m['fees']+m['impact_cost']:.2f}|{m['halted']}|")
    lines += ['', '## 结论', '',
        '本轮没有得到比上轮固定缓冲更可靠的升级。原20股正常费用：banded 22.5318%、risk 21.3802%、boundary 20.6031%、risk_boundary 20.3000%。风险缩放在其他五池两费用均仅3/5改善；边缘交易多数退步。原20股正常费用交易次数也由固定缓冲410升至417/432/443，较小单笔调整并未减少总交易次数。', '',
        'pooled_only与fixed_entry各12账户都精确等同legacy：在这些数据、现金和配置下，上轮利润变化来自已有持仓的调仓缓冲，而非按比例资金分配或首次门槛。不能推广为资金分配在更紧张预算下无作用。', '',
        '固定缓冲原20股费用与冲击1134.55美元，相当于初始资本1.13个百分点；在完全固定成交股数与时间的记账诊断中，抹掉这些成本也只直接增加这部分利润。这不是重新模拟零费用账户的收益上界，因为资金反馈会改变后续成交。要取得更大且可推广的提升，需要新的可验证信号优势，不能只期待进一步微调成交门槛。', '',
        '不推出新默认、不自动改已发布策略；上轮固定缓冲仍是可试用版本，且原有跨池失败与双费局限继续保留。', '',
        '## 使用与限制', '',
        '本轮不改变默认或已发布参数。后台execution_buffer字段支持fixed/risk/boundary/risk_boundary，只在portfolio_policy=banded时生效；fixed默认保持上轮版本完全一致。未通过的变体不增设网页推荐入口。风险参数是截至前一收盘的滚动估计，不使用当前日收盘/成交量。', '',
        '仍用原价格、无股息无现金利息，不能叫完整总回报。三个年度池是2025-09至2026-09，三个temporal池是2022-09至2025-09。终值含未实现盈亏，停机后现金不计息；双费下收益偶尔更好可能来自风控路径变化，不代表费用有益。', '',
        '复现：uv run --locked python scripts/study_buffer_geometry.py；uv run --locked python scripts/report_buffer_geometry.py。同名full.json.gz保存全部资产路径，sources.json保存源SHA。所有候选与亏损结果保留。']
    (ROOT/'2026-09-22-buffer-geometry.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-buffer-geometry-gates.json').write_text(json.dumps(dict(gates=gates,accepted=accepted,equivalence=equivalence),indent=2)+'\n')
    print(json.dumps(dict(accepted=accepted,equivalence=equivalence,gates=[g for g in gates if g['control']=='banded']),indent=2))

if __name__=='__main__':main()

"""Report every predeclared phase experiment without selecting winners."""
import gzip
import json
from pathlib import Path

ROOT = Path('docs/research-results')

def main():
    path = ROOT/'2026-09-22-phase-diversification.json'
    data = json.loads(path.read_text())
    full = json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    assert data['status']==full['status']=='completed'
    rows=data['results']
    assert len(rows)==len(full['results'])==30
    for compact, archived in zip(rows, full['results']):
        assert {k:v for k,v in compact.items() if k!='curve'} == {k:v for k,v in archived.items() if k!='curve'}
        assert compact['curve'] == [{k:v for k,v in point.items() if k not in ('positions','assets')} for point in archived['curve']]
    checks=json.loads((ROOT/'2026-09-22-phase-diversification-checks.json').read_text())
    assert len(checks['checks'])==5
    assert all(all(c[k] for k in ('baseline_exact','prefix_invariant','phase_identity','weight_bounds')) for c in checks['checks'])
    windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows))
    assert len(windows)==5
    controls=json.loads((ROOT/'2026-09-22-asset-pool.json').read_text())['results']
    lines=['# 共享资金下的调仓相位分散','',
           '## 依据与实现','',
           '运行前协议2cadbb1。Hoffstein等《Rebalance Timing Luck: The (Dumb) Luck of Smart Beta》（DOI 10.2139/ssrn.3673910）的Crossref摘要支持检验调仓日期敏感性；未读取全文，也未声称复现论文。博客请求403。', '',
           '固定低资产增长筛选，20个相位全部等权保留。第一日全部初始化为同一目标，此后每天更新一个相位；成熟后总目标等于最近20日原始目标的均值。用一个100000共享现金账户净额交易，不能理解为20个账户各投100000再平均收益。', '',
           'baseline为原20日决策；daily_hold每日按原20日目标重设股数；phase20每日按相位均值重设股数。后二者均次日成交。daily_hold控制了执行频率变化，但平滑也会改变目标时效与风险，不能声称仅隔离时间运气。均保留原分批、整股、费用、止损和永久停机。平均权重保持20%单股及95%总预算上限，但不保证按当日协方差衡量的波动始终小于10%。','',
           '## 全部结果','',
           '|股票池|区间（终点不含）|费用倍数|原策略收益%|每日原目标%|相位平均%|相位回撤%|相位首次停机|同资格基线收益%|',
           '|---|---|---:|---:|---:|---:|---:|---|---:|']
    differences=[]
    for pool,start,end in windows:
        for mult in [1,2]:
            part={r['method']:r for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
            assert set(part)=={'baseline','daily_hold','phase20'}
            b,h,p=(part[k] for k in ['baseline','daily_hold','phase20'])
            eligible=next(r for r in controls if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'],r['method'])==(pool,start,end,mult,'eligible'))
            val=lambda r:r['metrics']['return_pct']
            lines.append(f"|{pool}|{start}—{end}|{mult}|{val(b):+.3f}|{val(h):+.3f}|{val(p):+.3f}|{p['metrics']['max_drawdown_pct']:.3f}|{p['first_halt'] or '无'}|{val(eligible):+.3f}|")
            differences.append(dict(pool=pool,start=start,end=end,cost_multiplier=mult,phase_minus_baseline_pp=val(p)-val(b),phase_minus_daily_hold_pp=val(p)-val(h),phase_minus_eligible_pp=val(p)-val(eligible)))
    normal=[r for r in rows if r['method']=='phase20' and r['cost_multiplier']==1]
    wins=sum(d['phase_minus_baseline_pp']>0 for d in differences if d['cost_multiplier']==1)
    negatives=sum(r['metrics']['return_pct']<0 for r in normal)
    halted=sum(r['metrics']['halted'] for r in normal)
    lines+=['','## 结论与限制','',f'正常费用5窗口中相位平均高于原策略{wins}个，亏损{negatives}个，永久停机{halted}个。年度与连续窗口重叠，不是独立样本，不能给出胜率显著性。最新62股亦包含旧研究股票；全部数据已用于开发，不能视为新确认集。', '',
            '本轮仅检验共享资金执行机制，未提供新的企业类型适用判据。即使个别窗口改善，也不能用最好结果覆盖连续账户或失败窗口，不能从本轮升级正式“适用”状态。原价及尚未完整核验的分红/公司行动缺口保留，收益不声称完整净总回报。', '',
            '## 验证与复现','',
            '10个原策略对照全部指标和逐股贡献精确复现。每个窗口每日原始目标的20日抽样等于旧映射；相位平均与独立滑动均值恒等；全部目标权重边界和数据前缀不变性通过。30账户×方法费用组合和完整压缩档案检查齐全。来源行情哈希记录于checks文件，财报来源沿用asset-pool-data清单。', '',
            '`uv run --locked python scripts/study_phase_diversification.py`，然后 `uv run --locked python scripts/report_phase_diversification.py`。JSON及full.json.gz保留全部账户指标、费用、贡献与权益/持仓曲线。总体研究目标尚未完成。']
    (ROOT/'2026-09-22-phase-diversification.md').write_text('\n'.join(lines)+'\n')
    (ROOT/'2026-09-22-phase-diversification-comparison.json').write_text(json.dumps(differences,indent=2)+'\n')
    print('\n'.join(lines[10:]))

if __name__=='__main__':main()

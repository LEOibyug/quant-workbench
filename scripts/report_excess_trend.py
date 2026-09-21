"""Report all rate-consistent trend accounts against matched cash paths."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-excess-trend.json';data=json.loads(p.read_text());full=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=data['results']
 assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==72
 for a,b in zip(rows,full['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in d.items() if k not in ('positions','assets')} for d in b['curve']]
 checks=json.loads((ROOT/'2026-09-22-excess-trend-checks.json').read_text())
 assert len(checks['checks'])==len(checks['pure_cash'])==12
 windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows));assert len(windows)==12
 lines=['# 价格趋势相对现金收益：统一计息对照','',
 '协议9a622b0在运行前冻结。以252日价格涨幅是否超过同周期滞后SOFR现金指数作为门控，比较阈值零的原趋势与无筛选逆波动。所有实际账户现金均按相同利率计息，终点为最后交易日收盘；不是以现金收益作为选股alpha。','',
 '保留63日波动/协方差、原全池逆波动再乘信号（不重分配被排除权重）、10%风险向下缩放、20%单股上限、20日决策、整股分批与原止损/停机。三历史池各三年度及连续三年，共72账户，未调参。','',
 '|池|区间终点不含|费用|超过现金趋势%|原价格趋势%|不筛选逆波动%|纯现金%|超过现金趋势回撤%|','|---|---|---:|---:|---:|---:|---:|---:|']
 comparisons=[]
 for pool,start,end in windows:
  cash=next(c['return_pct'] for c in checks['pure_cash'] if (c['pool'],c['start'],c['end'])==(pool,start,end))
  for mult in [1,2]:
   part={r['method']:r['metrics'] for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
   assert set(part)=={'excess_trend','raw_trend','inverse_vol'}
   e,r,b=[part[k] for k in ['excess_trend','raw_trend','inverse_vol']]
   lines.append(f"|{pool}|{start}/{end}|{mult}|{e['return_pct']:+.3f}|{r['return_pct']:+.3f}|{b['return_pct']:+.3f}|{cash:+.3f}|{e['max_drawdown_pct']:.3f}|")
   comparisons.append(dict(pool=pool,start=start,end=end,cost_multiplier=mult,excess_minus_cash_pp=e['return_pct']-cash,excess_minus_raw_pp=e['return_pct']-r['return_pct'],excess_minus_unfiltered_pp=e['return_pct']-b['return_pct']))
 normal=[c for c in comparisons if c['cost_multiplier']==1]
 lines+=['','## 结论与限制','',f"正常费用12窗口中，超过现金门控高于纯现金{sum(c['excess_minus_cash_pp']>0 for c in normal)}个，高于原趋势{sum(c['excess_minus_raw_pp']>0 for c in normal)}个，高于不筛选{sum(c['excess_minus_unfiltered_pp']>0 for c in normal)}个。时间窗口重叠，不能称12次独立检验，也不能因绝对收益为正直接认定策略有效。",'',
 '本轮是机会成本一致性的开发消融，未增加企业经济属性模型。现金收益需要账户具备相应工具；SOFR为假设参考，不是零售可得收益。现行历史数据可能修订，滞后处理不证明初版时点完全一致。股票分红尚未完整计入，所以信号是价格相对现金趋势而非完整总回报趋势；此缺口不能据结果被隐去。','',
 '三池均已被用于研究且共享宏观时期；尚不足以交付经过独立确认的适用性判断，总体目标仍未完成。','',
 '## 验证','',
 '12窗口原价格趋势及不筛选映射精确复现旧tsmom实现；现金利率置零时新门控与原趋势相同。真实数据前缀检查通过；同一个现金账本构造信号和可用现金收益。所有动态账户逐日及期末权益由股票净贡献与利息守恒，72费用方法组合和完整档案一致。行情与1040条SOFR快照哈希及完整利率记录保存。','',
 '复现：`uv run --locked python scripts/study_excess_trend.py`；`uv run --locked python scripts/report_excess_trend.py`。未改网页或默认策略。']
 (ROOT/'2026-09-22-excess-trend.md').write_text('\n'.join(lines)+'\n');(ROOT/'2026-09-22-excess-trend-comparison.json').write_text(json.dumps(comparisons,indent=2)+'\n');print('\n'.join(lines[6:]))

if __name__=='__main__':main()

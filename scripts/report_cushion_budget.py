"""Complete equity cushion results; cash is a benchmark, not discovered alpha."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-cushion-budget.json';d=json.loads(p.read_text());f=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=d['results']
 assert d['status']==f['status']=='completed' and len(rows)==len(f['results'])==18
 assert {(r['pool'],r['method'],r['cost_multiplier']) for r in rows}=={(p,m,c) for p in ['random10','transfer12','new12'] for m in ['uncapped','constant30','cushion'] for c in [1,2]}
 for a,b in zip(rows,f['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in point.items() if k not in ('positions','assets')} for point in b['curve']]
 cash=json.loads((ROOT/'2026-09-22-excess-trend-checks.json').read_text())['pure_cash']
 cash={r['pool']:r['return_pct'] for r in cash if r['start']=='2022-09-01' and r['end']=='2025-09-01'}
 lines=['# 权益缓冲风险预算与固定低仓位对照','',
 '协议ceff19b在运行前冻结。Sharpe作者目录 https://web.stanford.edu/~wfsharpe/art/art.htm 核实Perold/Sharpe1988论文题录，Crossref返回1995重印DOI10.2469/faj.v51.n1.1871；未读原文，猜测正文URL404。本实验是明确自定义峰值缓冲预算，不声称复现CPPI或本金保险。','',
 '每收盘股票总目标上限=min(95%,3×max(权益−90%历史峰值,0)/权益)。初始为30%，回撤时收缩。基础为全股票逆波动/10%协方差预算；对照无额外上限和固定30%，全部每天更新目标、次日按原分批规则执行，同SOFR现金收益、同费用与原止损/永久停机。保留对照以区分动态反馈和单纯降低仓位。','',
 '|池|费用|预算|收益%|回撤%|股票暴露%|停机|同期纯现金%|','|---|---:|---|---:|---:|---:|---|---:|']
 for r in rows:
  m=r['metrics'];lines.append(f"|{r['pool']}|{r['cost_multiplier']}|{r['method']}|{m['return_pct']:+.3f}|{m['max_drawdown_pct']:.3f}|{m['average_gross_exposure_pct']:.2f}|{m['halted']}|{cash[r['pool']]:+.3f}|")
 comparisons=[]
 for pool in cash:
  for mult in [1,2]:
   part={r['method']:r['metrics'] for r in rows if r['pool']==pool and r['cost_multiplier']==mult}
   comparisons.append(dict(pool=pool,cost_multiplier=mult,cushion_minus_cash_pp=part['cushion']['return_pct']-cash[pool],cushion_minus_constant_pp=part['cushion']['return_pct']-part['constant30']['return_pct'],cushion_minus_uncapped_pp=part['cushion']['return_pct']-part['uncapped']['return_pct']))
 lines+=['','## 解释边界','',
 '正常费用动态缓冲三池收益+10.89/+11.87/+8.08%，回撤3.77/4.05/4.45%；全部低于固定30%仓位，也低于同利率纯现金+15.39%。减少停机与回撤并未产生稳定收益增量，不能仅以三池绝对盈利认定目标完成。','',
 '峰值90%是目标风险线而非保证：隔夜跳空、分批成交和调整延迟可造成突破，绝不宣称本金保护。动态预算未关闭原永久停机，触发后仍按原规则清仓。每天重设股数会产生交易，三个对照同频率但费用路径不同。','',
 '更低回撤不足以证明有效股票交易；须同时比较固定30%及同利率纯现金，不能把现金利息当新增alpha。三池均为已研究样本、同宏观历史，只有三个连续账户环境，不构成独立统计确认。原价分红/公司行动缺口与SOFR情景可得性限制仍存在。','',
 '## 核验','',
 '研究接口默认关闭，限定daily legacy并拒绝非有限或超出[0,1]的上限。6个无上限对照与显式1.0上限的指标、逐股贡献和成交精确复现。初始30%、回撤5%时15/95、回撤10%时零的解析例通过；所有决策上限只缩小原目标，逐日股票盈亏+利息=权益变动。18账户完整档案核验，9项既有相关测试通过。','',
 '复现：`uv run --locked python scripts/study_cushion_budget.py`；`uv run --locked python scripts/report_cushion_budget.py`。未改网页默认策略。总体目标仍未完成。']
 (ROOT/'2026-09-22-cushion-budget.md').write_text('\n'.join(lines)+'\n');(ROOT/'2026-09-22-cushion-budget-comparison.json').write_text(json.dumps(comparisons,indent=2)+'\n');print('\n'.join(lines[6:]))

if __name__=='__main__':main()

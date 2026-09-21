"""Verify and compare dynamic cash-interest research scenarios."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-cash-feedback.json';d=json.loads(p.read_text());f=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=d['results']
 assert d['status']==f['status']=='completed' and len(rows)==len(f['results'])==12
 assert {(r['method'],r['scenario'],r['cost_multiplier']) for r in rows}=={(m,s,c) for m in ['low_liability','eligible'] for s in ['zero','sofr','sofr_minus1'] for c in [1,2]}
 for a,b in zip(rows,f['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in x.items() if k not in ('positions','assets')} for x in b['curve']]
 checks=json.loads((ROOT/'2026-09-22-cash-feedback-checks.json').read_text())
 lines=['# 现金利息的完整资金与风控反馈','',
 '协议bc604e7固定。研究参数默认关闭，仅daily legacy且不与其他公司行动研究账本混用。前收盘现金按有效日严格早于前收盘的最近SOFR计日历天数/360利息，下一开盘到账后可交易；利息进入权益/风险，单列收入，不混入单股盈亏。SOFR为明确情景，非券商承诺收益，现行历史快照不等于无修订实时记录。','',
 '固定新12股低负债与同资格账户、两费用、零/SOFR/减1百分点三情景共12账户。首日不计息，终止在2025-08-29最后实际收盘，不对之后周末计息；纯现金也使用同一日历。此前静态审计截至end且有额外一交易日滞后，因此不能要求其现金数字与此完全相同。','',
 '|策略|费用|利率情景|收益%|回撤%|利息收入USD|停机|','|---|---:|---|---:|---:|---:|---|']
 for r in rows:
  m=r['metrics'];lines.append(f"|{r['method']}|{r['cost_multiplier']}|{r['scenario']}|{m['return_pct']:+.4f}|{m['max_drawdown_pct']:.4f}|{m.get('cash_interest_income',0):.2f}|{m['halted']}|")
 lines+=['','## 同期纯现金情景','']
 for c in checks['pure_cash']:lines.append(f"- 年率折减{c['haircut']}个百分点：{c['return_pct']:+.4f}%；{c['first_close']}至{c['last_close']}收盘。")
 lines+=['','## 含义与限制','',
 '利息能够改变可买股数、权益峰值与永久停机，所以不得把固定路径累计利息直接加到原收益作为替代。本轮动态结果才包含这些反馈。低负债组转正不代表选股因子有效；必须看其相对同利率纯现金和同资格账户的增量，且现金基准不可直接在真实券商保证获得。','',
 '这仍是价格与现金收益研究账户，不是完整股票总回报：股票现金分红和公司行动缺口没有自动修复。本轮未变更此前因子、窗口、账户止损参数；未将有利利率或停机变化当作满足研究目标，正式适用性仍证据不足。','',
 '## 检查','',
 '四个原零利率账户全部指标/逐股贡献精确复现；同四账户显式零利率账本同样复现指标、贡献及成交。动态情景逐日股票已实现+未实现盈亏+累计利息等于权益变动，最终逐股净贡献+利息守恒；利息本金与前收盘现金逐项对账。12账户完整档案核验。','',
 '9项相关测试通过，包括周末计息、利率滞后、复利、缺率/无效现金/重复记账拒绝，以及既有日线/分红/分拆行为。生产默认不传研究参数，未改变网页行为。','',
 '复现：`uv run --locked python scripts/study_cash_feedback.py`；`uv run --locked python scripts/report_cash_feedback.py`。总体研究目标未完成。']
 (ROOT/'2026-09-22-cash-feedback.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines[6:]))

if __name__=='__main__':main()

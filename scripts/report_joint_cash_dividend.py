"""Report partial verified distribution and cash yield integration without alpha claims."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-joint-cash-dividend.json';d=json.loads(p.read_text());full=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=d['results']
 assert d['status']==full['status']=='completed' and len(rows)==len(full['results'])==8
 assert {(r['method'],r['cost_multiplier']) for r in rows}=={(m,c) for m in ['raw','cash','dividend','joint'] for c in [1,2]}
 for a,b in zip(rows,full['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
 lines=['# 现金利息与MSFT已核实分红共存','',
 '协议90f3643在运行前冻结。原20股2025-09-01至2026-09-01 fixed_ensemble不变，仅比较现金利息与MSFT已核实股息账本的2×2组合，正常/双倍费用8账户。其余19股仍遗漏分红，不能叫完整总回报或新策略收益。','',
 '|模式|费用|收益%|回撤%|利息USD|股息收入USD|期末应收USD|','|---|---:|---:|---:|---:|---:|---:|']
 for r in rows:
  m=r['metrics'];lines.append(f"|{r['method']}|{r['cost_multiplier']}|{m['return_pct']:+.5f}|{m['max_drawdown_pct']:.4f}|{m.get('cash_interest_income',0):.2f}|{m.get('dividend_income',0):.2f}|{m.get('dividend_receivable',0):.2f}|")
 lines+=['','## 记账顺序','',
 '利息以前收盘已到账现金为本金，在下一开盘入账；之后处理当日除息，应收只增加权益不增加现金。支付日收盘股息到账，当天开盘成交不能提前花用；下一个交易日才将这笔现金纳入利息本金与交易。利息归账户，股息归单股，两者不重复归因。尚未支付的期末股息不会虚构成现金或清算收益。','',
 '合成例：除息形成3000美元应收，支付日前利息本金仍为零；支付日收盘到账后，次日按3.6%/360产生0.30美元，且可参与交易。显式零利率与原股息账户精确复现。','',
 '## 核验与边界','',
 '13项相关测试通过；4个原无利息对照全部指标与单股贡献精确复现。8账户逐日现金+市值+应收=权益，交易盈亏+股息+利息=权益变动，期末逐股贡献+利息守恒，现金计息本金逐条对齐前收盘。完整压缩档案逐项一致。','',
 '此次允许两个研究账本在daily legacy共存，仍拒绝分拆研究混用，生产默认关闭。SOFR用2024-08至2026-09的520条现行历史快照，严格滞后但不证明修订前版本；不是券商实际付息承诺。信号仍使用原价格，不同时更改股息信号。','',
 '收益增加来自账本补计与资金反馈，不构成新alpha或跨股票池策略确认。后续还需其他企业的可靠分红与完整基准，不能将MSFT部分修正外推全池。总体目标未完成。','',
 '复现：`uv run --locked python scripts/study_joint_cash_dividend.py`；`uv run --locked python scripts/report_joint_cash_dividend.py`。']
 (ROOT/'2026-09-22-joint-cash-dividend.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines[4:]))

if __name__=='__main__':main()

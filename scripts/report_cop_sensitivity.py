"""Report explicitly unverified COP ex-date sensitivity, never a total-return claim."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-cop-sensitivity.json';data=json.loads(p.read_text());full=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=data['results']
 assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==16
 assert len({(r['start'],r['end_exclusive'],r['offset'],r['cost_multiplier']) for r in rows})==16
 for a,b in zip(rows,full['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in x.items() if k not in ('positions','assets')} for x in b['curve']]
 checks=json.loads((ROOT/'2026-09-22-cop-sensitivity-checks.json').read_text());cash={(c['start'],c['end']):c['return_pct'] for c in checks['pure_cash']}
 lines=['# COP分红组成分与未决除息日敏感性','',
 '运行前协议45ad971。本报告是明确假设情景，不是独立核实权益日后的总回报。固定供应商金额/支付日，合计同日0.58+0.20时保留两个ID；VROC的发行人分类仍保留，kind=ordinary_cash仅为本情景假设的权益算法，并不把VROC法律类型改称普通股息。所有输入verified=false、currency=None、source_rate_scenario=true。','',
 '两窗口两费用各无股息/前一交易日/供应商日/后一交易日共16账户，现金均SOFR动态计息。日期平移只检验局部错误敏感性，不是任意可能权益日的收益界限。利息、已到账股息与除息应收分别核算；原低负债信号/风控保持不变，不做价格除息信号调整。','',
 '|区间终点不含|费用|除息偏移交易日|收益%|假设股息收入USD|回撤%|同率纯现金%|','|---|---:|---|---:|---:|---:|---:|']
 for r in rows:
  m=r['metrics'];lines.append(f"|{r['start']}/{r['end_exclusive']}|{r['cost_multiplier']}|{'无股息' if r['offset'] is None else r['offset']}|{m['return_pct']:+.4f}|{m.get('dividend_income',0):.2f}|{m['max_drawdown_pct']:.3f}|{cash[r['start'],r['end_exclusive']]:+.4f}|")
 lines+=['','## 解释与核验','',
 '原始组成分ID唯一、金额合计守恒，同日不误删0.20；已纳入0.78的普通股息不再另造0.20。偏移后不跨支付日、不产生未处理同日不同支付冲突。所有实际持仓始终只有COP。历史两费用无股息现金对照指标/贡献精确复现，16账户每日权益和累计股票净贡献+利息守恒，利息本金不含应收；完整档案逐项核验。','',
 '这里允许进入的是显式未核实情景，未改变发行人审计的book_ready=false。没有证明全部币种税务、权益法律类型、交易所除息指定、数据初版可见性或其他公司行动，也没有将供应商special=false视作法律证明。正收益或±1日范围不能成为企业适用性结论。','',
 '全部6个三年分红情景收益10.43%—10.81%，仍低于同率现金15.39%；正常供应商日期情景10.58%。最新一年6情景11.19%—11.48%高于现金3.88%，但不能替代跨期证据。这组局部假设未使连续账户超越现金，不继续为挽救低负债信号事后调日期；仍不称已核实完整总回报。总体目标未完成。','',
 '复现：`uv run --locked python scripts/study_cop_sensitivity.py`；`uv run --locked python scripts/report_cop_sensitivity.py`。未改生产策略或已核实事件库。']
 (ROOT/'2026-09-22-cop-sensitivity.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines[6:]))

if __name__=='__main__':main()

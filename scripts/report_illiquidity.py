"""Complete fixed volume-response experiment report."""
import gzip,json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
 p=ROOT/'2026-09-22-illiquidity.json';data=json.loads(p.read_text());full=json.loads(gzip.decompress(p.with_suffix('.full.json.gz').read_bytes()));rows=data['results']
 assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==30
 for a,b in zip(rows,full['results']):
  assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
  assert a['curve']==[{k:v for k,v in d.items() if k not in ('positions','assets')} for d in b['curve']]
 windows=list(dict.fromkeys((r['pool'],r['start'],r['end_exclusive']) for r in rows));assert len(windows)==5
 lines=['# 成交额价格反应：流动性补偿假设','',
 '协议9e47d3f先于回测。检索确认Amihud2002题录DOI10.1016/S1386-4181(01)00024-6，但正文/综述访问未成功；没有声称已读全文或复现论文。原作者旧页无研究，两个PDF路径404，综述出版社403。','',
 '自定义I=过去63交易日平均绝对简单收益/(当日收盘价×成交股数)，单位1/USD。成交额为近似值，I也可能包含波动和规模效应。高I为可能流动性补偿候选，低I为反向对照。每20日选最高/最低三分组及全部股票；保持原共享现金、逆波动/协方差预算、分批与停机。价格单位乘c且股数除c应保持I不变。','',
 '|池|区间终点不含|费用|高I收益%|低I收益%|全池收益%|高I回撤%|高I停机|','|---|---|---:|---:|---:|---:|---:|---|']
 summary=[]
 for pool,start,end in windows:
  for mult in [1,2]:
   part={r['method']:r['metrics'] for r in rows if (r['pool'],r['start'],r['end_exclusive'],r['cost_multiplier'])==(pool,start,end,mult)}
   assert set(part)=={'high_illiquidity','low_illiquidity','eligible'}
   h,l,e=[part[k] for k in ['high_illiquidity','low_illiquidity','eligible']]
   lines.append(f"|{pool}|{start}/{end}|{mult}|{h['return_pct']:+.3f}|{l['return_pct']:+.3f}|{e['return_pct']:+.3f}|{h['max_drawdown_pct']:.3f}|{h['halted']}|")
   summary.append(dict(pool=pool,start=start,end=end,cost=mult,high_negative=h['return_pct']<0,high_minus_eligible=h['return_pct']-e['return_pct']))
 normals=[x for x in summary if x['cost']==1]
 lines+=['','## 结论与限制','',f"正常费用5窗口高I组{sum(x['high_negative'] for x in normals)}个亏损，{sum(x['high_minus_eligible']>0 for x in normals)}个超过全池。没有建立跨池跨期可靠正向效果；不因局部结果改为只选低I组或调63日窗口。",'',
 '这是一项受流动性风险问题启发的短窗口代理实验，不是企业永久适用标签。全部样本已被研究，股票池和历史窗口重叠，不能把5个窗口当独立显著性样本。原价/分红和公司行动缺口保留；逆波动控制不能完全排除规模/波动混淆。','',
 '执行成本采用原固定费用和双倍敏感性，没有真实订单簿与冲击校准，不能以此确认高I股票的实盘可交易性。即使粗成本下盈利仍需容量验证，本轮失败则不应直接归因原文理论错误。','',
 '## 验证与复现','',
 '合成固定美元成交额序列精确核对I，并验证价格/股数单位逆向缩放不变；每个真实窗口价格前缀不改变过去目标。正有限价格/成交量、分组互斥与预算边界检查通过。30账户费用组合和完整档案逐项核验，输入SHA256保存。正式适用性仍证据不足，总体目标未完成。','',
 '`uv run --locked python scripts/study_illiquidity.py`；`uv run --locked python scripts/report_illiquidity.py`。未改变生产默认配置。']
 (ROOT/'2026-09-22-illiquidity.md').write_text('\n'.join(lines)+'\n');(ROOT/'2026-09-22-illiquidity-comparison.json').write_text(json.dumps(summary,indent=2)+'\n');print('\n'.join(lines[6:]))

if __name__=='__main__':main()

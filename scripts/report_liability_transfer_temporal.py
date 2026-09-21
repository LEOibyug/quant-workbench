"""All frozen earlier-period transfer outcomes and actual holding coverage."""
import gzip
import json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-liability-transfer-temporal.json'
    data=json.loads(path.read_text());full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    rows=data['results'];assert data['status']==full['status']=='completed' and len(rows)==len(full['results'])==24
    windows=list(dict.fromkeys((r['start'],r['end_exclusive']) for r in rows));assert len(windows)==4
    assert {(r['start'],r['end_exclusive'],r['method'],r['cost_multiplier']) for r in rows}=={(s,e,m,k) for s,e in windows for m in ['low_liability','high_liability','eligible'] for k in [1,2]}
    for a,b in zip(rows,full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
    lines=['# 新12股低负债筛选：跨时期检验','',
           '运行前协议9a18e84固定12公司和原参数，2022/2023/2024年9月起三个年度及连续三年，低/高/同资格正常与双倍费用24账户。补齐2021-08开始历史，三月请求；未更换企业、补字段、改预算或风险规则。所有账户初始现金100000，日线收盘决策、下一交易日成交。','',
           '## 全部结果','',
           '|开始/结束不含|费用|低负债收益%|高负债收益%|同资格收益%|低组回撤%|低组停机|','|---|---:|---:|---:|---:|---:|---|']
    for start,end in windows:
        for mult in [1,2]:
            part={r['method']:r['metrics'] for r in rows if (r['start'],r['end_exclusive'],r['cost_multiplier'])==(start,end,mult)}
            a,b,c=(part[m] for m in ['low_liability','high_liability','eligible'])
            lines.append(f"|{start}/{end}|{mult}|{a['return_pct']:+.4f}|{b['return_pct']:+.4f}|{c['return_pct']:+.4f}|{a['max_drawdown_pct']:.4f}|{a['halted']}|")
    coverage=json.loads((ROOT/'2026-09-22-liability-transfer-temporal-coverage.json').read_text())
    lines+=['','## 正常费用低组的覆盖','', '|区间|可计算股票数|实际曾持有|平均股票暴露%|','|---|---|---|---:|']
    for start,end in windows:
        c=next(x['coverage'] for x in coverage if (x['start'],x['end'])==(start,end))
        n=[len(d['eligible']) for d in c]
        r=next(r for r in full['results'] if (r['start'],r['end_exclusive'],r['method'],r['cost_multiplier'])==(start,end,'low_liability',1))
        held=sorted({s for p in r['curve'] for s,a in p['assets'].items() if a['market_value']>0})
        lines.append(f"|{start}/{end}|{min(n)}—{max(n)}|{', '.join(held)}|{r['metrics']['average_gross_exposure_pct']:.2f}|")
    lines+=['','## 解释边界','',
            '固定低负债规则跨时期未获支持：正常费用三个独立重启年度两亏，连续三年−7.1508%并永久停机，同资格基线+4.5604%。双倍费用连续−6.8013%也停机；费用更高而亏损略少源于路径/停机差异，不是成本有益。低组全部历史均只持COP，不能以最新+7.45%替代完整证据。后续不反选高组或调阈值挽救，转向其他经济机制。','',
            '不能把年度从现金重启的收益拼接为连续账户，也不能以最新一年的COP盈利替代过去的失败或风险。同一股票跨年份不是多个独立企业样本；股票池是人工当前成分，存在覆盖和存活偏差，历史宏观时期与旧研究相同。','',
            '同资格风险基线共享名义预算，但实际持仓/风险并不严格相同。最新与历史结果均为原价研究账户，缺完整分红和公司行动处理；粗略跳空检查通过不能证明全部公司行动无误。正式适用性仍保留证据不足，总体目标尚未完成。','',
            '## 核验与复现','',
            '每支股票日历完整、无重复及超过既定阈值的价格断点；源行情SHA256记录于data。四个窗口真实价格前缀不改变过去判断；24方法费用组合、全部压缩档案指标/贡献和权益曲线与紧凑结果一致。','',
            '使用 `.env` 环境运行 `scripts/study_liability_transfer_temporal.py` 下载及回测（密钥不输出）；再运行 `uv run --locked python scripts/report_liability_transfer_temporal.py`。未改网页或生产默认策略。']
    (ROOT/'2026-09-22-liability-transfer-temporal.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))

if __name__=='__main__':main()

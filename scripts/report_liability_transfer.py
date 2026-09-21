"""Frozen transfer results with accounting coverage and concentration limits."""
import gzip
import json
from pathlib import Path
ROOT=Path('docs/research-results')

def main():
    path=ROOT/'2026-09-22-liability-transfer.json'
    data=json.loads(path.read_text());full=json.loads(gzip.decompress(path.with_suffix('.full.json.gz').read_bytes()))
    assert data['status']==full['status']=='completed' and len(data['results'])==len(full['results'])==6
    assert {(r['method'],r['cost_multiplier']) for r in data['results']}=={(m,k) for m in ['low_liability','high_liability','eligible'] for k in [1,2]}
    coverage=json.loads((ROOT/'2026-09-22-liability-transfer-coverage.json').read_text())
    lines=['# 新12企业负债筛选迁移检验','',
           '下载前协议2009ca7固定DE、HON、RTX、TMO、DHR、AMGN、SBUX、TGT、CSX、FDX、CMCSA、COP。人工跨行业列举，非随机抽样；与既有62股无重叠，但当前股票选择仍有存活偏差。同一2025—2026市场时段，不是新的时间样本，也不是总体研究成功声明。','',
           '全部12股2024-08-01至2026-09-01共6264行原价SIP日线取得，三月分段、会话完整、无触发0.65/1.5倍粗略跳空检查；该检查不等于完整公司行动审计。SEC当前ticker/CIK全部匹配，不代表历史经济实体连续性已完整核验。','',
           '严格同申报直接Liabilities/Assets，仅DE、RTX、SBUX、CSX、COP满足。未因缺数据替换其他7家，也没有临时推导字段。每20日分组、相同共同预算、初始现金100000、原交易/风控和正常/双倍费用不变。','',
           '|策略|费用倍数|收益%|回撤%|平均股票暴露%|交易次数|停机|曾持有股票|',
           '|---|---:|---:|---:|---:|---:|---|---|']
    for a,b in zip(data['results'],full['results']):
        assert {k:v for k,v in a.items() if k!='curve'}=={k:v for k,v in b.items() if k!='curve'}
        assert a['curve']==[{k:v for k,v in p.items() if k not in ('positions','assets')} for p in b['curve']]
        held=sorted({s for p in b['curve'] for s,v in p['assets'].items() if v['market_value']>0})
        m=a['metrics']
        lines.append(f"|{a['method']}|{a['cost_multiplier']}|{m['return_pct']:+.4f}|{m['max_drawdown_pct']:.4f}|{m['average_gross_exposure_pct']:.2f}|{m['trade_count']}|{m['halted']}|{', '.join(held)}|")
    selected={k:sorted({s for d in coverage for s in d['selected'][k]}) for k in ['low_growth','high_growth','eligible']}
    lines+=['','## 选择与解释','',f"全期候选低负债组：{', '.join(selected['low_growth'])}；高组：{', '.join(selected['high_growth'])}。每次只有5家可计算，三分组每组只取1支，共同名义预算20%。因此即便某组盈利，也主要是少数企业的交易路径，不能视为已验证普遍企业类型。",'',
            '正常费用低组+7.4503%对比同资格+6.6995%，仅高0.7508个百分点，但最大回撤4.9350%对比1.2708%，收益改善伴随明显更高集中风险。双倍费用低组+7.1742%对比+6.6165%。全期只持COP不能成为广泛企业类型确认。','',
            '本轮不训练、不调参、不反选高组。低负债组相对同资格账户的收益差仍混合实际暴露、风险与个股路径；不得将正收益直接等同于筛选增量。原价及分红缺口尤其影响股息企业，未声称完整净总回报。总体目标尚未完成。','',
            '## 验证和复现','',
            '原名单与62股无重叠，下载完整日历及来源哈希保留。真实价格前缀不变；6个方法费用组合及完整压缩档案逐项核验。SEC覆盖与缺失原因保留于fundamentals，逐日判断和选股保留于coverage。', '',
            '依次执行 `uv run --locked python scripts/prepare_liability_transfer.py`；用 `.env` 环境运行 `scripts/download_liability_transfer.py`（不输出密钥）；`uv run --locked python scripts/study_liability_transfer.py`；`uv run --locked python scripts/report_liability_transfer.py`。未接入网页。']
    (ROOT/'2026-09-22-liability-transfer.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))

if __name__=='__main__':main()

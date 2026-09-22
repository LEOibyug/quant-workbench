"""Rolling forecast diagnostics with block uncertainty; not trading returns."""
import gzip,json
from pathlib import Path
import numpy as np
from scipy.stats import rankdata
ROOT=Path('docs/research-results');P=ROOT/'2026-09-22-lead-lag'


def interval(series,rng):
    n=len(series);blocks=int(np.ceil(n/21))
    starts=rng.integers(0,n,size=(2000,blocks))
    indices=((starts[:,:,None]+np.arange(21))%n).reshape(2000,-1)[:,:n]
    means=series[indices].mean(axis=1)
    # 12 comparisons; nominal Bonferroni 95% family coverage under bootstrap assumptions.
    return list(map(float,np.quantile(means,[.05/24,1-.05/24])))


def main():
    payload=json.loads(gzip.decompress(P.with_suffix('.full.json.gz').read_bytes()))
    assert payload['status']=='completed' and len(payload['pools'])==6
    output=[];rng=np.random.default_rng(20260922)
    for pool in payload['pools']:
        rows=[r for r in pool['rows'] if 'actual' in r]
        actual=np.array([r['actual'] for r in rows]);var=np.array([r['training_variance'] for r in rows])
        pred={m:np.array([r['predictions'][m] for r in rows]) for m in rows[0]['predictions']}
        metrics={};base_mse=np.mean((actual-pred['mean'])**2)
        for method,values in pred.items():
            mse=float(np.mean((actual-values)**2));ics=[]
            for a,b in zip(actual,values,strict=True):
                ra=rankdata(a);rb=rankdata(b)
                if np.std(ra)>0 and np.std(rb)>0:ics.append(float(np.corrcoef(ra,rb)[0,1]))
            metrics[method]=dict(mse=mse,r2_vs_mean=1-mse/base_mse,direction_accuracy=float(np.mean((values>0)==(actual>0))),mean_cross_section_spearman=float(np.mean(ics)),ic_days=len(ics))
        comparisons={}
        for control in ['own_market','shifted']:
            daily=(((actual-pred[control])**2-(actual-pred['network'])**2)/var).mean(axis=1)
            comparisons[control]=dict(normalized_mse_improvement=float(daily.mean()),bonferroni_block_interval=interval(daily,rng),daily=daily.tolist())
        output.append(dict(pool=pool['pool'],start=pool['start'],end_exclusive=pool['end_exclusive'],dates=[r['day'] for r in rows],first_entry=rows[0]['entry'],last_maturity=rows[-1]['maturity'],days=len(rows),stocks=actual.shape[1],metrics=metrics,comparisons=comparisons,checks=pool['checks']))
    wins=sum(r['comparisons']['own_market']['normalized_mse_improvement']>0 for r in output)
    historical_wins=sum(r['comparisons']['own_market']['normalized_mse_improvement']>0 for r in output if 'temporal' in r['pool'])
    negative=[(r['pool'],control) for r in output for control,c in r['comparisons'].items() if c['bonferroni_block_interval'][1]<0]
    gate=dict(wins_vs_own_market=wins,historical_wins=historical_wins,significant_negative=negative,advance_to_accounts=wins>=4 and historical_wins>0 and not negative)
    result=dict(pools=output,gate=gate,bootstrap=dict(block_days=21,draws=2000,seed=20260922,comparisons=12,scope='nominal block bootstrap, development data, not all historical searches'))
    P.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 跨股票信息传递：先验证增量预测信息','',
        '本轮跳出原三策略与执行缓冲，测试不同股票过去5日收益是否包含下一段可成交收益的增量信息。六池、四模型、逐日滚动训练，先检查预测证据，不先堆叠资金回测。', '',
        '## 文献与假设','',
        '读取Hou工作论文Crossref摘要（DOI 10.2139/ssrn.463005），核验2007期刊版本10.1093/revfin/hhm003题录。摘要主要涉及行业内部信息扩散、大股领先小股及负面信息；本轮任意大型股池网络不等于原文复现，也不保证日线尺度存在效应。Hong/Torous/Valkanov2007仅核验题录。完整检索记录包含2026年预印本摘要，但未据此确认因果结论。没有声称读全文。', '',
        '## 模型和时序','',
        '目标是信号收盘后下一交易日开盘至第五日收盘的对数收益，剔除下一开盘前无法成交的隔夜部分。每次训练最近252个已成熟样本，最后训练标签结束于当前收盘；特征标准化也只用训练样本。原始特征为各股截至当前收盘的5日涨跌。联合Ledoit-Wolf收缩协方差给出线性条件均值，没有调正则强度。', '',
        'mean只给历史均值；own_market只看自身与其余股票的等权市场；network使用全部股票（含自身）；shifted将网络训练特征循环错开126行，破坏特征标签关系。网络与自身/市场代表性嵌套，但收缩强度随维度不同，不能把差异全解释为网络因果信息。', '',
        '## 全部预测结果','',
        '|股票池|有效日期|股票数|模型|相对mean预测R²|方向正确率|日均截面Spearman|','|---|---:|---:|---|---:|---:|---:|']
    for r in output:
        for method,m in r['metrics'].items():lines.append(f"|{r['pool']}|{r['days']}|{r['stocks']}|{method}|{m['r2_vs_mean']:.5f}|{m['direction_accuracy']:.2%}|{m['mean_cross_section_spearman']:.4f}|")
    lines += ['', '预测R²是相对滚动历史均值的MSE改进，不是交易收益或价格解释率；原始MSE会受高波动股票影响。下面增量比较先除以各股训练目标方差，再按日期跨股平均。方向准确率可能来自普遍上涨偏置，不能单独证明有效。', '',
        '## 增量与不确定性','',
        '正值表示network的标准化MSE较小。21交易日循环区块、2000次、seed20260922；六池两比较共12个Bonferroni名义95%区间，不跨不同日历配对。尾部分位约由最外侧4个重采样决定，区间是近似且存在蒙特卡洛误差；不覆盖此前所有模型搜索，也不证明平稳性。', '',
        '|池|对照|平均标准化MSE改善|区间下界|区间上界|','|---|---|---:|---:|---:|']
    for r in output:
        for c,m in r['comparisons'].items():
            lo,hi=m['bonferroni_block_interval'];lines.append(f"|{r['pool']}|{c}|{m['normalized_mse_improvement']:+.5f}|{lo:+.5f}|{hi:+.5f}|")
    positive=json.loads((ROOT/'2026-09-22-lead-lag-positive-control.json').read_text())
    lines += ['', '## 决策','',f'固定门槛结果：{gate}。', '',
        '本次network在六池全部落后own_market，且六池相对mean预测R²均负；五池相对own_market的本轮校正区间上界小于零。方向正确率约48%—51%，没有进入交易回测的依据。更复杂的横截面条件均值在这些日线窗口主要增加估计误差，不能靠把网络加深来推断会改善。', '',
        f'正面对照：人工构造H收益精确滞后A五个交易日、其余股票为独立噪声，网络在走步预测中恢复领先关系，跟随股MSE为{positive["follower_mse"]}。这说明流水线可以识别被植入的强信号，但不证明真实股票存在这种关系。复现check_lead_lag.py。', '',
        '进入资金回测的门槛是六池至少四池相对own_market点估计改善，至少一个历史池改善，且本轮比较无显著负增量。这个筛查不证明可交易利润；通过也要扣成本并与市场风险基线比较。未通过则不进入账户回测、不按本轮赢家挑股票连接或改窗口。', '',
        '## 核查与限制','',
        '六池均检查真实数据前缀、输入行重排、价格单位变换和训练标签成熟日期；完整预测包含训练首尾信号日、成熟日、入场日、目标终点和训练方差。留出区间终点前无法完整成熟的最后五天不计预测指标。', '',
        '所有数据时期已经参与过多轮研究；当前股票名单存在选择偏差，原价格还有公司行动与股息口径限制。统计领先可以来自共同冲击、非同步定价或估计误差，不等于某公司引起另一公司涨跌。日线没有证据不意味着分钟级网络同样无效。', '',
        '复现：OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run --locked python scripts/study_lead_lag.py；uv run --locked python scripts/report_lead_lag.py。同名full.json.gz保存全部预测，sources.json记录SHA。生产策略和网页未修改。']
    P.with_suffix('.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(gate=gate,metrics=[dict(pool=r['pool'],network=r['metrics']['network'],comparisons={k:v['normalized_mse_improvement'] for k,v in r['comparisons'].items()}) for r in output]),indent=2))

if __name__=='__main__':main()

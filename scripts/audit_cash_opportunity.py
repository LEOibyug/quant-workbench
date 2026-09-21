"""Lagged SOFR scenarios; fixed-path interest is not a dynamic backtest."""
import gzip
import hashlib
import json
from bisect import bisect_left
from datetime import date
from pathlib import Path
from quant_workbench.market_data import schedule

ROOT=Path('docs/research-results')


def factor(rate,haircut,days):
    if days<0:raise ValueError('Negative interval')
    return 1+max(0,rate-haircut)/100*days/360


def main():
    assert abs(factor(5,1,3)-(1+.04*3/360))<1e-15
    source=Path('artifacts/research/cash-benchmark/sofr.json')
    data=json.loads(source.read_text())['refRates']
    assert all(r['type']=='SOFR' for r in data)
    rates={r['effectiveDate']:r['percentRate'] for r in data}
    assert len(rates)==len(data)
    effective=sorted(rates)
    calendar=schedule('2022-08-01','2025-09-02').index.strftime('%Y-%m-%d').tolist()
    fullpath=ROOT/'2026-09-22-liability-transfer-temporal.full.json.gz'
    book=json.loads(gzip.decompress(fullpath.read_bytes()))
    assert book['status']=='completed' and len(book['results'])==24
    rows=[];segments={}
    for account in book['results']:
        curve=account['curve'];end=account['end_exclusive'];start=curve[0]['date']
        assert curve[0]['equity']==100000
        days=[p['date'] for p in curve]
        assert days==sorted(set(days))
        intervals=[]
        for i,p in enumerate(curve):
            day=p['date'];nextday=days[i+1] if i+1<len(days) else end
            elapsed=(date.fromisoformat(nextday)-date.fromisoformat(day)).days
            assert elapsed>0 and p['cash']>=0
            prior=calendar[calendar.index(day)-1]
            j=bisect_left(effective,prior)-1
            assert j>=0
            rate_day=effective[j];assert rate_day<prior<day
            intervals.append(dict(day=day,next_day=nextday,calendar_days=elapsed,rate_effective_date=rate_day,rate_percent=rates[rate_day]))
        assert sum(d['calendar_days'] for d in intervals)==(date.fromisoformat(end)-date.fromisoformat(start)).days
        label=start+'/'+end
        if label in segments:assert segments[label]==intervals
        segments[label]=intervals
        for haircut in [0,1]:
            cash=100000.;interest=0.
            for p,d in zip(curve,intervals):
                f=factor(d['rate_percent'],haircut,d['calendar_days'])
                cash*=f
                interest+=p['cash']*(f-1)
            rows.append(dict(start=start,end=end,method=account['method'],cost_multiplier=account['cost_multiplier'],haircut_percentage_points=haircut,original_price_account_return_pct=account['metrics']['return_pct'],cash_scenario_return_pct=(cash/100000-1)*100,fixed_path_uncompounded_interest_usd=interest,average_gross_exposure_pct=account['metrics']['average_gross_exposure_pct'],not_dynamic_performance=True))
    assert len(rows)==48
    out=dict(status='completed',source_url='https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2022-08-01&endDate=2025-09-01',source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),account_sha256=hashlib.sha256(fullpath.read_bytes()).hexdigest(),rate_observations=len(data),rate_snapshot=data,segments=segments,results=rows,checks=dict(weekend_three_day_formula=True,source_lag=True,calendar_span=True,cash_nonnegative=True),limitations=['SOFR is not an offered retail deposit rate','Current historical snapshot is not vintage first publication data','Fixed-path interest cannot represent dynamic trading or risk feedback'])
    (ROOT/'2026-09-22-cash-opportunity.json').write_text(json.dumps(out,indent=2)+'\n')
    lines=['# 现金利息遗漏与机会成本','',
           '运行前协议e540324。现有日线账户不计现金利息；本轮从纽约联储取得770条历史SOFR，使用前一NYSE交易日之前的最近有效利率，按收盘间日历天数和360日分母计算。0或1个百分点折减为两种固定情景，不是券商实际收益或官方SOFR指数复现。','',
           '|区间终点不含|SOFR情景纯现金收益%|减1百分点现金收益%|原低负债账户收益%|原低组路径遗漏利息USD（SOFR情景）|','|---|---:|---:|---:|---:|']
    for label in segments:
        start,end=label.split('/')
        a=next(r for r in rows if (r['start'],r['end'],r['method'],r['cost_multiplier'],r['haircut_percentage_points'])==(start,end,'low_liability',1,0))
        b=next(r for r in rows if (r['start'],r['end'],r['method'],r['cost_multiplier'],r['haircut_percentage_points'])==(start,end,'low_liability',1,1))
        lines.append(f"|{label}|{a['cash_scenario_return_pct']:+.3f}|{b['cash_scenario_return_pct']:+.3f}|{a['original_price_account_return_pct']:+.3f}|{a['fixed_path_uncompounded_interest_usd']:.2f}|")
    lines+=['','## 如何解释','',
            '上表两边会计口径不同：股票账户未补现金收益，纯现金列则计息。不能据此直接宣布公平排名或收益差为股票alpha。固定路径遗漏利息只对旧收盘现金余额累加，不复投、不改变下一日买入股数、止损和永久停机；不可加到原收益后冒充完整回测，也不是上下界。','',
            '它说明下一步评估必须把现金收益接入账户账本并重跑同一资金/风控反馈，而不是继续用零现金收益或静态补值证明有效。纯现金情景收益也不能被当作已完成有效股票策略目标。','',
            '## 来源与限制','',
            '利率API来源及完整数据快照、每段所选有效日期、天数与源哈希保存于JSON。纽约联储说明页 https://www.newyorkfed.org/markets/reference-rates/sofr-averages-and-index 明确指数按营业日复利、约08:00发布；本轮360日和额外滞后为自定义约定，不伪称已核验官方完整指数算法。现行快照可能含修订，额外滞后不证明历史初版不变。SOFR为担保融资市场参考利率，普通账户未必获得。','',
            '24原账户×两利率情景完整，合成周末三日计算、时间滞后、区间日历总长度及非负现金检查通过。全部原账户起始权益100000，现金比较按实际第一条收盘至end对齐。股票分红/公司行动缺口仍在。','',
            '复现：`uv run --locked python scripts/audit_cash_opportunity.py`。未修改生产回测，总体目标未完成。']
    (ROOT/'2026-09-22-cash-opportunity.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:12]))

if __name__=='__main__':main()

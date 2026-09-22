# 固定缓冲能否继续提高：风险缩放与边缘交易

方案0a9687a在本轮运行前冻结。固定原三策略、股票池和所有比例阈值，共84账户：24旧对照精确复现、60新增执行变体。所有逐日现金/市值/盈亏和期末逐股贡献守恒通过。已观察开发数据，非独立确认，不按结果调阈值。

## 原理

固定2%权重缓冲对高低波动股票并不产生相同跟踪风险。risk以截至上一收盘63日简单收益波动率计算 b_i=b×median(sigma)/sigma_i，高波动股票缓冲较窄。缺失/零风险回退固定值。只对已有仓位生效，首次建仓门槛不变。它均衡的是独立风险近似，不是完整组合相关风险。

boundary在偏离越界后只交易到缓冲边缘，保留一部分目标偏离；risk_boundary联合两者。首次建仓、零目标退出、止损与熔断不被边缘缓冲拦截，仍受实际流动性限制。目的是减少交易，但会造成长期跟踪偏差，不能从理论动机直接推导回报改善。

pooled_only仅保留共享买单分配、日换手约束；fixed_entry再保留0.5%首次门槛，两者已有仓位门槛为0。这两个消融用于解释此前收益变化。

## 精确归因

与legacy曲线、全部指标、逐股贡献同时完全相同：{'pooled_only': {'exact_accounts': 12, 'total': 12}, 'fixed_entry': {'exact_accounts': 12, 'total': 12}}。这种相同只证明本组资金/订单条件下未产生变化，不等于共享分配在资金紧张时永远无效。

## 原20股

|执行|费用倍数|收益%|回撤%|交易数|费用与冲击美元|
|---|---:|---:|---:|---:|---:|
|legacy|1|22.147|4.708|593|1367.06|
|banded|1|22.532|4.374|410|1134.55|
|pooled_only|1|22.147|4.708|593|1367.06|
|fixed_entry|1|22.147|4.708|593|1367.06|
|risk|1|21.380|4.850|417|1129.21|
|boundary|1|20.603|5.134|432|978.87|
|risk_boundary|1|20.300|5.050|443|984.22|
|legacy|2|20.551|4.793|595|2734.14|
|banded|2|20.348|4.689|414|2272.89|
|pooled_only|2|20.551|4.793|595|2734.14|
|fixed_entry|2|20.551|4.793|595|2734.14|
|risk|2|20.329|4.874|416|2249.52|
|boundary|2|19.598|5.156|433|1954.40|
|risk_boundary|2|19.267|5.082|446|1968.39|

## 非原20股跨池门槛

其余5池至少4/5收益改善、中位差>0、回撤不能全部恶化；正常与双费都需通过，分别相对原legacy与上轮banded报告。

|候选|对照|费用倍数|改善池数|收益差中位数百分点|通过|
|---|---|---:|---:|---:|---|
|pooled_only|legacy|1|0/5|+0.000|False|
|pooled_only|legacy|2|0/5|+0.000|False|
|pooled_only|banded|1|2/5|-0.287|False|
|pooled_only|banded|2|1/5|-0.371|False|
|fixed_entry|legacy|1|0/5|+0.000|False|
|fixed_entry|legacy|2|0/5|+0.000|False|
|fixed_entry|banded|1|2/5|-0.287|False|
|fixed_entry|banded|2|1/5|-0.371|False|
|risk|legacy|1|3/5|+0.101|False|
|risk|legacy|2|4/5|+0.230|True|
|risk|banded|1|3/5|+0.005|False|
|risk|banded|2|3/5|+0.007|False|
|boundary|legacy|1|2/5|-0.202|False|
|boundary|legacy|2|2/5|-0.071|False|
|boundary|banded|1|2/5|-0.161|False|
|boundary|banded|2|2/5|-0.225|False|
|risk_boundary|legacy|1|1/5|-0.479|False|
|risk_boundary|legacy|2|1/5|-0.401|False|
|risk_boundary|banded|1|2/5|-0.246|False|
|risk_boundary|banded|2|1/5|-0.513|False|

同时通过两费用、两对照的新增缓冲候选：无。

## 全部84账户

|池|执行|费用|收益%|回撤%|平均仓位%|交易数|费用与冲击美元|停机|
|---|---|---:|---:|---:|---:|---:|---:|---|
|original20|legacy|1|22.147|4.708|62.34|593|1367.06|False|
|original20|banded|1|22.532|4.374|62.61|410|1134.55|False|
|original20|pooled_only|1|22.147|4.708|62.34|593|1367.06|False|
|original20|fixed_entry|1|22.147|4.708|62.34|593|1367.06|False|
|original20|risk|1|21.380|4.850|62.49|417|1129.21|False|
|original20|boundary|1|20.603|5.134|62.67|432|978.87|False|
|original20|risk_boundary|1|20.300|5.050|61.79|443|984.22|False|
|original20|legacy|2|20.551|4.793|62.26|595|2734.14|False|
|original20|banded|2|20.348|4.689|62.60|414|2272.89|False|
|original20|pooled_only|2|20.551|4.793|62.26|595|2734.14|False|
|original20|fixed_entry|2|20.551|4.793|62.26|595|2734.14|False|
|original20|risk|2|20.329|4.874|62.32|416|2249.52|False|
|original20|boundary|2|19.598|5.156|62.74|433|1954.40|False|
|original20|risk_boundary|2|19.267|5.082|61.82|446|1968.39|False|
|alternate20|legacy|1|19.100|6.496|63.40|630|1363.00|False|
|alternate20|banded|1|19.749|6.426|64.08|417|1091.98|False|
|alternate20|pooled_only|1|19.100|6.496|63.40|630|1363.00|False|
|alternate20|fixed_entry|1|19.100|6.496|63.40|630|1363.00|False|
|alternate20|risk|1|18.465|6.358|63.73|433|1112.10|False|
|alternate20|boundary|1|19.588|6.163|63.93|454|968.53|False|
|alternate20|risk_boundary|1|18.259|6.010|63.43|484|1001.52|False|
|alternate20|legacy|2|17.530|6.694|63.36|627|2706.62|False|
|alternate20|banded|2|18.135|6.549|64.03|417|2172.93|False|
|alternate20|pooled_only|2|17.530|6.694|63.36|627|2706.62|False|
|alternate20|fixed_entry|2|17.530|6.694|63.36|627|2706.62|False|
|alternate20|risk|2|16.936|6.541|63.68|435|2224.11|False|
|alternate20|boundary|2|18.251|6.197|63.99|450|1926.39|False|
|alternate20|risk_boundary|2|17.129|6.058|63.42|489|2012.72|False|
|random10|legacy|1|-7.320|9.300|43.36|278|678.83|False|
|random10|banded|1|-7.552|9.474|43.74|195|584.08|False|
|random10|pooled_only|1|-7.320|9.300|43.36|278|678.83|False|
|random10|fixed_entry|1|-7.320|9.300|43.36|278|678.83|False|
|random10|risk|1|-7.215|9.224|43.55|197|586.31|False|
|random10|boundary|1|-8.130|9.652|41.97|222|553.65|False|
|random10|risk_boundary|1|-7.799|9.372|42.00|221|550.12|False|
|random10|legacy|2|-7.982|9.640|43.38|274|1346.32|False|
|random10|banded|2|-9.079|10.097|43.03|203|1211.42|True|
|random10|pooled_only|2|-7.982|9.640|43.38|274|1346.32|False|
|random10|fixed_entry|2|-7.982|9.640|43.38|274|1346.32|False|
|random10|risk|2|-7.855|9.432|43.57|199|1176.67|False|
|random10|boundary|2|-9.303|10.173|39.11|208|1054.33|True|
|random10|risk_boundary|2|-9.275|10.151|41.32|224|1130.87|True|
|random10_temporal|legacy|1|-4.077|9.318|43.49|886|2126.14|False|
|random10_temporal|banded|1|-3.790|9.294|43.54|625|1814.04|False|
|random10_temporal|pooled_only|1|-4.077|9.318|43.49|886|2126.14|False|
|random10_temporal|fixed_entry|1|-4.077|9.318|43.49|886|2126.14|False|
|random10_temporal|risk|1|-3.976|9.170|43.50|629|1814.47|False|
|random10_temporal|boundary|1|-3.228|8.197|43.34|691|1673.48|False|
|random10_temporal|risk_boundary|1|-2.793|7.886|43.33|713|1687.35|False|
|random10_temporal|legacy|2|-7.092|10.247|25.46|542|2577.24|True|
|random10_temporal|banded|2|-6.966|10.208|25.46|390|2216.51|True|
|random10_temporal|pooled_only|2|-7.092|10.247|25.46|542|2577.24|True|
|random10_temporal|fixed_entry|2|-7.092|10.247|25.46|542|2577.24|True|
|random10_temporal|risk|2|-6.862|10.099|25.47|393|2224.24|True|
|random10_temporal|boundary|2|-4.809|9.108|43.28|682|3311.84|False|
|random10_temporal|risk_boundary|2|-4.389|8.676|43.32|714|3357.71|False|
|transfer12_temporal|legacy|1|-8.831|10.103|6.35|173|410.78|True|
|transfer12_temporal|banded|1|-10.005|10.669|8.93|170|470.65|True|
|transfer12_temporal|pooled_only|1|-8.831|10.103|6.35|173|410.78|True|
|transfer12_temporal|fixed_entry|1|-8.831|10.103|6.35|173|410.78|True|
|transfer12_temporal|risk|1|-10.000|10.664|8.94|173|474.66|True|
|transfer12_temporal|boundary|1|-9.033|10.007|6.23|142|338.75|True|
|transfer12_temporal|risk_boundary|1|-9.146|10.149|6.18|155|352.58|True|
|transfer12_temporal|legacy|2|-9.201|10.435|6.35|174|822.83|True|
|transfer12_temporal|banded|2|-8.822|10.062|6.35|130|716.12|True|
|transfer12_temporal|pooled_only|2|-9.201|10.435|6.35|174|822.83|True|
|transfer12_temporal|fixed_entry|2|-9.201|10.435|6.35|174|822.83|True|
|transfer12_temporal|risk|2|-8.823|10.063|6.36|133|724.03|True|
|transfer12_temporal|boundary|2|-9.621|10.073|6.09|139|666.84|True|
|transfer12_temporal|risk_boundary|2|-9.738|10.195|6.05|151|692.41|True|
|new12_temporal|legacy|1|-4.060|10.211|41.79|909|2167.31|True|
|new12_temporal|banded|1|-3.722|10.183|41.91|616|1818.13|True|
|new12_temporal|pooled_only|1|-4.060|10.211|41.79|909|2167.31|True|
|new12_temporal|fixed_entry|1|-4.060|10.211|41.79|909|2167.31|True|
|new12_temporal|risk|1|-3.473|10.124|41.96|618|1819.59|True|
|new12_temporal|boundary|1|-4.996|10.801|42.04|721|1737.04|True|
|new12_temporal|risk_boundary|1|-4.808|10.586|42.04|763|1772.25|True|
|new12_temporal|legacy|2|-5.168|10.008|40.39|878|4172.57|True|
|new12_temporal|banded|2|-4.797|10.249|41.75|617|3618.30|True|
|new12_temporal|pooled_only|2|-5.168|10.008|40.39|878|4172.57|True|
|new12_temporal|fixed_entry|2|-5.168|10.008|40.39|878|4172.57|True|
|new12_temporal|risk|2|-4.789|10.286|41.82|614|3599.30|True|
|new12_temporal|boundary|2|-5.239|10.087|41.18|717|3411.31|True|
|new12_temporal|risk_boundary|2|-5.309|10.110|41.25|752|3467.75|True|

## 结论

本轮没有得到比上轮固定缓冲更可靠的升级。原20股正常费用：banded 22.5318%、risk 21.3802%、boundary 20.6031%、risk_boundary 20.3000%。风险缩放在其他五池两费用均仅3/5改善；边缘交易多数退步。原20股正常费用交易次数也由固定缓冲410升至417/432/443，较小单笔调整并未减少总交易次数。

pooled_only与fixed_entry各12账户都精确等同legacy：在这些数据、现金和配置下，上轮利润变化来自已有持仓的调仓缓冲，而非按比例资金分配或首次门槛。不能推广为资金分配在更紧张预算下无作用。

固定缓冲原20股费用与冲击1134.55美元，相当于初始资本1.13个百分点；在完全固定成交股数与时间的记账诊断中，抹掉这些成本也只直接增加这部分利润。这不是重新模拟零费用账户的收益上界，因为资金反馈会改变后续成交。要取得更大且可推广的提升，需要新的可验证信号优势，不能只期待进一步微调成交门槛。

不推出新默认、不自动改已发布策略；上轮固定缓冲仍是可试用版本，且原有跨池失败与双费局限继续保留。

## 使用与限制

本轮不改变默认或已发布参数。后台execution_buffer字段支持fixed/risk/boundary/risk_boundary，只在portfolio_policy=banded时生效；fixed默认保持上轮版本完全一致。未通过的变体不增设网页推荐入口。风险参数是截至前一收盘的滚动估计，不使用当前日收盘/成交量。

仍用原价格、无股息无现金利息，不能叫完整总回报。三个年度池是2025-09至2026-09，三个temporal池是2022-09至2025-09。终值含未实现盈亏，停机后现金不计息；双费下收益偶尔更好可能来自风控路径变化，不代表费用有益。

复现：uv run --locked python scripts/study_buffer_geometry.py；uv run --locked python scripts/report_buffer_geometry.py。同名full.json.gz保存全部资产路径，sources.json保存源SHA。所有候选与亏损结果保留。

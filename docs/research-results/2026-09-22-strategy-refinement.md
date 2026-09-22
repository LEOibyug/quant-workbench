# 盈利机制驱动的模型改进：完整对照结果

原20股分析提出三种不同机制候选，先冻结方案再运行各自实验，没有按结果调窗口或选股票。已有历史都属于开发数据。本报告包含六池、两费用、共72账户，不能称为新样本外确认。

## 变更

- trend_reversal：动量/反转目标各半，反转要求当前价不低于63日前；通道不再单独占资金。假设是减少持续下跌中的逆势交易。
- smoothed_ensemble：保留原三分支，以调仓间隔为半衰期指数平滑目标，之后按当前协方差限风险。假设是减少快于执行周期的目标跳动；会造成入退出滞后。止损和熔断仍由引擎执行。
- banded：保留原三策略，在实际执行中复用调仓缓冲与按比例共享买单资金，不调用成本优化器。用原配置2%调仓门槛、0.5%首次建仓门槛、100%日换手上限。
- cost_aware：复用现有共享资金、相关风险和换手成本优化器，独立于信号变化测试。优化的是目标跟踪与费用折衷，不是准确预测收益。

第二方案在看到第一方案原20股和另一20股初步结果后提出，顺序已在独立协议记录。第三方案在发现平滑增加成交后，依据基础执行缺少缓冲的代码检查提出。三个方案按顺序记录，没有回写先前假设或隐藏失败。

## 预先规定的跨池推荐门槛

排除original20后五个池，至少4/5收益改善、收益差中位数为正、回撤不能全部变差，正常和双倍费用均需通过。门槛仅为开发期筛查，不是统计显著性或未来盈利保证。不同区间累计收益不直接合并成年化收益。

|模型|执行|费用倍数|改善池数|收益差中位数百分点|通过|
|---|---|---:|---:|---:|---|
|fixed_ensemble|cost_aware|1|1/5|-1.406|False|
|fixed_ensemble|cost_aware|2|2/5|-0.354|False|
|trend_reversal|legacy|1|2/5|-0.155|False|
|trend_reversal|legacy|2|3/5|+0.498|False|
|trend_reversal|cost_aware|1|2/5|-0.238|False|
|trend_reversal|cost_aware|2|2/5|-0.199|False|
|smoothed_ensemble|legacy|1|1/5|-1.832|False|
|smoothed_ensemble|legacy|2|1/5|-0.329|False|
|fixed_ensemble|banded|1|3/5|+0.287|False|
|fixed_ensemble|banded|2|4/5|+0.371|True|

同时通过两费用门槛的候选：无。默认及已发布版本不自动替换；两个新模型及缓冲执行在开发页可选择、运行并发布冻结版本。

## 全部账户

|股票池|模型|执行|费用|收益%|回撤%|均仓位%|交易数|费用+冲击美元|停机|
|---|---|---|---:|---:|---:|---:|---:|---:|---|
|alternate20|fixed_ensemble|banded|1|19.749|6.426|64.08|417|1091.98|False|
|alternate20|fixed_ensemble|cost_aware|1|16.298|6.131|58.66|352|842.28|False|
|alternate20|fixed_ensemble|legacy|1|19.100|6.496|63.40|630|1363.00|False|
|alternate20|smoothed_ensemble|legacy|1|18.735|6.645|65.01|912|1286.57|False|
|alternate20|trend_reversal|cost_aware|1|11.472|6.315|48.33|253|795.37|False|
|alternate20|trend_reversal|legacy|1|13.037|7.329|50.68|390|1068.56|False|
|alternate20|fixed_ensemble|banded|2|18.135|6.549|64.03|417|2172.93|False|
|alternate20|fixed_ensemble|cost_aware|2|15.523|5.805|55.12|292|1344.23|False|
|alternate20|fixed_ensemble|legacy|2|17.530|6.694|63.36|627|2706.62|False|
|alternate20|smoothed_ensemble|legacy|2|17.207|6.918|64.87|910|2563.00|False|
|alternate20|trend_reversal|cost_aware|2|10.008|6.023|45.76|242|1395.85|False|
|alternate20|trend_reversal|legacy|2|11.917|7.707|50.67|389|2127.22|False|
|new12_temporal|fixed_ensemble|banded|1|-3.722|10.183|41.91|616|1818.13|True|
|new12_temporal|fixed_ensemble|cost_aware|1|-5.719|10.923|40.90|557|1513.19|True|
|new12_temporal|fixed_ensemble|legacy|1|-4.060|10.211|41.79|909|2167.31|True|
|new12_temporal|smoothed_ensemble|legacy|1|-8.999|12.112|42.49|1426|2061.63|True|
|new12_temporal|trend_reversal|cost_aware|1|-3.964|11.539|29.49|384|1373.86|True|
|new12_temporal|trend_reversal|legacy|1|-2.690|10.730|31.46|641|1786.45|True|
|new12_temporal|fixed_ensemble|banded|2|-4.797|10.249|41.75|617|3618.30|True|
|new12_temporal|fixed_ensemble|cost_aware|2|-6.074|11.232|38.92|496|2530.36|True|
|new12_temporal|fixed_ensemble|legacy|2|-5.168|10.008|40.39|878|4172.57|True|
|new12_temporal|smoothed_ensemble|legacy|2|-7.228|10.201|42.24|1415|4091.70|True|
|new12_temporal|trend_reversal|cost_aware|2|-4.522|11.329|27.26|377|2505.81|True|
|new12_temporal|trend_reversal|legacy|2|-2.743|10.146|29.83|614|3402.21|True|
|original20|fixed_ensemble|banded|1|22.532|4.374|62.61|410|1134.55|False|
|original20|fixed_ensemble|cost_aware|1|20.168|4.504|56.74|339|853.57|False|
|original20|fixed_ensemble|legacy|1|22.147|4.708|62.34|593|1367.06|False|
|original20|smoothed_ensemble|legacy|1|15.969|5.780|63.37|852|1226.78|False|
|original20|trend_reversal|cost_aware|1|16.301|5.223|44.23|244|784.41|False|
|original20|trend_reversal|legacy|1|20.203|4.739|48.14|379|1086.82|False|
|original20|fixed_ensemble|banded|2|20.348|4.689|62.60|414|2272.89|False|
|original20|fixed_ensemble|cost_aware|2|18.301|5.031|50.49|295|1419.07|False|
|original20|fixed_ensemble|legacy|2|20.551|4.793|62.26|595|2734.14|False|
|original20|smoothed_ensemble|legacy|2|14.323|5.983|63.40|857|2461.53|False|
|original20|trend_reversal|cost_aware|2|14.017|5.526|39.99|236|1364.82|False|
|original20|trend_reversal|legacy|2|18.683|4.830|48.06|377|2157.04|False|
|random10|fixed_ensemble|banded|1|-7.552|9.474|43.74|195|584.08|False|
|random10|fixed_ensemble|cost_aware|1|-7.320|8.925|39.58|183|498.33|False|
|random10|fixed_ensemble|legacy|1|-7.320|9.300|43.36|278|678.83|False|
|random10|smoothed_ensemble|legacy|1|-9.152|10.079|37.36|372|592.44|True|
|random10|trend_reversal|cost_aware|1|-6.909|7.484|30.25|116|407.19|False|
|random10|trend_reversal|legacy|1|-6.180|7.233|32.57|214|555.47|False|
|random10|fixed_ensemble|banded|2|-9.079|10.097|43.03|203|1211.42|True|
|random10|fixed_ensemble|cost_aware|2|-7.747|9.281|36.05|167|853.47|False|
|random10|fixed_ensemble|legacy|2|-7.982|9.640|43.38|274|1346.32|False|
|random10|smoothed_ensemble|legacy|2|-9.619|10.504|37.38|370|1179.93|True|
|random10|trend_reversal|cost_aware|2|-8.314|8.545|27.33|112|729.23|False|
|random10|trend_reversal|legacy|2|-6.747|7.481|32.59|215|1110.85|False|
|random10_temporal|fixed_ensemble|banded|1|-3.790|9.294|43.54|625|1814.04|False|
|random10_temporal|fixed_ensemble|cost_aware|1|-4.061|8.906|41.35|570|1507.86|False|
|random10_temporal|fixed_ensemble|legacy|1|-4.077|9.318|43.49|886|2126.14|False|
|random10_temporal|smoothed_ensemble|legacy|1|-1.332|9.000|43.51|1364|2013.71|False|
|random10_temporal|trend_reversal|cost_aware|1|-4.616|7.864|32.68|379|1304.00|False|
|random10_temporal|trend_reversal|legacy|1|-5.742|9.385|34.26|634|1715.86|False|
|random10_temporal|fixed_ensemble|banded|2|-6.966|10.208|25.46|390|2216.51|True|
|random10_temporal|fixed_ensemble|cost_aware|2|-4.076|8.225|38.87|502|2530.03|False|
|random10_temporal|fixed_ensemble|legacy|2|-7.092|10.247|25.46|542|2577.24|True|
|random10_temporal|smoothed_ensemble|legacy|2|-3.742|9.252|43.50|1358|4002.18|False|
|random10_temporal|trend_reversal|cost_aware|2|-5.630|8.629|30.61|371|2354.33|False|
|random10_temporal|trend_reversal|legacy|2|-6.594|10.038|34.11|637|3443.17|True|
|transfer12_temporal|fixed_ensemble|banded|1|-10.005|10.669|8.93|170|470.65|True|
|transfer12_temporal|fixed_ensemble|cost_aware|1|-10.237|10.853|8.46|154|388.53|True|
|transfer12_temporal|fixed_ensemble|legacy|1|-8.831|10.103|6.35|173|410.78|True|
|transfer12_temporal|smoothed_ensemble|legacy|1|-10.858|11.502|6.16|295|445.07|True|
|transfer12_temporal|trend_reversal|cost_aware|1|-9.069|10.316|4.64|84|255.32|True|
|transfer12_temporal|trend_reversal|legacy|1|-8.986|10.264|4.93|122|329.10|True|
|transfer12_temporal|fixed_ensemble|banded|2|-8.822|10.062|6.35|130|716.12|True|
|transfer12_temporal|fixed_ensemble|cost_aware|2|-9.555|10.077|6.86|125|600.76|True|
|transfer12_temporal|fixed_ensemble|legacy|2|-9.201|10.435|6.35|174|822.83|True|
|transfer12_temporal|smoothed_ensemble|legacy|2|-9.530|10.152|6.02|297|894.98|True|
|transfer12_temporal|trend_reversal|cost_aware|2|-9.400|10.179|5.15|93|531.66|True|
|transfer12_temporal|trend_reversal|legacy|2|-9.393|10.200|4.85|122|658.14|True|

## 本轮结论与使用建议

优先试用的是原fixed_ensemble + banded缓冲执行，不是更换信号。原20股正常费用收益22.147→22.532%，回撤4.708→4.374%，交易593→410，费用+冲击1367.06→1134.55美元。12账户交易数全部减少，11/12费用降低，但正常费用非原池仅3/5收益改善、双费4/5，未满足两费用均4/5的完整门槛。原20股双费收益20.551→20.348%，也需明确保留。

趋势过滤与目标平滑均不推荐替代原组合。尤其平滑将原20股交易数增加到852，说明平滑目标并不等于减少实际成交。两者作为研究候选保留，不能以“已优化”包装为收益提升。

网页：长期策略选择“固定三策略组合”，共享资金执行政策选择“共享资金 · 调仓缓冲执行”。复现实验时调仓5日、每日单股最大调整10%、首次建仓门槛0.5%、调仓缓冲2%、日换手上限100%，关闭额外轮换优化，其他使用冻结原配置。模型改为新候选时请单独比较，不混同已发布旧版本。当前未更改默认策略或已发布配置。

缓冲带跳过小额非零目标调整；零目标退出、止损与组合熔断继续执行，并受成交量限制。该政策也按可用资金比例满足买单，故改善不能全部归因于缓冲带本身。

## 可复核范围

同年度original20/alternate20/random10为2025-09至2026-09，三个temporal池为2022-09至2025-09连续区间。无股息和现金利息，长时间停机后的持币不计息；不是完整总回报。原20股两费用旧组合精确复现，全部72账户核对现金+市值=权益及逐股盈亏=权益变化。新模型复用前缀因果性、输入排序不变、仓位约束、真实引擎账本测试。

收益提升不能仅凭更低费用解释：更少或更晚交易会改变整个资金路径。反之，减少亏损但仍为负也不构成可部署盈利策略。股票池内的单股利润不能被当作独立投资机会分数。

复现：study_trend_pullback.py、study_smoothed_ensemble.py（另加--banded运行缓冲实验）、report_strategy_refinement.py（均用uv run --locked python scripts/前缀运行）。三实验同名full.json.gz保存完整逐日持仓、贡献及配置，sources.json保存数据与代码哈希。

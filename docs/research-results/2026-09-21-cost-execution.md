# 成本约束共享资金：36组开发比较与16组跨期确认

## 结论

成本控制降低了佣金、成交次数和换手，但没有建立跨股票池和时期的稳健收益改善。固定三策略随机池仍亏损；一年高点信号的两个执行变体当年三池均正，随后冻结跨期确认失败。未因成本优化名称或求解器成功就认定经济有效。

## 文献与模型对应

读取Gârleanu–Pedersen《Dynamic Trading with Predictable Returns and Transaction Costs》NBER WP15205原摘要：https://www.nber.org/papers/w15205 。其动态解考虑不同速度的信号衰减，提出向未来目标瞄准、部分调整的原则，实证采用商品期货。没有读取或声称复现全文闭式解。

本项目现有成本优化是协方差标准化目标跟踪误差，加“估计成本/波动尺度”乘L1换手惩罚；它不估计信号衰减或真实收益效用。约束包括只买原信号允许股、总目标仓位和估计风险均不超过原目标。最优数学目标不等于最优未来利润。

## 三种固定执行方式

- legacy：原执行方式，忽略额外进场/调仓门槛。
- pooled_only：仅使用按比例分配可用资金、5%现金缓冲、0.5%新开仓门槛、2%调仓门槛和100%日换手预算；目标优化器用恒等映射替代。
- cost_aware：在上述执行方式上加入现有目标跟踪/成本优化。

所有组allocation.enabled=false，单股止损与组合永久熔断保持修复后的语义。固定组合每5日、高点每20日调仓；两信号均在相同预热历史上生成。双倍成本同时影响成交与优化器的估计成本，不是单纯事后减费用。

## 开发比较全部结果

|池|信号|执行|费用倍数|收益%|最大回撤%|成交数|
|---|---|---|---:|---:|---:|---:|
|original20|fixed_ensemble|legacy|1|+22.147|4.708|593|
|original20|fixed_ensemble|legacy|2|+20.551|4.793|595|
|original20|fixed_ensemble|pooled_only|1|+22.532|4.374|410|
|original20|fixed_ensemble|pooled_only|2|+20.348|4.689|414|
|original20|fixed_ensemble|cost_aware|1|+20.168|4.504|339|
|original20|fixed_ensemble|cost_aware|2|+18.258|5.068|294|
|original20|high52|legacy|1|+6.420|7.712|151|
|original20|high52|legacy|2|+5.940|7.809|152|
|original20|high52|pooled_only|1|+6.258|7.637|133|
|original20|high52|pooled_only|2|+5.783|7.789|134|
|original20|high52|cost_aware|1|+5.495|7.642|129|
|original20|high52|cost_aware|2|+5.049|7.722|122|
|alternate20|fixed_ensemble|legacy|1|+19.100|6.496|630|
|alternate20|fixed_ensemble|legacy|2|+17.530|6.694|627|
|alternate20|fixed_ensemble|pooled_only|1|+19.749|6.426|417|
|alternate20|fixed_ensemble|pooled_only|2|+18.135|6.549|417|
|alternate20|fixed_ensemble|cost_aware|1|+16.298|6.131|352|
|alternate20|fixed_ensemble|cost_aware|2|+15.523|5.805|292|
|alternate20|high52|legacy|1|+26.069|4.247|145|
|alternate20|high52|legacy|2|+25.515|4.280|145|
|alternate20|high52|pooled_only|1|+26.128|4.099|130|
|alternate20|high52|pooled_only|2|+25.656|4.129|129|
|alternate20|high52|cost_aware|1|+24.777|3.974|116|
|alternate20|high52|cost_aware|2|+23.441|3.806|108|
|random10|fixed_ensemble|legacy|1|-7.320|9.300|278|
|random10|fixed_ensemble|legacy|2|-7.982|9.640|274|
|random10|fixed_ensemble|pooled_only|1|-7.552|9.474|195|
|random10|fixed_ensemble|pooled_only|2|-9.079|10.097|203|
|random10|fixed_ensemble|cost_aware|1|-7.320|8.925|183|
|random10|fixed_ensemble|cost_aware|2|-7.747|9.281|167|
|random10|high52|legacy|1|+1.528|7.220|84|
|random10|high52|legacy|2|+1.291|7.295|84|
|random10|high52|pooled_only|1|+1.525|7.387|59|
|random10|high52|pooled_only|2|+1.309|7.456|59|
|random10|high52|cost_aware|1|+1.501|7.076|56|
|random10|high52|cost_aware|2|+1.295|6.900|54|

固定组合正常费用：原池佣金约634→366美元、换手21.71→14.57倍，但收益22.15%→20.17%；第二池佣金664→374美元而收益19.10%→16.30%；随机池收益约-7.32%未解决。成本优化平均股票仓位也下降，所以不能把费用差或少亏全归因于更聪明的成交。

## 高点信号冻结跨期确认

|起始|结束（不含）|执行|费用倍数|收益%|最大回撤%|
|---|---|---|---:|---:|---:|
|2022-09-01|2023-09-01|pooled_only|1|+1.192|7.078|
|2022-09-01|2023-09-01|pooled_only|2|+1.033|7.087|
|2022-09-01|2023-09-01|cost_aware|1|-8.978|10.262|
|2022-09-01|2023-09-01|cost_aware|2|-8.980|10.203|
|2023-09-01|2024-09-01|pooled_only|1|+0.619|9.937|
|2023-09-01|2024-09-01|pooled_only|2|-8.388|9.981|
|2023-09-01|2024-09-01|cost_aware|1|+0.671|9.719|
|2023-09-01|2024-09-01|cost_aware|2|-0.229|9.942|
|2024-09-01|2025-09-01|pooled_only|1|-3.538|9.317|
|2024-09-01|2025-09-01|pooled_only|2|-3.967|9.589|
|2024-09-01|2025-09-01|cost_aware|1|-3.259|9.091|
|2024-09-01|2025-09-01|cost_aware|2|-3.791|9.083|
|2022-09-01|2025-09-01|pooled_only|1|-1.359|10.439|
|2022-09-01|2025-09-01|pooled_only|2|-1.836|10.513|
|2022-09-01|2025-09-01|cost_aware|1|-8.978|10.262|
|2022-09-01|2025-09-01|cost_aware|2|-8.980|10.203|

连续三年pooled_only正常-1.359%、双倍-1.836%；cost_aware正常-8.978%、双倍-8.980%，第一年已触发永久熔断。原legacy高点连续正常-1.664%、双倍-2.258%，直接引用已有high52-temporal结果，已核对行情SHA256一致，未把引用8条基线计为8次新试验。

2023—2024 pooled_only正常略盈利而双倍显著亏损，体现止损/熔断路径非线性；引擎在开盘和收盘检查风险，报告最大回撤为日终值，开盘触发熔断不一定对应日终回撤超过10%。所有优化调用都报告optimized，没有求解失败回退；失败是本次经济结果，不是以求解失败解释。

历史时期与年度连续窗口有重叠，且已经用于其他候选；不能作全新独立确认。尽管简单执行方式在个别对照减少亏损，仍没有足够证据完成原目标。不根据这些结果放松熔断、调整门槛或选择某个年份的执行方式。

## 复现与验证

运行study_cost_execution.py及study_cost_execution_temporal.py。两个同名JSON保存52次完整配置、指标、净值、逐股贡献和求解状态，full.json.gz无损保留逐日资产明细，摘要/归档逐项核验一致。2项已有相关测试通过：成本配置风险/换手约束及共享执行的股票顺序不变/资金预算约束。没有为研究脚本重复堆叠镜像测试。

本轮复用了现有执行实现，未按收益修改产品策略。研究目标仍未完成。

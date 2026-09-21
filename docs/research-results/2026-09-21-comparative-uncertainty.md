# 近期9个候选：成对收益不确定性审计

结论：54个候选—基线比较，在本次固定区块bootstrap最大统计量校正下，没有单侧p<0.05的改善。最小校正p约0.5105。不能把这解释成证明全部策略永远无效，但当前证据不足以支持成功声明。

## 跨池最弱改善

以下是每日成对收益差均值×25200，单位年化算术百分点，不是复合终值差。区间为三池最小均值的未校正bootstrap百分位区间，不是同时置信区间。

|研究|候选|费用倍数|三池最小改善|未校正95%区间|
|---|---|---:|---:|---|
|tsmom|inverse_vol|1|-1.913|-7.223, 1.999|
|tsmom|inverse_vol|2|-1.656|-6.524, 2.169|
|tsmom|tsmom|1|-5.938|-15.149, 1.317|
|tsmom|tsmom|2|-6.052|-15.024, 1.295|
|low-beta|low_beta|1|-1.975|-21.989, 11.141|
|low-beta|low_beta|2|-1.729|-21.606, 11.248|
|low-beta|high_beta|1|-12.830|-34.283, -5.648|
|low-beta|high_beta|2|-12.721|-34.061, -5.659|
|event-reaction|positive|1|-7.079|-18.775, -1.343|
|event-reaction|positive|2|-5.310|-16.367, 0.243|
|event-reaction|negative|1|1.729|-7.582, 6.000|
|event-reaction|negative|2|4.547|-6.537, 8.304|
|volume-event|high|1|-7.246|-17.064, -1.700|
|volume-event|high|2|-8.555|-18.553, -2.340|
|volume-event|low|1|-15.567|-30.654, -1.764|
|volume-event|low|2|-15.128|-30.179, -0.952|
|online-mixture|wealth_mix|1|-0.093|-0.605, 0.025|
|online-mixture|wealth_mix|2|-0.121|-0.522, 0.009|

只有event-reaction/negative在本年三池均优于all事件账户，但最弱改善区间正常费用约[-7.58,+6.00]，双倍约[-6.54,+8.30]，均跨零；其原池账户绝对收益也为负。不能仅凭较差基线将它标成跨池有效策略。

## 全部成对结果

|研究|候选|基线|池|费用|实际终值收益差pp|年化每日均差pp|校正单侧p|
|---|---|---|---|---:|---:|---:|---:|
|tsmom|inverse_vol|equal|original20|1|1.349|1.109|1.0000|
|tsmom|inverse_vol|equal|alternate20|1|-2.346|-1.913|1.0000|
|tsmom|inverse_vol|equal|random10|1|0.275|0.274|1.0000|
|tsmom|inverse_vol|equal|original20|2|1.151|0.944|1.0000|
|tsmom|inverse_vol|equal|alternate20|2|-2.023|-1.656|1.0000|
|tsmom|inverse_vol|equal|random10|2|0.250|0.249|1.0000|
|tsmom|tsmom|equal|original20|1|-6.449|-5.938|1.0000|
|tsmom|tsmom|equal|alternate20|1|-5.532|-4.662|1.0000|
|tsmom|tsmom|equal|random10|1|0.034|-0.015|1.0000|
|tsmom|tsmom|equal|original20|2|-6.557|-6.052|1.0000|
|tsmom|tsmom|equal|alternate20|2|-5.053|-4.289|1.0000|
|tsmom|tsmom|equal|random10|2|0.053|0.004|1.0000|
|low-beta|low_beta|equal|original20|1|-0.764|-0.752|1.0000|
|low-beta|low_beta|equal|alternate20|1|-2.501|-1.975|1.0000|
|low-beta|low_beta|equal|random10|1|9.250|9.022|0.9780|
|low-beta|low_beta|equal|original20|2|-0.666|-0.668|1.0000|
|low-beta|low_beta|equal|alternate20|2|-2.184|-1.729|1.0000|
|low-beta|low_beta|equal|random10|2|9.274|9.060|0.9780|
|low-beta|high_beta|equal|original20|1|-13.856|-12.830|1.0000|
|low-beta|high_beta|equal|alternate20|1|-7.268|-5.756|1.0000|
|low-beta|high_beta|equal|random10|1|-8.704|-9.167|1.0000|
|low-beta|high_beta|equal|original20|2|-13.710|-12.721|1.0000|
|low-beta|high_beta|equal|alternate20|2|-6.926|-5.500|1.0000|
|low-beta|high_beta|equal|random10|2|-8.728|-9.211|1.0000|
|event-reaction|positive|all|original20|1|3.038|2.981|1.0000|
|event-reaction|positive|all|alternate20|1|-6.393|-7.079|1.0000|
|event-reaction|positive|all|random10|1|-5.950|-6.280|1.0000|
|event-reaction|positive|all|original20|2|5.406|5.643|0.9770|
|event-reaction|positive|all|alternate20|2|-4.128|-4.704|1.0000|
|event-reaction|positive|all|random10|2|-4.961|-5.310|1.0000|
|event-reaction|negative|all|original20|1|1.730|1.729|1.0000|
|event-reaction|negative|all|alternate20|1|7.434|7.332|0.7183|
|event-reaction|negative|all|random10|1|4.671|4.374|0.9980|
|event-reaction|negative|all|original20|2|4.259|4.547|0.9421|
|event-reaction|negative|all|alternate20|2|8.436|8.453|0.5105|
|event-reaction|negative|all|random10|2|5.498|5.233|0.9900|
|volume-event|high|inverse_vol|original20|1|-7.283|-6.460|1.0000|
|volume-event|high|inverse_vol|alternate20|1|-8.461|-7.246|1.0000|
|volume-event|high|inverse_vol|random10|1|1.502|1.703|1.0000|
|volume-event|high|inverse_vol|original20|2|-7.933|-7.200|1.0000|
|volume-event|high|inverse_vol|alternate20|2|-9.727|-8.555|1.0000|
|volume-event|high|inverse_vol|random10|2|2.548|2.674|1.0000|
|volume-event|low|inverse_vol|original20|1|-8.362|-7.565|1.0000|
|volume-event|low|inverse_vol|alternate20|1|-17.294|-15.567|1.0000|
|volume-event|low|inverse_vol|random10|1|0.074|0.011|1.0000|
|volume-event|low|inverse_vol|original20|2|-7.806|-7.198|1.0000|
|volume-event|low|inverse_vol|alternate20|2|-16.505|-15.128|1.0000|
|volume-event|low|inverse_vol|random10|2|0.856|0.838|1.0000|
|online-mixture|wealth_mix|static_mix|original20|1|0.499|0.474|0.9910|
|online-mixture|wealth_mix|static_mix|alternate20|1|0.822|0.732|0.8412|
|online-mixture|wealth_mix|static_mix|random10|1|-0.089|-0.093|1.0000|
|online-mixture|wealth_mix|static_mix|original20|2|0.679|0.646|0.9600|
|online-mixture|wealth_mix|static_mix|alternate20|2|0.663|0.598|0.9500|
|online-mixture|wealth_mix|static_mix|random10|2|-0.115|-0.121|1.0000|

## 方法、范围与限制

同一251交易日日历，净值转换每日简单收益并包含首日相对初始资金的收益。21日非循环移动区块，1000重复，所有54列同次抽样使用相同日期索引；以bootstrap均值标准差标准化，中心化后每次取54列最大统计量，给出单侧家族校正p。未进行区块长度或显著性阈值寻优。协议在运行前保存。

区块bootstrap是此处明确设定的统计诊断，不声称严格有限样本控制或复现某篇方法论文。21日块下仅约12块有效信息，样本短且包括永久停机、大量现金与非平稳结构，区间和p值可能不稳健。有限样本、路径依赖使重采样不能替代新时期账户运行。

该校正只覆盖近期列出的9个候选×3池×2费用，不覆盖之前所有39阶段、模型及人工搜索。既有结果已查看，不可能由这次校正重新变成干净样本外。也不以无显著性证明没有经济效应。

数值检查验证区块范围/长度/块内连续性以及首日初始资金收益处理。输入报告SHA保存于JSON，所有候选与基线要求同一日期，不作插值。没有重复执行已有账户或修改产品。

## 对研究路径的影响

现有价格、事件、风险排序与简单财务回归不足以形成确认。后续不能通过调比例/阈值反复测试这些已知窗口，再以最好结果宣称成功；需要机制明确的额外信息或预先冻结的新增确认样本。当前数据仍可用于实现与失败诊断，最终成功判断必须保留验证边界。总体目标未完成。

# 多年企业质量与估值：18组开发诊断未通过

这轮检验企业类型而非短期走势：多年盈利能力、经营现金流资本效率和滞后年度盈利收益率，是否能判断适用股票。结果未支持该定义。企业经营质量与投资价格及随后回报是不同概念；不能据当前评分输出已验证的“适用”。

## 规则与口径

质量=三年中位净利润/资产+三年中位经营现金流/资产-三年ROA标准差；要求三年利润、现金流、资产均正，财年末间隔330—400日、最新期末不超过550日。所有输入filed严格早于当日，不使用未来财报。

收益率代理=最近年度净利润/同年度稀释加权平均股数/当前股价。这不是当前实际流通股市值、不是企业价值倍数，也没有分析师预期。只使用已公开的同期间股数，拆股/资本变化仍需要完整公司行动数据才能作更严格解释。

quality选资格企业质量分数前半；quality_value等权合并质量和收益率的分位排名选前半；eligible_risk不额外排序，持有全部基础资格企业。三者都按逆波动分配95%容量、单股20%上限、10%年化风险向下缩放，同原引擎/成本/止损。eligible_risk不是等权，也不是未过滤的全池买入持有。

BRK.B JPM MA SOFI V BAC GS MS PLD NEE SO按事前会计模型定义排除，XOM身份待核验。当前业务类别非严格历史行业数据；排除仅表示这个财务模型不支持它们，不表示不能使用其他交易策略。股数缺失不影响质量方法。完整规则见事前协议quality-value-protocol.md。

## 全部结果

| 股票池 | 方法 | 费用倍数 | 净收益% | 最大回撤% | 平均股票仓位% | 熔断 |
|---|---|---:|---:|---:|---:|---|
| original20 | quality | 1 | +10.199 | 9.215 | 62.77 | 否 |
| original20 | quality | 2 | +9.704 | 9.368 | 62.81 | 否 |
| original20 | quality_value | 1 | +14.580 | 8.100 | 69.73 | 否 |
| original20 | quality_value | 2 | +14.015 | 8.184 | 69.69 | 否 |
| original20 | eligible_risk | 1 | +20.684 | 7.546 | 72.76 | 否 |
| original20 | eligible_risk | 2 | +19.396 | 7.603 | 72.71 | 否 |
| alternate20 | quality | 1 | +10.766 | 8.283 | 71.59 | 否 |
| alternate20 | quality | 2 | +10.883 | 8.338 | 71.92 | 否 |
| alternate20 | quality_value | 1 | +14.223 | 8.824 | 74.49 | 否 |
| alternate20 | quality_value | 2 | +15.838 | 8.564 | 74.66 | 否 |
| alternate20 | eligible_risk | 1 | +18.143 | 7.519 | 88.90 | 否 |
| alternate20 | eligible_risk | 2 | +16.662 | 7.560 | 88.77 | 否 |
| random10 | quality | 1 | -9.553 | 10.182 | 30.99 | 是 |
| random10 | quality | 2 | -9.516 | 10.122 | 14.39 | 是 |
| random10 | quality_value | 1 | -7.580 | 10.282 | 37.86 | 是 |
| random10 | quality_value | 2 | -7.875 | 10.410 | 37.85 | 是 |
| random10 | eligible_risk | 1 | -7.324 | 10.465 | 48.24 | 是 |
| random10 | eligible_risk | 2 | -7.648 | 10.603 | 48.23 | 是 |

同资格风险预算在两个20股池均超过质量/质量价值的收益，而随机池所有候选亏损并触发熔断。不能把两个盈利股票池单独挑出来支持企业筛选。

部分双倍成本结果反而更高，是整数股、交易路径、止损触发及后续现金占用随成本变化导致，不能理解为“费用越高越好”。这些费用敏感性结果一并保留，没有只挑较好费用口径。

## 期初名单与可复核原因

- original20 / quality：NVDA, AAPL, META, GOOGL, MSFT, AVGO, COST。
- original20 / quality_value：GOOGL, META, AAPL, MSFT, NVDA, JNJ, COST。
- original20 / eligible_risk：AAPL, AMD, AVGO, COST, GOOGL, JNJ, LLY, META, MSFT, NVDA, ORCL, TSLA, WMT。
- alternate20 / quality：ADBE, HD, QCOM, TXN, PG, CSCO, CAT, MRK。
- alternate20 / quality_value：QCOM, MRK, ADBE, CAT, HD, PG, CVX, CSCO。
- alternate20 / eligible_risk：ABBV, ADBE, CAT, CRM, CSCO, CVX, GE, HD, IBM, KO, MRK, PEP, PG, QCOM, TXN, UNH。
- random10 / quality：LOW, ACN, MCD, NKE。
- random10 / quality_value：LOW, MCD, ACN, LMT。
- random10 / eligible_risk：ACN, GILD, INTU, LMT, LOW, MCD, NKE。

名单会因新年度报表、价格和排序变化而变化，以上只展示2025-09-02期初，不代表全年持仓。每股判断附完整财年数据、filed、accession、股数来源和拒绝原因，见同名JSON。quality_value分位是当前池相对排序，不能对单只股票脱离比较池解释为普遍适用阈值。

## 证据边界

本轮依托此前已读取的Novy-Marx盈利能力文献作为动机，但该论文主要使用毛利润/资产；这里的净利润、现金流、稳定性评分和年度收益率是自己提出的候选，并非论文复现。会计可比性、商誉、无形资产费用化、并购与一次性损益都可能使分数失真。未以本轮结果继续调权重。

当前所有三个股票池和时间已用于多轮开发，存在反复研究选择偏差；本轮失败是拒绝候选的证据，不能用其他单次盈利抵消。后续若提出新规则需要另行设计独立验证，不继续给当前失败规则加补丁并重称有效。

两项针对性测试通过：价格翻倍时盈利收益率减半而质量不变，未来股数重述不改变历史判断，超出业务范围/陈旧/缺失数据不返回候选通过。18组逐股贡献和账户损益核验一致，未修改网页策略。代码quality_value_features.py可输出每股候选财务判断，但正式status仍为证据不足。

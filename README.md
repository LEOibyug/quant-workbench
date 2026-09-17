# Quant Workbench

本地美股日内策略研究工作台：供应商 API 下载 → 离线训练与冻结实验 → 验证／最终测试 → 收益与成交复盘。前后端分离，研究页与展示页分开。研究页完成训练、验证、测试与复盘，发布独立策略／模型版本后可单向打开展示页；展示页没有返回研究的入口，也不读取实验数据或结果。

## 启动

Python 3.12，Node.js 22.12+ 或 24。macOS / Linux 原生运行，无容器。

```sh
uv sync --locked --extra neural --python 3.12
uv run --extra neural uvicorn quant_workbench.api:app --host 127.0.0.1 --port 8000
```

另一个终端：

```sh
cd frontend
npm ci --cache ../tmp/npm-cache
npm run dev
```

打开 [研究面板](http://127.0.0.1:5173/research) 或 [策略与模型展示](http://127.0.0.1:5173/workspace)。

## 直接获取行情

研究面板选择 Alpaca 或 Massive（原 Polygon）、股票和日期，调用供应商 API 下载，不需要 CSV 中转。后端启动前在本地环境配置凭证：

- Alpaca：`APCA_API_KEY_ID`、`APCA_API_SECRET_KEY`；支持 IEX / SIP。
- Massive：`MASSIVE_API_KEY`，兼容 `POLYGON_API_KEY`。

密钥只在后端读取；页面显示是否配置，不显示内容。可用历史范围、分钟权限、调用频率由套餐决定，软件不会代购订阅。下载自动分页，转为 UTC 分钟结束时间，仅保留常规交易时段并保存 Parquet 快照。实际账户连接需有效凭证；测试覆盖模拟 HTTP 合约，不代表真实订阅已验证。CSV仅为可选导入工具。

无需密钥可使用明确标注的合成示例，走完整个实验流程。示例不代表实际股票表现。

## 已实现

- 原版SMA、开盘突破、VWAP回归，以及趋势过滤突破/止跌确认回归：ATR风控、仓位风险预算、冷却、日损失限制。
- 因果卷积＋双尺度GRU/线性/RBF/双头MLP模型，输出未来1/5/15分钟上涨概率及收益；MLP融合短长程历史与已成熟预测/GT/误差反馈。前2k周期不参与交易，每股独立持续适应。
- 训练、验证、测试按日期隔离；离线训练模型固定保存，验证／测试分别重新加载并适应。最终测试暴露记录、重复结果复用。
- 次分钟开盘近似成交、价差、滑点、佣金、卖出规费、参与率限制、止损和日内清仓。
- 两页均支持单股动态模拟：价格与买卖点/净盈亏、资金/回撤/持仓曲线、日收益与模型预测；暂停、调速、拖动回放以及CSV导出。见[动态模拟与复盘](docs/simulations.md)。
- 完整实验另提供日收益Sharpe、逐股贡献、纯规则对照与在线概率评分。
- SQLite目录、Parquet行情、JSON结果、独立离线模型及在线检查点；数据和模型均不进入Git。

## 边界

首版用于分钟级研究，不是交易所级高频逐笔撮合，也没有实盘下单。常规时段、只做多、无杠杆、等额独立资金、禁止隔夜；缺失分钟会明确拒绝回测，尾盘无法在参与率内清仓则该次结果无效。基准是每日开盘买入、收盘卖出的无成本日内持有，跨日复利，不将拆股价格跳变计入隔夜收益。

上涨概率不等于扣费盈利概率；线性模型为基线，非线性模型仍需以独立区间检验真实市场优势。线性/RBF/MLP使用CPU；双尺度GRU使用PyTorch，默认CUDA→CPU自动选择（MPS已放弃），CUDA路径启用cudnn调优、TF32矩阵精度与开发期温度校准。主流供应商已接入两家，其他供应商通过同一适配器接口扩展。

文档：[环境与Linux兼容性](docs/setup.md)、[API与数据格式](docs/data-api.md)、[在线学习协议](docs/timeseries.md)、[存储估算](docs/storage-estimate.md)。原课件只保留本机，不上传GitHub。

## 数据分析与成本约束选型

研究页可启用收益幅度模型与成本过滤。严格模式下入场须满足规则、上涨概率和可选的预期收益成本门槛；另提供模型调节规则风险仓位的研究模式，见[入场融合说明](docs/entry-fusion.md)。无规则机会允许不交易。可配置价差、滑点、佣金、规费，并提供Alpaca免佣、IBKR阶梯首档及保守基础佣金情景；它们不等同于完整券商账单。

批量研究命令直接使用API下载的本地快照：

```sh
uv run quant-workbench study --dataset 数据集ID \
  --start 2024-01-02 --train-end 2024-02-06 \
  --validation-end 2024-02-16 --end 2024-03-01 \
  --output artifacts/studies/my-study
```

逐股比较三类规则 × 纯规则／概率过滤／成本倍数1／成本倍数1.5，共12个预先定义候选。仅开发期训练，验证阶段按扣费收益和回撤选型；无正评分或不足5笔完整交易则持币。选中配置额外在验证集上做1.5倍／2倍费用压力检查。全部选择先固定，只有显式添加`--include-test`才运行最终测试。输出report.md、study.json、selection.json；实验与离线模型同时保存在本地研究目录。曾看过的测试日期会标为已暴露。

合成数据报告仅用于验证流程，不能据此给NVDA等真实股票选择实盘策略。真实分析需要先配置供应商密钥并下载有适当市场覆盖的数据，见[密钥获取步骤](docs/provider-keys.md)。

增强研究添加 `--suite enhanced`，固定比较11个候选并保留旧规则对照。规则与新测试协议见[增强策略](docs/refined-strategies.md)。

上一轮真实数据结果见[增强规则与反馈模型评估](docs/research-results/2026-09-18-feedback-model.md)：新模型尚未优于简单基线，未自动发布。

序列网络升级：因果卷积＋双尺度GRU＋注意力，结合成熟误差反馈和小批次回放；新增趋势回调与状态组合规则。使用 `--suite sequence` 进行分段稳定性验证，见[网络、设备与研究协议](docs/sequence-model.md)。

最新[序列网络与设备评估](docs/research-results/2026-09-18-sequence-network.md)：GRU验证评分优于MLP，但尚未超过简单基线；研究命令使用 `uv run --extra neural quant-workbench study --suite sequence ...`。

[入场稀疏与三组佣金对照](docs/research-results/2026-09-18-entry-and-commissions.md)：旧严格模型换佣金仍仅3笔；新规则与标准化GRU仓位调节有241—243笔，保守费用下仍亏损，作为研究候选保留。

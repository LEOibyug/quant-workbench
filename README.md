# Quant Workbench

美股日内策略研究工作台：供应商 API 下载 → 离线训练与冻结实验 → 验证／最终测试 → 收益与成交复盘。计算服务与本地工作台分别启动，开发和展示整合在同一网页，可来回切换。

## 分别启动计算服务与本地工作台

Python 3.12，Node.js 22.12+ 或 24。macOS / Linux 原生运行，无容器。

**计算服务器**（训练、回测、模拟、行情获取和数据持久化）：

一键启动（已安装 `uv`）：

```sh
./scripts/start-compute.sh
```

脚本自动安装锁定的 neural 依赖，以 `0.0.0.0` 监听系统分配的空闲端口，并打印网页应填写的端口。选择没有计算进程、显存占用不超过 512 MiB、利用率不超过 5% 的 NVIDIA GPU，优先选择空闲显存最多的一张；通过 `CUDA_VISIBLE_DEVICES` 将模型限制到该卡。无空闲 GPU 或 CUDA 不可用时明确退出，不自动退回 CPU。GPU 空闲检查是启动时快照，不是集群资源预留，其他用户仍可能随后占用该卡。

可用参数：`--dry-run` 仅检查；`--port 8001` 指定端口（占用则报错）；`--cpu` 显式使用 CPU；`--max-gpu-memory-mib 512` / `--max-gpu-utilization 5` 调整空闲阈值。脚本前台运行，Ctrl+C 停止。已有计算服务使用同一数据目录时不要重复启动。

手动指定监听地址及端口：

```sh
uv sync --locked --extra neural --python 3.12
uv run --extra neural quant-workbench serve-compute --host 0.0.0.0 --port 8001
```

在服务器配置供应商密钥，`QUANT_DATA_DIR` 指向数据目录（默认 `data`）。已有数据目录可直接沿用，无须迁移格式。单个数据目录只启动一个计算进程，不使用多 worker 或热重载。

**本地机器**只需轻量 Python 网关和前端，无须安装 PyTorch 或复制模型、行情：

```sh
uv venv .venv-local --python 3.12
uv pip install --python .venv-local/bin/python -r requirements-local.txt
.venv-local/bin/python -m uvicorn quant_workbench.local_api:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

若本地已经安装完整项目，也可运行 `uv run quant-workbench serve-local`。

另一个本地终端：

```sh
cd frontend
npm ci
npm run dev
```

打开 [工作台](http://127.0.0.1:5173/research)，在顶部填写计算服务器 IP／主机名、端口（默认 `8001`），点击「连接并保存」。验证成功后保存到当前浏览器，开发页和展示页共用连接；左侧导航支持双向切换并保留本次页面状态。两项服务也可以在同一机器上分别启动。

网页 → 本地网关（8000）→ 计算服务（8001）。网关转发行情上传、任务提交、进度、结果和 CSV 下载；不运行模型，不写入计算数据目录。进度采用自动轮询和断线重试，训练／下载任务 ID 按服务器地址保存。关闭网页不终止已提交任务，重新打开或重新连接后可继续查看；回测和模拟也可从各自历史记录恢复。计算服务重启会将中断任务标记失败，不会自动续算。

计算服务应部署在可信局域网／VPN 内；当前不提供公网身份认证。本地网关保持 `127.0.0.1` 监听。也可通过 SSH 隧道把服务器的计算端口转发到本机，再在页面填写 `127.0.0.1` 和转发端口。`QUANT_API_TARGET` 仅用于改变 Vite 的**本地网关**目标，不应直接指向计算服务器。

旧入口 `quant_workbench.api:app` 仍作为计算服务兼容入口；新部署请使用上述拆分入口。详细接口约定见 [远程计算服务](docs/remote-compute.md)。

## 直接获取行情

研究面板选择 Alpaca 或 Massive（原 Polygon）、股票和日期，调用供应商 API 下载，不需要 CSV 中转。计算服务启动前在服务器环境配置凭证：

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

盈利策略搜索日志（vwap回归参数搜索、自适应门控对照与尾盘动量策略）：验证期最优+3.40%未通过一次性最终测试（-3.11%），样本外盈利未成立，全部尝试见[搜索日志](docs/research-results/2026-09-18-profitable-strategy-log.md)。

第二轮机制探索（同日志）：新增**因果市场状态门控**（`regime_gate`，basket前N日漂移/效率，只禁开仓不碍退出）与**walk-forward评估协议**（[scripts/walk_forward.py](scripts/walk_forward.py)）；门控消除全部深度亏损月（walk-forward 3个月+1.57%、无亏损月）。按需求实现**分批波动收割** `scaled_reversion`（逐档加仓、各批独立止盈止损，`max_scaling_lots`），本数据上弱于单批，保留为可选策略。

[入场稀疏与三组佣金对照](docs/research-results/2026-09-18-entry-and-commissions.md)：旧严格模型换佣金仍仅3笔；新规则与标准化GRU仓位调节有241—243笔，保守费用下仍亏损，作为研究候选保留。

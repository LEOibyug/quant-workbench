# 行情供应商与研究 API

本地后端文档为 http://127.0.0.1:8000/docs 。所有路径以 `/api` 开头。

## 供应商直连

`GET /providers` 返回供应商、凭证是否配置和套餐说明。`POST /datasets/fetch` 示例：

```json
{"provider":"alpaca","symbols":["NVDA","TSLA","AAPL","AMD","SOFI"],"start":"2024-01-02","end":"2024-03-01","feed":"sip"}
```

Massive使用 `"provider":"massive"`，不使用feed字段。日期按纽约交易日解释，end右端不含。下载自动分页；失败、限流、非法分页地址、返回缺少指定股票时明确报错，不保存截断结果。凭证不经前端传递，Alpaca使用请求头，Massive使用Bearer认证。分页限制固定供应商域名，不随重定向泄露密钥。

数据均请求raw价格用于日内成交与按股收费，不把复权价格误作历史可成交价格。特征和标签不跨日；基准按日开收盘计算，无隔夜公司行动收益。尚未实现隔夜总回报、退市样本选择、自动重试限流或分布式下载。

官方接口参考：

- https://docs.alpaca.markets/reference/stockbars
- https://massive.com/docs/rest/stocks/aggregates/custom-bars
- https://github.com/massive-com/client-python

本地保存数据来源与SHA256，实验引用不可变快照。缓存用于复现，用户正常使用不需要手动传递CSV。Alpaca IEX行情不代表完整市场，SIP和Massive分钟历史通常依权限与套餐。缺失分钟、停牌等目前由完整性检查拒绝，不虚构可成交量。

## 实验与运行

- `GET /datasets` / `POST /datasets/demo`：本地快照与合成示例。
- `POST /experiments`：指定dataset_id、symbols、start/train_end/validation_end/end、config与model；在开发期训练、分析逐股特征、保存冻结实验。
- `GET /experiments`：实验与运行状态。
- `POST /experiments/{id}/run/{train|validation|test}`：单机后台运行；测试须先完成验证，重复完成的运行复用结果。
- `GET /experiments/{id}/results/{phase}`：最多300笔成交和抽样曲线。
- `GET /experiments/{id}/export/{phase}/{trades|curve|daily_returns}`：完整CSV下载。

训练回放为样本内分析。验证和测试分别重新加载同一离线模型，在线学习只用该阶段逐步揭晓的标签。重复创建实验不会使已看过的测试日期重新变成未见数据，界面会提示历史暴露。

## 可选CSV兼容

仅为已有数据的导入工具，非必经工作流。`POST /datasets/import`使用multipart字段file。
列为 `timestamp,symbol,open,high,low,close,volume`。UTC或带偏移的整分钟结束时间，例如 `2024-01-03T14:31:00Z` 表示纽约09:30—09:31。volume为实际股数整数。重复、NaN、无时区、非法OHLC、非正常交易时段会拒绝。最多100MB、200万行、10只股票；更大研究范围应拆分下载和实验。

## 存储与服务限制

`QUANT_DATA_DIR`默认data。`datasets/`保存Parquet；catalog.sqlite保存目录；`results/`保存全量JSON；`models/`保存可信本地joblib。离线模型与每阶段在线检查点独立，依赖升级后需重新训练。不要从外部拷入未经信任的joblib。

服务以单进程运行；单次后台回测，启动时将中断的任务标记失败。原始输入与模型哈希校验，结果与模型原子写入。配置和数据需独立备份，Git只保存源码。

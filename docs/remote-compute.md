# 远程计算服务

## 进程与数据归属

- `quant_workbench.compute_api:app`：行情供应商、数据集、训练、回测、动态模拟、发布版本及结果；数据存放在服务器的 `QUANT_DATA_DIR`。
- `quant_workbench.local_api:app`：仅 HTTP 网关，依赖 `requirements-local.txt`，不导入计算模块或打开 SQLite。
- Vite / React：本地开发与展示、参数编辑、图表、回放、导出文件保存。开发与展示共用侧栏和连接配置，页内切换保留状态。

启动命令见 [README](../README.md)。Vite 开发服务器和 preview 均将 `/api` 转发至本地网关，默认 `http://127.0.0.1:8000`。

## 连接协议

浏览器所有 `/api` 请求携带 `X-Quant-Compute-URL: http://服务器:端口`，包括上传和下载。网关只接受 HTTP(S) origin，不接受用户信息、路径或查询串；仅转发必要请求头，不转发浏览器 Cookie。地址是每个请求的配置，不在服务端全局保存，因此不同浏览器连接互不覆盖。没有请求头的客户端可使用 `QUANT_COMPUTE_URL` 环境变量，默认 `http://127.0.0.1:8001`。

`GET /api/health` 验证 `service=quant-workbench-compute` 和 `protocol_version=1`；网页仅在验证通过后保存地址并重新加载，失败保留原连接。本地网关的独立健康检查为 `GET /local/health`。服务器不可达返回 502；计算端的 404、422 等状态码与错误内容保留。网关连接超时 5 秒，响应读取超时 300 秒，不自动重试任务提交，避免重复计算。

## 任务、进度和结果

| 操作 | 接口 |
| --- | --- |
| 异步下载 / 训练 | `POST /api/research/operations/download`、`POST /api/research/operations/train` |
| 下载 / 训练进度及结果 | `GET /api/research/operations/{id}` |
| 回测提交 | `POST /api/experiments/{id}/run/{phase}` |
| 回测进度 | `GET /api/experiments` 或 `GET /api/experiments/{id}` 中的 `runs[].progress` |
| 回测结果 / 导出 | `GET /api/experiments/{id}/results/{phase}`、`GET /api/experiments/{id}/export/{phase}/{kind}` |
| 模拟提交 | `POST /api/{scope}/simulations` |
| 模拟历史 / 进度 | `GET /api/{scope}/simulations?source_id=...`、`GET /api/{scope}/simulations/{id}` |
| 模拟快照 / 导出 | `GET /api/{scope}/simulations/{id}/result`、`GET /api/{scope}/simulations/{id}/export/{kind}` |

进度字段包括 `status`、`stage`、`done`、`total`、`unit`、时间及错误信息，沿用原有阶段进度口径；前端自动轮询，无需浏览器直连服务器或配置跨域。动态模拟可增量读取快照。上传和下载通过网关流式传输，CSV 文件名和响应类型保留。

任务独立于网页连接运行。训练 / 下载的待恢复 ID 以服务器地址作为浏览器存储命名空间；重连同一服务器后自动恢复查询。切换服务不会取消原服务器任务。重启计算进程后中断任务记为失败；尚不支持跨服务器迁移任务、进程崩溃续算或多 worker 调度。旧版未带服务器命名空间的浏览器任务标记不自动继承。

计算服务没有公网认证，使用可信网络、VPN 或 SSH 隧道。本地网关只监听 loopback；服务器供应商密钥不传给浏览器。已有数据保留在原计算机器即可，客户端通过 API 使用，无需共享文件系统。

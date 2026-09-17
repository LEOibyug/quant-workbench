# Quant Workbench

本地美股日内策略研究工作台。当前交付为工程基础、存储估算和两个独立前端入口，历史回测、真实行情及实时交易尚未实现。

Python 3.12，Node.js 22或24，macOS Apple Silicon / Linux x86_64。无容器要求，默认CPU可运行。安装、验证、GPU扩展及数据开销见 `docs/setup.md` 和 `docs/storage-estimate.md`。

```sh
uv sync --locked
uv run quant-workbench doctor
uv run quant-workbench estimate
uv run uvicorn quant_workbench.api:app --host 127.0.0.1 --port 8000
```

另一个终端运行前端：

```sh
cd frontend
npm ci
npm run dev
```

浏览器打开 `http://127.0.0.1:5173/research` 或 `http://127.0.0.1:5173/workspace`。

默认研究假设：NVDA、TSLA、AAPL、AMD、SOFI，SPY/QQQ作为基准；1分钟数据、常规时段、只做多、不加杠杆、当日清仓。数据周期暂按24个月估算。这里是研究配置，不表示已验证收益。

源码和依赖锁文件可以拉取到Linux服务器；虚拟环境、行情、模型、账户凭证与参考课件不进入Git。不要复制Mac的`.venv`到Linux。原始课程材料仅保留在本机 `参考/`。

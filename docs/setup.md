# 本地开发与Linux兼容性

## 支持范围

Python 3.12，macOS arm64、Linux x86_64；前端支持Node.js 22.12及以上的22系列，或24系列。当前Mac验证加GitHub Actions双系统CPU检查，不表示已在用户的NVIDIA服务器实测。项目不依赖容器、Apple专有框架或CUDA。

## 安装与启动

安装官方uv和Node.js后，在项目根目录：

```sh
uv sync --locked --python 3.12
source .venv/bin/activate
quant-workbench doctor
```

`uv sync`会在项目根目录创建`.venv`。Linux拉取代码后执行同一命令；不要同步Mac的虚拟环境。`uv.lock`锁定跨平台版本和包校验信息，各系统自动使用对应wheel。修改依赖后执行`uv lock`，将锁文件和依赖声明一起提交。

当前Mac的既有npm全局缓存存在权限问题。本项目安装已使用 `npm ci --cache ../tmp/npm-cache`（在frontend目录执行）绕开，无需修改全局目录权限；其他机器可正常使用`npm ci`。

在后端启动前配置供应商API密钥。可复制`.env.example`为被Git忽略的`.env`，填入自己的密钥，然后在当前终端执行`set -a; source .env; set +a`。应用读取环境变量，不自动读取.env文件。

统一启动：

```sh
./scripts/start.sh
```

脚本会安装依赖、构建网页，并通过统一后端提供开发页、展示页和全部 API。打开打印的工作台 URL；默认 `0.0.0.0` 监听并分配空闲端口，可用 `--port 8000` 固定端口，或 `--cpu --host 127.0.0.1` 在无 GPU 的本机启动。GPU 选择、数据目录及停止行为见[README](../README.md)。

开发页与展示页分别为 `/research`、`/workspace`，可双向切换。API 文档为同一端口的 `/docs`。供应商 HTTP 客户端读取标准 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 环境配置。

## 数据位置

默认相对于运行目录使用`data/`。服务器可设置绝对路径：

```sh
export QUANT_DATA_DIR=/srv/quant-data
uv run quant-workbench doctor
```

该变量控制环境诊断、行情、模型、实验及结果保存根目录。配置与路径使用`pathlib`和环境变量，不在代码中写入个人的Mac路径。日期存储约定UTC，市场规则使用`America/New_York`；数据格式优先Parquet/JSON，避免将不可信pickle作为交换格式。

## 可选PyTorch与设备自适应

GRU安装和启动必须带neural extra：`uv sync --locked --extra neural`、`./scripts/start.sh`。默认CUDA→CPU（MPS支持已放弃，面向CUDA生态开发），`QUANT_TORCH_DEVICE`可手动指定auto/cuda/cpu，模型跨设备保存为CPU权重。详见[序列网络](sequence-model.md)。

### NVIDIA服务器

逐步事件回测、文件读取、DuckDB/普通Pandas操作不会因为安装CUDA自动使用GPU。优先考虑GPU的工作包括大批量模型训练和可向量化的参数搜索；在功能实现时保留CPU路径并显式选择设备。

基础环境故意不安装PyTorch/CUDA。服务器上先运行`nvidia-smi`检查驱动与显卡，再到[PyTorch官方安装选择器](https://pytorch.org/get-started/locally/)选取与驱动相容的Linux/CUDA命令。本次未检查服务器驱动，不预先固定CUDA版本。

为避免日常`uv sync`移除额外安装的包，创建独立可重建的GPU环境：

```sh
uv venv --python 3.12 .venv-gpu
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file /tmp/quant-base-requirements.txt
uv pip sync --python .venv-gpu/bin/python /tmp/quant-base-requirements.txt
uv pip install --python .venv-gpu/bin/python --no-deps -e .
```

之后使用选择器给出的版本和index，将安装目标指定为`.venv-gpu/bin/python`。不要把未核实的CUDA wheel安装到Mac。验证时运行：

```sh
.venv-gpu/bin/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

只有`torch.cuda.is_available()`为真且小型训练基准通过后才能声明GPU可用。确认后把精确版本、CUDA index及驱动要求记录为服务器配置；项目已实现PyTorch双尺度GRU计算路径，CUDA→CPU自适应（MPS已放弃），CUDA下启用cudnn调优与TF32；基础依赖仍不要求GPU。GPU环境可通过`uv pip freeze --python .venv-gpu/bin/python`留存版本，但还需保存安装index和硬件环境，不能仅靠freeze声称完全可复现。

## 验证与Git管理

```sh
uv run pytest -q
uv run ruff check .
uv run quant-workbench estimate --symbols 7 --years 2
uv run python scripts/benchmark_storage.py
cd frontend
npm ci
npm run build
```

Git跟踪代码、依赖锁文件和分析文档。忽略`.venv*`、`node_modules`、数据、模型、日志、临时文件、`.env*`及原始课件。GitHub默认私有。数据备份使用独立磁盘或备份目录，源码Git仓库不能代替数据备份。

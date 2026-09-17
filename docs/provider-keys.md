# 获取和配置行情API密钥

## Alpaca（建议先验证这条路径）

1. 打开 https://alpaca.markets/ 注册并登录。
2. 切换到 Paper Trading 模拟账户控制台，找到 API Keys / Generate API Keys。菜单名称以当前网页为准。
3. 生成 Key ID 与 Secret Key，Secret通常仅显示一次；保存在自己的密码管理器或本机配置里。
4. 在项目根目录复制`.env.example`为`.env`，填入APCA_API_KEY_ID和APCA_API_SECRET_KEY。
5. 先在研究页选Alpaca、IEX、一只股票和一天日期，测试历史分钟端点权限。

行情与交易权限、地区注册资格、历史范围和套餐限制以账户为准。免费IEX为单一交易所覆盖；不能把它当作全市场成交量或盘口。需要完整市场分钟数据时再核对SIP权限。先验证已有权限，不必为了获取密钥先入金实盘。

官方行情说明：https://docs.alpaca.markets/docs/about-market-data-api

## Massive（原Polygon）

在 https://massive.com/ 注册登录，进入Dashboard的API Keys获取密钥，填入`.env`的MASSIVE_API_KEY。旧POLYGON_API_KEY变量也可识别。密钥本身不代表拥有所有历史分钟数据权限，需要核对股票数据套餐的历史覆盖、调用次数和分钟聚合权限。

官方分钟端点：https://massive.com/docs/rest/stocks/aggregates/custom-bars

## 本地配置与启动

```dotenv
APCA_API_KEY_ID=你的KeyID
APCA_API_SECRET_KEY=你的SecretKey
# 或仅配置另一家
MASSIVE_API_KEY=你的MassiveKey
```

只填写你选用的供应商。不要把凭证发送到聊天、前端输入框或提交Git。本项目忽略`.env`，`.env.example`始终是空值模板。

后端启动终端中：

```sh
set -a
source .env
set +a
uv run uvicorn quant_workbench.api:app --host 127.0.0.1 --port 8000
```

后端读取启动时的环境变量，修改文件后须重启。若已有8000端口的后端，在原终端按Ctrl-C结束再启动；不要重复启动占用同一端口。

研究页“密钥已配置”只检查是否存在变量，并不代表认证与数据订阅已验证；以实际下载结果为准。遇到403通常核对权限/订阅/日期范围，429检查调用频率；不要通过聊天粘贴含Authorization头的日志。

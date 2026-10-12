# 加密货币因子挖掘与量化交易实验平台（Crypto Factor Mining Experiment）

一个开箱即用的数字资产量化研究与模拟交易实验平台：专注于 **OKX 现货（SPOT）与永续合约（SWAP）** 的因子实验室、策略回测、模拟盘交易、AI 辅助看盘与 24/7 实时行情，全部数据自托管。

> **说明**：平台现已全面适配 **OKX 加密资产**，默认直连 **OKX 公开行情接口**（WebSocket 实时增量推送 + REST 快照兜底），**零凭据 / 无需 API Key** 即可启动并实时接入全市场行情数据。国内期货专属代码（CTP、新浪财经、SimNow 及休市日历限制）已完成剥离，系统支持 24/7 全天候连续运行。

## 核心功能

- **OKX 实时行情**：直连 OKX 公开 WebSocket（`wss://ws.okx.com:8443/ws/v5/public`）与 REST 接口，支持现货与永续合约全市场标的，24/7 全天候无休市，毫秒级推流、自动断线重连与 REST 快照自动兜底。
- **标的规格与精度**：自动拉取并缓存 OKX 标的规格（合约面值 `ctVal`、数量步长 `lotSz`、最小委托量 `minSz`、价格跳动 `tickSz`），内部采用统一归一化小写命名（如 `btc-usdt-swap`、`btc-usdt`、`eth-usdt-swap`）。
- **因子实验室**：内置 60+ 量化特征与算子，支持基于表达式的因子挖掘与自动搜索，token 编码可复现，支持全截面与单标的多维度评价（IC/IR/分层收益等）。
- **策略回测**：支持多周期（1m、5m、15m、30m、1H、1D 等）K 线策略回测、AI 生成 K 线压力测试与决策模型回测。
- **模拟交易**：全天候纸面账户、挂单撮合引擎、持仓与权益曲线追踪、平仓标准监控（指标交叉 / 因子阈值 / 动态止损）。
- **量化任务与信号**：策略信号实时计算、多周期共振监控、信号触发自动告警。
- **AI 看盘与交易助手**：LLM 驱动的主播式盘面实时解盘与多轮对话交易辅助，支持自定义配置多 AI 模型与提供商渠道。
- **管理后台**：行情通道健康监控、系统设置、K 线缓存状态及用户配额管理。

## 技术栈

- **后端**：Python 3.12+ / FastAPI / SQLAlchemy 2.0 (asyncio) / PostgreSQL 18 / Redis 7 / websockets / httpx / uv
- **前端**：Next.js 15 / React 19 / TailwindCSS 4 / Radix UI / lightweight-charts
- **部署**：Docker Compose

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 复制并调整环境变量配置
cp .env.example .env

# 2. 启动服务（含内置 PostgreSQL 与 Redis 基础环境）
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

### 方式二：本地开发环境

#### 1. 启动基础设施

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d postgres redis
```

#### 2. 后端服务

```bash
cd backend

# 安装依赖
uv sync

# 运行测试套件（含 OKX 接入与导入完整性校验）
uv run pytest

# 启动后端 API（OKX 行情服务随应用自动拉起）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

#### 3. 前端服务

```bash
cd frontend

# 安装依赖并启动
pnpm install
pnpm dev
```

前端开发服务器将运行在 `http://localhost:3000`。

## 行情源说明

| 源            | 协议 / 模式      | 说明                                                              |
| ------------- | ---------------- | ----------------------------------------------------------------- |
| `okx`（默认） | WebSocket + REST | 直连 OKX 公开行情（无需 API Key），覆盖主流及全市场现货与永续合约 |
| `okx_demo`    | 模拟交易环境     | OKX 官方模拟盘环境（请求头 `x-simulated-trading: 1` 切换）        |

> **提示**：公开行情接口无需提供 OKX API Key / Secret。如需在私有网络或受限网络环境中运行，请确保容器具有访问 `https://www.okx.com` 与 `wss://ws.okx.com:8443` 的网络能力。

## 免责声明

本项目仅供量化策略学习研究与模拟交易实验使用，不构成任何投资建议与决策参考。接入实盘行情或交易所接口所产生的资金风险与法律合规责任由使用者自行承担。

## License

[MIT](LICENSE)

## 社区

本项目已链接认可 [LINUX DO](https://linux.do) 社区。

> LINUX DO —— 真实、友善、纯粹的交流社区

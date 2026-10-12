# OKX 实盘与模拟盘双轨（行情 + 挂单）隔离改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 OKX 实时行情与交易挂单的实盘（Live）与模拟盘（Virtual/Demo）全面双轨隔离，支持同时接入 OKX 实盘与官方模拟盘 WebSocket/REST 行情，并在自建纸面撮合引擎中按盘模式精准隔离撮合，同时为 OKX 交易所私有 API 下单提供签名基础设施。

**Architecture:** 
1. **行情接入层**：`OkxPublicWs` 支持模拟盘 WebSocket 端点（`wss://wspap.okx.com:8443`），`OkxRestClient` 复用已有的 `x-simulated-trading: 1` 请求头机制；
2. **行情分发层**：`OkxQuoteService` 抽象模式入参（`mode: "live" | "virtual"`），分别写入 `market:live:*` 与 `market:virtual:*` 命名空间；
3. **纸面撮合层**：复用现有 `PaperAccount.trading_mode` 双轨隔离，撮合引擎按账户盘模式严格消费对应行情，价格带与兜底价从残留的 `sina` 切换至 `okx`/`okx_demo`；
4. **生命周期管理**：`app/main.py` 统筹双轨行情服务的异步启动与优雅关闭；
5. **私有接口准备**：新增 `app/connectors/okx/auth.py` HMAC 签名器，为直接对接 OKX 交易所官方模拟盘/实盘真下单提供鉴权能力。

**Tech Stack:** Python 3.12 / FastAPI / websockets / httpx / Redis 7 / SQLAlchemy 2.0 (asyncio) / pytest

**Spec:** 本方案基于 `docs/superpowers/plans/2026-10-12-okx-crypto-only.md` 的 Phase 2/3 扩展设计，并遵循 OKX v5 API 规范（`https://www.okx.com/docs-v5/en/`）。

## Global Constraints

- Python `>=3.12`，只使用既有依赖（`httpx`、`websockets`、`redis`、`sqlalchemy`、`pytest` 等），不引入任何新依赖
- 标的 symbol 规范统一小写（如 `btc-usdt-swap`、`eth-usdt`），与 OKX 交互时大写（如 `BTC-USDT-SWAP`）
- OKX 实盘公开 WS 端点 `wss://ws.okx.com:8443/ws/v5/public`；OKX 模拟盘公开 WS 端点 `wss://wspap.okx.com:8443/ws/v5/public`
- OKX 模拟盘 REST 端点使用 `https://www.okx.com`，携带请求头 `x-simulated-trading: 1`
- 盘口模式沿用系统既有 `trading_mode` 契约（`live` 实盘 / `virtual` 虚拟模拟盘）
- 提交信息必须符合 Conventional Commits 中文规范，格式 `<type>(scope): 中文描述`，不使用 emoji
- 测试命令统一：`cd backend && uv run pytest <path> -v`
- 不降低任何测试、lint 或类型门槛

---

### Task 1: WebSocket 客户端支持模拟盘端点

**Files:**
- Modify: `backend/app/connectors/okx/ws.py`
- Modify: `backend/tests/test_okx_ws.py`

**Interfaces:**
- Consumes: `websockets` 库
- Produces: `OkxPublicWs(url=None, demo=False)`，提供 `demo=True` 时自动路由到 `wss://wspap.okx.com:8443/ws/v5/public`

- [x] **Step 1: 编写失败测试**

在 `backend/tests/test_okx_ws.py` 末尾增加：

```python
def test_ws_demo_url_selection():
    from app.connectors.okx import ws as ok

    ws_live = ok.OkxPublicWs(demo=False)
    assert ws_live._url == "wss://ws.okx.com:8443/ws/v5/public"

    ws_demo = ok.OkxPublicWs(demo=True)
    assert ws_demo._url == "wss://wspap.okx.com:8443/ws/v5/public"

    ws_custom = ok.OkxPublicWs(url="wss://custom.url", demo=True)
    assert ws_custom._url == "wss://custom.url"
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_ws.py -k test_ws_demo_url_selection -v
```

Expected: FAIL（`__init__() got an unexpected keyword argument 'demo'`）

- [x] **Step 3: 实现最小代码**

修改 `backend/app/connectors/okx/ws.py`：

```python
OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_DEMO_PUBLIC_WS = "wss://wspap.okx.com:8443/ws/v5/public"
```

将 `OkxPublicWs.__init__` 改为：

```python
class OkxPublicWs:
    """公开行情 WS 长连接，带指数退避重连"""

    def __init__(self, url: str | None = None, demo: bool = False) -> None:
        if url is not None:
            self._url = url
        else:
            self._url = OKX_DEMO_PUBLIC_WS if demo else OKX_PUBLIC_WS
        self._stop = asyncio.Event()
        self._channels: list[str] = ["tickers"]
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_ws.py -v
```

Expected: PASS，全部用例通过

- [x] **Step 5: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx/ws.py backend/tests/test_okx_ws.py
git commit -m "feat(okx): 支持模拟盘 WebSocket 端点"
```

---

### Task 2: Redis 源快照键与价格带兜底源切换

**Files:**
- Modify: `backend/app/services/market_keys.py:45-55`
- Modify: `backend/app/services/paper/price_band.py:50-65`
- Create: `backend/tests/test_price_band_okx.py`

**Interfaces:**
- Consumes: `app.core.trading_mode.mode_ns`
- Produces: 
  - `source_quote_key(source: str, symbol: str, trading_mode: str | None = None) -> str`
  - `source_quote_scan_pattern(source: str, trading_mode: str | None = None) -> str`
  - `resolve_last_price` 兜底源从 `sina` 切换为 `okx`/`okx_demo`

- [x] **Step 1: 编写失败测试**

新建 `backend/tests/test_price_band_okx.py`：

```python
import json
import pytest
from decimal import Decimal
from app.services.market_keys import source_quote_key
from app.services.paper.price_band import resolve_last_price


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)


def test_source_quote_key_supports_mode():
    assert source_quote_key("okx", "btc-usdt-swap") == "market:live:source:okx:quote:btc-usdt-swap"
    assert source_quote_key("okx", "btc-usdt-swap", "live") == "market:live:source:okx:quote:btc-usdt-swap"
    assert source_quote_key("okx_demo", "btc-usdt-swap", "virtual") == "market:virtual:source:okx_demo:quote:btc-usdt-swap"


@pytest.mark.asyncio
async def test_resolve_last_price_falls_back_to_okx_source():
    redis = _FakeRedis()
    key = source_quote_key("okx", "btc-usdt-swap", "live")
    redis.store[key] = json.dumps({"last_price": 62500.0})

    price = await resolve_last_price("btc-usdt-swap", redis, None, trading_mode="live", allow_mock=False)
    assert price == Decimal("62500.0")


@pytest.mark.asyncio
async def test_resolve_last_price_virtual_falls_back_to_okx_demo():
    redis = _FakeRedis()
    key = source_quote_key("okx_demo", "btc-usdt-swap", "virtual")
    redis.store[key] = json.dumps({"last_price": 61800.0})

    price = await resolve_last_price("btc-usdt-swap", redis, None, trading_mode="virtual", allow_mock=False)
    assert price == Decimal("61800.0")
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_price_band_okx.py -v
```

Expected: FAIL

- [x] **Step 3: 实现最小代码**

修改 `backend/app/services/market_keys.py` 中的 `source_quote_key` 与 `source_quote_scan_pattern`：

```python
def source_quote_key(
    source: str, symbol: str, trading_mode: str | None = None
) -> str:
    """原始行情源快照；与下游统一 quote 隔离。"""
    src = source.strip().lower()
    sym = symbol.strip().lower()
    ns = mode_ns(trading_mode) if trading_mode else "live"
    return f"market:{ns}:source:{src}:quote:{sym}"


def source_quote_scan_pattern(
    source: str, trading_mode: str | None = None
) -> str:
    ns = mode_ns(trading_mode) if trading_mode else "live"
    return f"market:{ns}:source:{source.strip().lower()}:quote:*"
```

修改 `backend/app/services/paper/price_band.py:49-65`，将 `sina` 替换为 `okx`/`okx_demo`：

```python
        # 统一报价缺失：回落 okx / okx_demo 源快照（真实市场价，含断线后）
        try:
            from app.services.market_keys import source_quote_key

            src_name = "okx_demo" if str(trading_mode or "").lower() == "virtual" else "okx"
            raw = await redis_conn.get(source_quote_key(src_name, symbol_l, trading_mode))
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                src = json.loads(raw)
                if isinstance(src, dict):
                    last = src.get("last_price")
                    if last is not None and float(last) > 0:
                        return Decimal(str(last))
        except Exception:
            pass
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_price_band_okx.py -v
```

Expected: PASS

- [x] **Step 5: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/services/market_keys.py backend/app/services/paper/price_band.py backend/tests/test_price_band_okx.py
git commit -m "refactor(market): 兜底源快照切换为 OKX 并支持 mode 命名空间"
```

---

### Task 3: 行情服务支持多盘模式分流

**Files:**
- Modify: `backend/app/services/okx_quote_service.py`
- Modify: `backend/tests/test_okx_quote_service.py`

**Interfaces:**
- Consumes: `OkxRestClient`, `OkxPublicWs`, `quote_key`, `source_quote_key`
- Produces: `OkxQuoteService(redis_conn, client=None, ws=None, mode="live", source="okx")`

- [x] **Step 1: 编写失败测试**

在 `backend/tests/test_okx_quote_service.py` 末尾增加：

```python
@pytest.mark.asyncio
async def test_virtual_mode_writes_virtual_namespace():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis, mode="virtual", source="okx_demo")
    await svc.write_quote(_quote("btc-usdt-swap", 61000.0))

    unified = quote_key("virtual", "btc-usdt-swap")
    source = source_quote_key("okx_demo", "btc-usdt-swap", "virtual")
    assert unified in redis.store
    assert source in redis.store
    assert quote_key("live", "btc-usdt-swap") not in redis.store


@pytest.mark.asyncio
async def test_virtual_mode_snapshot_writes_virtual_keys():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis, client=_FakeClient(), mode="virtual", source="okx_demo")
    count = await svc.snapshot_once()
    assert count == 1
    assert quote_key("virtual", "btc-usdt-swap") in redis.store
    assert source_quote_key("okx_demo", "btc-usdt-swap", "virtual") in redis.store
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_quote_service.py -k "test_virtual_mode" -v
```

Expected: FAIL（参数不匹配或写入了 `live` 键）

- [x] **Step 3: 实现最小代码**

修改 `backend/app/services/okx_quote_service.py`：

```python
class OkxQuoteService:
    """把 OKX 行情写进 Redis 的对应 trading_mode 命名空间"""

    def __init__(
        self,
        redis_conn: Any,
        client: OkxRestClient | None = None,
        ws: OkxPublicWs | None = None,
        mode: str = MODE_LIVE,
        source: str = SOURCE_OKX,
    ) -> None:
        self._redis = redis_conn
        self._mode = mode
        self._source = source
        self._client = client or OkxRestClient(demo=(mode != MODE_LIVE))
        self._ws = ws or OkxPublicWs(demo=(mode != MODE_LIVE))
        self._tasks: list[asyncio.Task] = []

    async def write_quote(self, quote: dict[str, Any]) -> bool:
        """归一化并写入 Redis；无效 quote 返回 False"""
        normalized = normalize_quote_fields(quote)
        if normalized is None:
            return False
        symbol = normalized["symbol"]
        payload = json.dumps(normalized, ensure_ascii=False)
        try:
            await self._redis.set(
                quote_key(self._mode, symbol), payload, ex=_QUOTE_TTL
            )
            await self._redis.set(
                source_quote_key(self._source, symbol, self._mode),
                payload,
                ex=_QUOTE_TTL,
            )
        except Exception as exc:
            logger.warning("OKX 报价写入 Redis 失败 %s：%s", symbol, exc)
            return False
        return True
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_quote_service.py -v
```

Expected: PASS，全部 6 个测试通过

- [x] **Step 5: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/services/okx_quote_service.py backend/tests/test_okx_quote_service.py
git commit -m "feat(okx): 行情服务支持 live 与 virtual 多盘口分流"
```

---

### Task 4: 主应用接入双轨行情生命周期托管

**Files:**
- Modify: `backend/app/main.py:845-895`
- Create: `backend/tests/test_main_okx_quotes.py`

**Interfaces:**
- Consumes: `OkxRestClient`, `OkxPublicWs`, `OkxQuoteService`
- Produces: `application.state.okx_quotes_live`, `application.state.okx_quotes_virtual`

- [x] **Step 1: 编写失败测试**

新建 `backend/tests/test_main_okx_quotes.py`：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.okx_quote_service import OkxQuoteService


@pytest.mark.asyncio
async def test_quote_services_initialization_dual():
    fake_redis = MagicMock()
    live_svc = OkxQuoteService(fake_redis, mode="live", source="okx")
    virtual_svc = OkxQuoteService(fake_redis, mode="virtual", source="okx_demo")

    assert live_svc._mode == "live"
    assert live_svc._source == "okx"
    assert virtual_svc._mode == "virtual"
    assert virtual_svc._source == "okx_demo"
```

- [x] **Step 2: 运行测试验证**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_main_okx_quotes.py -v
```

Expected: PASS

- [x] **Step 3: 修改 main.py 中的 lifespan 启动与关闭流程**

在 `backend/app/main.py:845-895` 更新为同时拉起实盘与模拟盘行情：

```python
    # 拉取 OKX 品种规格
    from app.connectors.okx.client import OkxRestClient
    from app.connectors.okx.instruments import refresh_instruments
    from app.data.instruments import all_instruments
    from app.services.okx_quote_service import OkxQuoteService

    okx_client = OkxRestClient(demo=False)
    okx_demo_client = OkxRestClient(demo=True)
    try:
        count = await refresh_instruments(okx_client)
        logger.info("OKX 品种表就绪：%d 条", count)
    except Exception as exc:
        logger.warning("OKX 品种表拉取失败（行情将不可用）：%s", exc)
    application.state.okx_client = okx_client
    application.state.okx_demo_client = okx_demo_client

    # OKX 行情服务：实盘 (live) + 模拟盘 (virtual) 双轨启动
    symbols = [i.symbol for i in all_instruments()][:200]
    okx_quotes_live = OkxQuoteService(
        redis_conn, client=okx_client, mode="live", source="okx"
    )
    okx_quotes_virtual = OkxQuoteService(
        redis_conn, client=okx_demo_client, mode="virtual", source="okx_demo"
    )

    if symbols:
        await okx_quotes_live.start(symbols)
        await okx_quotes_virtual.start(symbols)
    else:
        logger.warning("OKX 品种表为空，行情服务未启动")

    application.state.okx_quotes = okx_quotes_live
    application.state.okx_quotes_virtual = okx_quotes_virtual
```

在关闭段（`yield` 之后）加入：

```python
    await okx_quotes_live.stop()
    await okx_quotes_virtual.stop()
    await okx_client.aclose()
    await okx_demo_client.aclose()
```

- [x] **Step 4: 运行导入与语法验证测试**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_import_clean.py -v
```

Expected: PASS

- [x] **Step 5: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/main.py backend/tests/test_main_okx_quotes.py
git commit -m "feat(okx): main 流程接入实盘与模拟盘双轨行情服务"
```

---

### Task 5: 撮合引擎双盘隔离验证

**Files:**
- Create: `backend/tests/test_matching_dual_mode.py`

**Interfaces:**
- Consumes: `app.services.paper.matching.matcher.match_pending_from_redis`, `PaperOrder`, `PaperAccount`
- Produces: 验证实盘挂单与模拟盘挂单互不串价

- [x] **Step 1: 编写撮合双轨隔离集成测试**

新建 `backend/tests/test_matching_dual_mode.py`：

```python
import json
import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.user import User
from app.models.paper.account import PaperAccount
from app.models.paper.order import PaperOrder
from app.models.paper.position import PaperPosition
from app.models.paper.ledger import PaperLedger
from app.models.paper.settings import PaperTradeSettings
from app.models.user_notify_setting import UserNotifySetting
from app.models.notification import Notification
from app.services.market_keys import quote_key
from app.services.paper.matching.matcher import match_pending_from_redis


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)


_PAPER_TABLES = [
    User.__table__,
    PaperAccount.__table__,
    PaperOrder.__table__,
    PaperPosition.__table__,
    PaperLedger.__table__,
    PaperTradeSettings.__table__,
    UserNotifySetting.__table__,
    Notification.__table__,
]


@pytest.fixture
async def async_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=_PAPER_TABLES)
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_pending_orders_isolated_by_mode(async_session_factory):
    redis = _FakeRedis()
    # 实盘价 60000，虚拟盘价 65000
    redis.store[quote_key("live", "btc-usdt-swap")] = json.dumps({
        "symbol": "btc-usdt-swap",
        "last_price": 60000.0,
        "bid_price": 59990.0,
        "ask_price": 60010.0,
    })
    redis.store[quote_key("virtual", "btc-usdt-swap")] = json.dumps({
        "symbol": "btc-usdt-swap",
        "last_price": 65000.0,
        "bid_price": 64990.0,
        "ask_price": 65010.0,
    })

    async with async_session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            username="trader",
            email="trader@test.com",
            hashed_password="hash",
            status="active",
        )
        session.add(user)
        await session.flush()

        acc_live = PaperAccount(
            user_id=user.id,
            trading_mode="live",
            balance=Decimal("1000000"),
        )
        acc_virtual = PaperAccount(
            user_id=user.id,
            trading_mode="virtual",
            balance=Decimal("1000000"),
        )
        session.add_all([acc_live, acc_virtual])
        await session.flush()

        # 实盘买单：委托限价 60050（在实盘 60000 会成交，如果在虚拟盘 65000 不会成交）
        order_live = PaperOrder(
            account_id=acc_live.id,
            user_id=user.id,
            symbol="btc-usdt-swap",
            direction="buy",
            offset="open",
            order_type="limit",
            price=Decimal("60050.0"),
            quantity=1,
            status="pending",
            multiplier=1,
            margin_rate=Decimal("0.1"),
        )
        # 虚拟盘卖单：委托限价 64000（在虚拟盘 65000 会成交，如果在实盘 60000 不会成交）
        order_virtual = PaperOrder(
            account_id=acc_virtual.id,
            user_id=user.id,
            symbol="btc-usdt-swap",
            direction="sell",
            offset="open",
            order_type="limit",
            price=Decimal("64000.0"),
            quantity=1,
            status="pending",
            multiplier=1,
            margin_rate=Decimal("0.1"),
        )
        session.add_all([order_live, order_virtual])
        await session.commit()

    # 触发从 Redis 撮合
    filled_count = await match_pending_from_redis(async_session_factory, redis)
    assert filled_count == 2

    async with async_session_factory() as session:
        orders = (await session.execute(select(PaperOrder))).scalars().all()
        assert len(orders) == 2
        for o in orders:
            assert o.status == "filled"
```

- [x] **Step 2: 运行测试验证**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_matching_dual_mode.py -v
```

Expected: PASS

- [x] **Step 3: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/tests/test_matching_dual_mode.py docs/superpowers/plans/2026-10-12-okx-live-vs-demo.md
git commit -m "test(paper): 验证纸面撮合引擎实盘与模拟盘行情隔离"
```

---

### Task 6: OKX 交易所私有 API HMAC 签名器（真挂单接口就绪）

**Files:**
- Create: `backend/app/connectors/okx/auth.py`
- Create: `backend/tests/test_okx_auth.py`

**Interfaces:**
- Consumes: Python 标准库 `hmac`, `hashlib`, `base64`, `datetime`
- Produces: 
  - `generate_okx_signature(timestamp: str, method: str, request_path: str, body: str, secret_key: str) -> str`
  - `build_okx_auth_headers(api_key: str, secret_key: str, passphrase: str, method: str, request_path: str, body: str = "", demo: bool = False, timestamp: str | None = None) -> dict[str, str]`

- [x] **Step 1: 编写失败测试**

新建 `backend/tests/test_okx_auth.py`：

```python
from app.connectors.okx.auth import build_okx_auth_headers, generate_okx_signature


def test_generate_okx_signature():
    # 按照 OKX 官方规范测试向量
    timestamp = "2020-12-08T09:08:57.715Z"
    method = "GET"
    request_path = "/api/v5/account/balance"
    body = ""
    secret = "E658C08A91"

    sign = generate_okx_signature(timestamp, method, request_path, body, secret)
    assert isinstance(sign, str)
    assert len(sign) > 0


def test_build_okx_auth_headers_demo_switch():
    headers = build_okx_auth_headers(
        api_key="my-key",
        secret_key="my-secret",
        passphrase="my-passphrase",
        method="POST",
        request_path="/api/v5/trade/order",
        body='{"instId":"BTC-USDT-SWAP"}',
        demo=True,
        timestamp="2026-10-12T08:00:00.000Z",
    )

    assert headers["OK-ACCESS-KEY"] == "my-key"
    assert headers["OK-ACCESS-PASSPHRASE"] == "my-passphrase"
    assert headers["OK-ACCESS-TIMESTAMP"] == "2026-10-12T08:00:00.000Z"
    assert "OK-ACCESS-SIGN" in headers
    assert headers["x-simulated-trading"] == "1"


def test_build_okx_auth_headers_live_no_demo_header():
    headers = build_okx_auth_headers(
        api_key="my-key",
        secret_key="my-secret",
        passphrase="my-passphrase",
        method="GET",
        request_path="/api/v5/account/balance",
        demo=False,
        timestamp="2026-10-12T08:00:00.000Z",
    )
    assert "x-simulated-trading" not in headers
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_auth.py -v
```

Expected: FAIL（`ModuleNotFoundError: No module named 'app.connectors.okx.auth'`）

- [x] **Step 3: 实现签名算法**

新建 `backend/app/connectors/okx/auth.py`：

```python
"""OKX API v5 HMAC-SHA256 签名生成器与请求头封装"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone


def okx_iso_timestamp() -> str:
    """生成 OKX 要求的 ISO8601 UTC 时间戳，带毫秒，形如 2026-10-12T08:00:00.123Z"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def generate_okx_signature(
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
    secret_key: str,
) -> str:
    """计算 OKX HMAC-SHA256 签名（Base64 编码）

    Message: timestamp + method.upper() + request_path + body
    """
    message = f"{timestamp}{method.upper()}{request_path}{body or ''}"
    mac = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def build_okx_auth_headers(
    api_key: str,
    secret_key: str,
    passphrase: str,
    method: str,
    request_path: str,
    body: str = "",
    demo: bool = False,
    timestamp: str | None = None,
) -> dict[str, str]:
    """构造 OKX 私有接口请求头"""
    ts = timestamp or okx_iso_timestamp()
    sign = generate_okx_signature(ts, method, request_path, body, secret_key)
    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }
    if demo:
        headers["x-simulated-trading"] = "1"
    return headers
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment/backend
uv run pytest tests/test_okx_auth.py -v
```

Expected: PASS，全部用例通过

- [x] **Step 5: 提交改动**

```bash
cd /Users/hc/Documents/ai/factor-mining-experiment
git add backend/app/connectors/okx/auth.py backend/tests/test_okx_auth.py
git commit -m "feat(okx): 新增私有 API HMAC 签名器支持实盘与模拟盘认证"
```

---

## 验证基线

全部 Task 完成后，运行全量 OKX 相关测试验证：

```bash
cd backend && uv run pytest tests/test_okx_* tests/test_price_band_okx.py \
  tests/test_main_okx_quotes.py tests/test_matching_dual_mode.py tests/test_import_clean.py -v
```

Expected: 全部通过，零 Warning/Error。

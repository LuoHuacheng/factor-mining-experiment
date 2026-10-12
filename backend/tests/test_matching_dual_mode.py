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


@pytest.mark.asyncio
async def test_no_cross_mode_fill_when_other_mode_price_favorable(async_session_factory):
    redis = _FakeRedis()
    # 实盘价格 60000，虚拟盘价格 50000
    redis.store[quote_key("live", "btc-usdt-swap")] = json.dumps({
        "symbol": "btc-usdt-swap",
        "last_price": 60000.0,
        "bid_price": 59990.0,
        "ask_price": 60010.0,
    })
    redis.store[quote_key("virtual", "btc-usdt-swap")] = json.dumps({
        "symbol": "btc-usdt-swap",
        "last_price": 50000.0,
        "bid_price": 49990.0,
        "ask_price": 50010.0,
    })

    async with async_session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            username="trader2",
            email="trader2@test.com",
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
        session.add(acc_live)
        await session.flush()

        # 实盘买单：委托限价 55000
        # 实盘价格 60000 > 55000 不会成交
        # 若串到虚拟盘（50000 < 55000）则会错误成交
        order_live = PaperOrder(
            account_id=acc_live.id,
            user_id=user.id,
            symbol="btc-usdt-swap",
            direction="buy",
            offset="open",
            order_type="limit",
            price=Decimal("55000.0"),
            quantity=1,
            status="pending",
            multiplier=1,
            margin_rate=Decimal("0.1"),
        )
        session.add(order_live)
        await session.commit()

    filled_count = await match_pending_from_redis(async_session_factory, redis)
    assert filled_count == 0

    async with async_session_factory() as session:
        order = (await session.execute(select(PaperOrder))).scalars().first()
        assert order.status == "pending"

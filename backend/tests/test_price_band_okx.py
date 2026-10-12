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

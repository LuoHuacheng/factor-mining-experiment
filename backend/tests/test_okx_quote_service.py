"""OKX 行情写入 Redis —— 键名与既有 market_keys 契约一致"""

import json

import pytest

from app.services.market_keys import quote_key, source_quote_key
from app.services.okx_quote_service import OkxQuoteService


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value


def _quote(symbol="btc-usdt-swap", last=61234.5):
    return {
        "symbol": symbol,
        "name": "BTC",
        "exchange": "OKX",
        "last_price": last,
        "pre_close": 60000.0,
        "bid_price": last,
        "ask_price": last,
        "bid_vol": 1,
        "ask_vol": 1,
        "volume": 10,
        "open_price": last,
        "high_price": last,
        "low_price": last,
        "tick_time": "1791782400000",
        "trade_date": "",
    }


@pytest.mark.asyncio
async def test_write_quote_uses_live_namespace():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    await svc.write_quote(_quote())

    unified = quote_key("live", "btc-usdt-swap")
    source = source_quote_key("okx", "btc-usdt-swap")
    assert unified in redis.store
    assert source in redis.store


@pytest.mark.asyncio
async def test_written_payload_is_normalized():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    await svc.write_quote(_quote())

    payload = json.loads(redis.store[quote_key("live", "btc-usdt-swap")])
    assert payload["symbol"] == "btc-usdt-swap"
    assert payload["last_price"] == 61234.5
    # quote_schema 归一化会补 position 字段
    assert payload["position"] == 0


@pytest.mark.asyncio
async def test_invalid_quote_is_skipped():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis)
    written = await svc.write_quote({"symbol": "", "last_price": 0})
    assert written is False
    assert redis.store == {}


class _FakeClient:
    async def get(self, path, params=None):
        return [
            {"instId": "BTC-USDT-SWAP", "last": "61234.5", "bidPx": "1", "askPx": "2",
             "bidSz": "1", "askSz": "1", "high24h": "2", "low24h": "0.5",
             "vol24h": "10", "volCcy24h": "1", "sodUtc8": "60000", "ts": "1"},
        ]


@pytest.mark.asyncio
async def test_snapshot_once_writes_all_tickers():
    redis = _FakeRedis()
    svc = OkxQuoteService(redis, client=_FakeClient())
    count = await svc.snapshot_once()
    assert count == 1
    assert quote_key("live", "btc-usdt-swap") in redis.store

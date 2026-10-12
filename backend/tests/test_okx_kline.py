"""OKX K 线解析"""

import pytest

from app.connectors.okx import kline as ok


CANDLE = [
    "1791782400000", "61234.5", "61300.0", "61100.0", "61250.0",
    "1234", "75.6", "7560000", "1",
]

FORMING = [
    "1791782460000", "61250.0", "61280.0", "61240.0", "61270.0",
    "12", "0.7", "70000", "0",
]


def test_bar_map_covers_all_periods():
    assert ok.BAR_MAP["1m"] == "1m"
    assert ok.BAR_MAP["5m"] == "5m"
    assert ok.BAR_MAP["15m"] == "15m"
    assert ok.BAR_MAP["30m"] == "30m"
    assert ok.BAR_MAP["60m"] == "1H"
    assert ok.BAR_MAP["4h"] == "4H"
    assert ok.BAR_MAP["1d"] == "1D"


def test_candle_to_bar_maps_ohlcv():
    bar = ok.candle_to_bar(CANDLE, "btc-usdt-swap")
    assert bar is not None
    assert bar["ts"] == 1791782400000
    assert bar["open"] == 61234.5
    assert bar["high"] == 61300.0
    assert bar["low"] == 61100.0
    assert bar["close"] == 61250.0
    assert bar["volume"] == 1234


def test_candle_confirm_flag():
    assert ok.candle_to_bar(CANDLE, "btc-usdt-swap")["confirm"] is True
    assert ok.candle_to_bar(FORMING, "btc-usdt-swap")["confirm"] is False


def test_candle_open_interest_is_zero():
    """OKX candle 不含持仓量；因子层对 has_oi=False 已置零，不得造数"""
    bar = ok.candle_to_bar(CANDLE, "btc-usdt-swap")
    assert bar["open_interest"] == 0


def test_candle_returns_none_on_short_row():
    assert ok.candle_to_bar(CANDLE[:5], "btc-usdt-swap") is None


def test_candle_returns_none_on_bad_number():
    bad = list(CANDLE)
    bad[1] = "abc"
    assert ok.candle_to_bar(bad, "btc-usdt-swap") is None


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append((path, params))
        return self._payload


@pytest.mark.asyncio
async def test_fetch_candles_uses_market_path_and_limit():
    client = _FakeClient([CANDLE, FORMING])
    bars = await ok.fetch_candles(client, "btc-usdt-swap", "1m", limit=300)
    assert len(bars) == 2
    path, params = client.calls[0]
    assert path == "/api/v5/market/candles"
    assert params["instId"] == "BTC-USDT-SWAP"
    assert params["bar"] == "1m"
    assert params["limit"] == "300"


@pytest.mark.asyncio
async def test_fetch_candles_clamps_limit_to_300():
    """/market/candles 上限 300，超出必须夹取"""
    client = _FakeClient([])
    await ok.fetch_candles(client, "btc-usdt-swap", "1m", limit=5000)
    assert client.calls[0][1]["limit"] == "300"


@pytest.mark.asyncio
async def test_fetch_history_candles_clamps_limit_to_100():
    client = _FakeClient([])
    await ok.fetch_history_candles(client, "btc-usdt-swap", "1m", limit=500)
    path, params = client.calls[0]
    assert path == "/api/v5/market/history-candles"
    assert params["limit"] == "100"


@pytest.mark.asyncio
async def test_fetch_candles_unknown_period_raises():
    client = _FakeClient([])
    with pytest.raises(ValueError):
        await ok.fetch_candles(client, "btc-usdt-swap", "7m")

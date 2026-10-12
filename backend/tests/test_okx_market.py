"""OKX 行情解析"""

from app.connectors.okx.market import ticker_to_quote
from app.data.quote_schema import normalize_quote_fields


TICKER_RAW = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "last": "61234.5",
    "lastSz": "1",
    "askPx": "61235.0",
    "askSz": "12",
    "bidPx": "61234.0",
    "bidSz": "8",
    "open24h": "60000.0",
    "high24h": "62000.0",
    "low24h": "59500.0",
    "volCcy24h": "123456.78",
    "vol24h": "12345",
    "ts": "1791782400000",
    "sodUtc0": "60100.0",
    "sodUtc8": "60200.0",
}


def test_ticker_maps_prices():
    q = ticker_to_quote(TICKER_RAW)
    assert q is not None
    assert q["symbol"] == "btc-usdt-swap"
    assert q["last_price"] == 61234.5
    assert q["bid_price"] == 61234.0
    assert q["ask_price"] == 61235.0
    assert q["bid_vol"] == 8
    assert q["ask_vol"] == 12


def test_ticker_uses_sod_utc8_as_pre_close():
    """OKX 的 sodUtc8 是北京时区零点开盘价，用作涨跌幅基准"""
    q = ticker_to_quote(TICKER_RAW)
    assert q["pre_close"] == 60200.0


def test_normalized_quote_computes_change_pct_from_pre_close():
    """涨跌幅由 quote_schema 按 pre_close 算，ticker_to_quote 不重复实现"""
    norm = normalize_quote_fields(ticker_to_quote(TICKER_RAW))
    assert norm is not None
    assert norm["change"] is not None
    expected = (61234.5 - 60200.0) / 60200.0 * 100
    assert round(norm["change_pct"], 4) == round(expected, 4)


def test_ticker_falls_back_to_sod_utc0_when_utc8_missing():
    raw = {k: v for k, v in TICKER_RAW.items() if k != "sodUtc8"}
    q = ticker_to_quote(raw)
    assert q["pre_close"] == 60100.0


def test_ticker_survives_missing_pre_close():
    raw = {k: v for k, v in TICKER_RAW.items() if k not in ("sodUtc8", "sodUtc0")}
    q = ticker_to_quote(raw)
    assert q is not None
    assert q["pre_close"] is None


def test_ticker_returns_none_on_bad_last():
    raw = {**TICKER_RAW, "last": "0"}
    assert ticker_to_quote(raw) is None


def test_ticker_returns_none_without_inst_id():
    raw = {k: v for k, v in TICKER_RAW.items() if k != "instId"}
    assert ticker_to_quote(raw) is None


def test_quote_passes_normalize_contract():
    """输出必须能被既有 quote_schema 归一化（下游 K 线/WS 契约）"""
    q = ticker_to_quote(TICKER_RAW)
    norm = normalize_quote_fields(q)
    assert norm is not None
    assert norm["symbol"] == "btc-usdt-swap"
    assert norm["last_price"] == 61234.5
    assert norm["position"] == 0

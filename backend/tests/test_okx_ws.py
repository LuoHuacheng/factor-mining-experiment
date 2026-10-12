"""OKX 公开 WS 订阅与消息解析"""

from app.connectors.okx import ws as ok


def test_subscribe_args_shape():
    args = ok.subscribe_args(["btc-usdt-swap", "eth-usdt-swap"], ["tickers"])
    assert args == [
        {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        {"channel": "tickers", "instId": "ETH-USDT-SWAP"},
    ]


def test_subscribe_args_multi_channel():
    args = ok.subscribe_args(["btc-usdt-swap"], ["tickers", "books5"])
    assert len(args) == 2
    assert {a["channel"] for a in args} == {"tickers", "books5"}


def test_subscribe_args_empty_symbols():
    assert ok.subscribe_args([], ["tickers"]) == []


def test_parse_ticker_message():
    msg = {
        "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        "data": [{"instId": "BTC-USDT-SWAP", "last": "61234.5"}],
    }
    parsed = ok.parse_ws_message(msg)
    assert parsed is not None
    channel, payload = parsed
    assert channel == "tickers"
    assert payload["instId"] == "BTC-USDT-SWAP"


def test_parse_books5_message():
    msg = {
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{"asks": [["61235", "1", "0", "1"]], "bids": [["61234", "2", "0", "1"]], "ts": "1"}],
    }
    parsed = ok.parse_ws_message(msg)
    assert parsed is not None
    assert parsed[0] == "books5"


def test_parse_ignores_event_and_error_frames():
    assert ok.parse_ws_message({"event": "subscribe", "arg": {"channel": "tickers"}}) is None
    assert ok.parse_ws_message({"event": "error", "code": "60012", "msg": "bad"}) is None


def test_parse_ignores_frame_without_data():
    assert ok.parse_ws_message({"arg": {"channel": "tickers"}, "data": []}) is None


def test_parse_ignores_frame_without_arg():
    assert ok.parse_ws_message({"data": [{"instId": "X"}]}) is None

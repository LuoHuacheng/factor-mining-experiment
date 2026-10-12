from app.connectors.okx.auth import (
    build_okx_auth_headers,
    generate_okx_signature,
    okx_iso_timestamp,
)


def test_okx_iso_timestamp_format():
    ts = okx_iso_timestamp()
    assert isinstance(ts, str)
    assert ts.endswith("Z")
    assert "T" in ts
    assert len(ts) == 24


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
    assert headers["Content-Type"] == "application/json"


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
    assert headers["OK-ACCESS-KEY"] == "my-key"
    assert headers["OK-ACCESS-PASSPHRASE"] == "my-passphrase"
    assert headers["OK-ACCESS-TIMESTAMP"] == "2026-10-12T08:00:00.000Z"
    assert "OK-ACCESS-SIGN" in headers
    assert headers["Content-Type"] == "application/json"


def test_build_okx_auth_headers_auto_timestamp():
    headers = build_okx_auth_headers(
        api_key="my-key",
        secret_key="my-secret",
        passphrase="my-passphrase",
        method="GET",
        request_path="/api/v5/account/balance",
    )
    assert headers["OK-ACCESS-TIMESTAMP"].endswith("Z")
    assert len(headers["OK-ACCESS-TIMESTAMP"]) == 24

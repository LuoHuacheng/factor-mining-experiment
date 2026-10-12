"""OKX instruments 解析与拉取"""

import pytest

from app.connectors.okx import instruments as oi
from app.connectors.okx.client import OkxApiError, OkxRestClient


SWAP_RAW = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "uly": "BTC-USDT",
    "instFamily": "BTC-USDT",
    "baseCcy": "",
    "quoteCcy": "",
    "settleCcy": "USDT",
    "ctVal": "0.01",
    "ctMult": "1",
    "ctValCcy": "BTC",
    "tickSz": "0.1",
    "lotSz": "0.01",
    "minSz": "0.01",
    "state": "live",
}

SPOT_RAW = {
    "instType": "SPOT",
    "instId": "BTC-USDT",
    "baseCcy": "BTC",
    "quoteCcy": "USDT",
    "tickSz": "0.1",
    "lotSz": "0.00000001",
    "minSz": "0.00001",
    "state": "live",
}


def test_parse_swap_maps_contract_value_from_ct_val():
    item = oi.parse_instrument(SWAP_RAW)
    assert item is not None
    assert item.symbol == "btc-usdt-swap"
    assert item.code == "BTC"
    assert item.tick_size == 0.1
    assert item.contract_value == 0.01
    assert item.min_qty == 0.01
    assert item.lot_size == 0.01
    assert item.quote_ccy == "USDT"


def test_parse_spot_uses_base_and_quote_ccy():
    item = oi.parse_instrument(SPOT_RAW)
    assert item is not None
    assert item.symbol == "btc-usdt"
    assert item.code == "BTC"
    assert item.contract_value == 1.0
    assert item.quote_ccy == "USDT"


def test_parse_skips_non_live():
    raw = {**SWAP_RAW, "state": "suspend"}
    assert oi.parse_instrument(raw) is None


def test_parse_skips_usdc_quoted():
    """只保留 USDT 计价，避免同名品种跨计价币冲突"""
    raw = {**SWAP_RAW, "instId": "BTC-USDC-SWAP", "settleCcy": "USDC"}
    assert oi.parse_instrument(raw) is None


def test_parse_returns_none_on_bad_numbers():
    raw = {**SWAP_RAW, "tickSz": "abc"}
    assert oi.parse_instrument(raw) is None


def test_parse_returns_none_without_inst_id():
    raw = {k: v for k, v in SWAP_RAW.items() if k != "instId"}
    assert oi.parse_instrument(raw) is None


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def get(self, path, params=None):
        self.calls.append((path, params))
        return self._payload


@pytest.mark.asyncio
async def test_fetch_instruments_requests_swap_type():
    client = _FakeClient([SWAP_RAW])
    items = await oi.fetch_instruments(client, "SWAP")
    assert len(items) == 1
    assert client.calls[0][0] == "/api/v5/public/instruments"
    assert client.calls[0][1]["instType"] == "SWAP"


@pytest.mark.asyncio
async def test_refresh_instruments_populates_module_table():
    from app.data import instruments as inst

    client = _FakeClient([SWAP_RAW, SPOT_RAW])
    count = await oi.refresh_instruments(client)
    assert count == 2
    assert inst.get_code_for_symbol("btc-usdt-swap") == "BTC"
    assert inst.get_master_symbol_for_code("BTC") == "btc-usdt-swap"


def test_api_error_carries_code_and_msg():
    err = OkxApiError("51001", "Instrument ID does not exist")
    assert err.code == "51001"
    assert "does not exist" in err.msg
    assert "51001" in str(err)

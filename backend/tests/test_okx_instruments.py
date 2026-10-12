"""OKX 品种查找表 —— 7 个兼容查询函数 + Instrument 模型"""

from app.data import instruments as inst


def _seed():
    inst.set_instruments([
        inst.Instrument(
            symbol="btc-usdt-swap", code="BTC", name="BTC/USDT 永续",
            exchange="OKX", tick_size=0.1, contract_value=0.01,
            min_qty=0.01, lot_size=0.01, quote_ccy="USDT",
        ),
        inst.Instrument(
            symbol="eth-usdt-swap", code="ETH", name="ETH/USDT 永续",
            exchange="OKX", tick_size=0.01, contract_value=0.1,
            min_qty=0.1, lot_size=0.1, quote_ccy="USDT",
        ),
        inst.Instrument(
            symbol="btc-usdt", code="BTC", name="BTC/USDT 现货",
            exchange="OKX", tick_size=0.1, contract_value=1.0,
            min_qty=0.00001, lot_size=0.00000001, quote_ccy="USDT",
        ),
    ])


def test_code_from_full_symbol():
    _seed()
    assert inst.get_code_for_symbol("btc-usdt-swap") == "BTC"


def test_code_from_bare_code():
    _seed()
    assert inst.get_code_for_symbol("btc") == "BTC"


def test_code_unknown_returns_empty():
    _seed()
    assert inst.get_code_for_symbol("nope-usdt") == ""


def test_master_symbol_prefers_swap():
    """永续优先于现货：OKX 主战场是 SWAP"""
    _seed()
    assert inst.get_master_symbol_for_code("BTC") == "btc-usdt-swap"


def test_product_name_is_code():
    _seed()
    assert inst.get_product_name("BTC") == "BTC"


def test_contract_name_is_display_name():
    _seed()
    assert inst.get_contract_name("btc-usdt-swap") == "BTC/USDT 永续"


def test_contract_name_unknown_symbol_falls_back_to_symbol():
    _seed()
    assert inst.get_contract_name("zzz-usdt") == "zzz-usdt"


def test_tick_size_and_decimal_places():
    _seed()
    assert inst.get_tick_size("BTC") == 0.1
    assert inst.get_decimal_places("BTC") == 1
    assert inst.get_decimal_places("ETH") == 2


def test_decimal_places_for_whole_number_tick():
    inst.set_instruments([
        inst.Instrument(
            symbol="x-usdt-swap", code="X", name="X", exchange="OKX",
            tick_size=1.0, contract_value=1.0, min_qty=1.0,
            lot_size=1.0, quote_ccy="USDT",
        ),
    ])
    assert inst.get_decimal_places("X") == 0


def test_round_by_tick():
    _seed()
    assert inst.round_by_tick(123.456, "BTC") == 123.5
    assert inst.round_by_tick(123.44, "ETH") == 123.44


def test_unknown_code_uses_default_tick():
    _seed()
    assert inst.get_tick_size("ZZZ") == inst.DEFAULT_TICK_SIZE


def test_get_instrument_returns_none_for_unknown():
    _seed()
    assert inst.get_instrument("nope") is None
    assert inst.get_instrument("btc-usdt-swap").contract_value == 0.01


def test_set_instruments_replaces_previous():
    _seed()
    inst.set_instruments([])
    assert inst.all_instruments() == []
    assert inst.get_code_for_symbol("btc-usdt-swap") == ""

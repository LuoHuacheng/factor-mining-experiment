"""OKX 品种定义与查找表 —— 顶替原期货合约表

对外保持与原 contracts.py 同名的 7 个查询函数，使 98 处调用点无需改动。

主力口径：同 code 下优先 SWAP（永续），其次 SPOT —— OKX 主战场是永续，
且永续无到期日，不需要换月逻辑。

数据由 app.connectors.okx.instruments 在启动时经
GET /api/v5/public/instruments 拉取后调用 set_instruments 灌入；
本模块只负责存储与查询，不做任何网络访问。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

DEFAULT_TICK_SIZE = 0.01

EXCHANGE_OKX = "OKX"


@dataclass(frozen=True)
class Instrument:
    """单个可交易标的

    symbol 为内部规范符号（小写），如 btc-usdt-swap；
    contract_value 对应 OKX 的 ctVal（每张合约面值，现货恒为 1.0）。
    """

    symbol: str
    code: str
    name: str
    exchange: str
    tick_size: float
    contract_value: float
    min_qty: float
    lot_size: float
    quote_ccy: str


_INSTRUMENTS: list[Instrument] = []
_BY_SYMBOL: dict[str, Instrument] = {}
_BY_CODE: dict[str, list[Instrument]] = {}
_MASTER_BY_CODE: dict[str, str] = {}
ALL_CONTRACTS: list[dict[str, Any]] = []


def _kind_rank(symbol: str) -> int:
    """symbol 的品种类型权重：永续 0，现货 1，其它 2"""
    if symbol.endswith("-swap"):
        return 0
    if symbol.count("-") == 1:
        return 1
    return 2


def set_instruments(items: Iterable[Instrument]) -> None:
    """整体替换品种表并重建全部查找索引"""
    global _INSTRUMENTS, _BY_SYMBOL, _BY_CODE, _MASTER_BY_CODE, ALL_CONTRACTS

    _INSTRUMENTS = list(items)
    _BY_SYMBOL = {i.symbol: i for i in _INSTRUMENTS}

    by_code: dict[str, list[Instrument]] = {}
    for item in _INSTRUMENTS:
        by_code.setdefault(item.code, []).append(item)
    _BY_CODE = by_code

    _MASTER_BY_CODE = {
        code: min(rows, key=lambda i: (_kind_rank(i.symbol), i.symbol)).symbol
        for code, rows in by_code.items()
    }

    ALL_CONTRACTS.clear()
    ALL_CONTRACTS.extend([
        {
            "symbol": i.symbol,
            "code": i.code,
            "name": i.name,
            "exchange": i.exchange,
            "tick_size": i.tick_size,
            "contract_value": i.contract_value,
            "min_qty": i.min_qty,
            "lot_size": i.lot_size,
            "quote_ccy": i.quote_ccy,
        }
        for i in _INSTRUMENTS
    ])


def all_instruments() -> list[Instrument]:
    """当前全部标的"""
    return list(_INSTRUMENTS)


def get_instrument(symbol: str) -> Instrument | None:
    """按 symbol 精确取标的，未找到返回 None"""
    return _BY_SYMBOL.get(str(symbol or "").strip().lower())


def get_code_for_symbol(symbol: str) -> str:
    """symbol → 品种 code（大写）。支持全符号、纯 code、未知返回空串"""
    s = str(symbol or "").strip().lower()
    if not s:
        return ""
    hit = _BY_SYMBOL.get(s)
    if hit is not None:
        return hit.code
    # 纯 code 形式（如 btc / BTC）
    rows = _BY_CODE.get(s.upper())
    if rows:
        return rows[0].code
    # 前缀兜底：btc-anything → BTC
    head = s.split("-")[0].upper()
    if head in _BY_CODE:
        return head
    return ""


def get_master_symbol_for_code(code: str) -> str:
    """品种 code → 主力 symbol（永续优先）。未知时原样返回入参"""
    c = str(code or "").strip().upper()
    master = _MASTER_BY_CODE.get(c)
    if master:
        return master
    return str(code or "")


def get_product_name(code: str) -> str:
    """品种 code → 展示名（即 code 本身，OKX 无中文品种名）"""
    c = str(code or "").strip().upper()
    if c in _BY_CODE:
        return c
    return c


def get_contract_name(symbol: str) -> str:
    """symbol → 展示名；未知则原样返回 symbol"""
    s = str(symbol or "").strip().lower()
    hit = _BY_SYMBOL.get(s)
    if hit is not None:
        return hit.name
    return str(symbol or "")


def get_tick_size(code: str) -> float:
    """品种最小变动价位；未知返回 DEFAULT_TICK_SIZE"""
    rows = _BY_CODE.get(str(code or "").strip().upper())
    if not rows:
        return DEFAULT_TICK_SIZE
    return min(r.tick_size for r in rows)


def get_decimal_places(code: str) -> int:
    """按 tick_size 推算价格显示小数位"""
    tick = get_tick_size(code)
    if tick >= 1:
        return 0
    text = f"{tick:.10f}".rstrip("0").split(".")
    return len(text[1]) if len(text) > 1 else 0


def round_by_tick(price: float, code: str) -> float:
    """按品种最小变动价位取整价格"""
    tick = get_tick_size(code)
    if tick <= 0:
        return float(price)
    return round(round(float(price) / tick) * tick, 10)


extract_product_code = get_code_for_symbol


def get_product_spec(symbol_or_code: str) -> dict[str, Any]:
    """获取品种规格字典（兼容原 product_specs 契约）"""
    code = get_code_for_symbol(symbol_or_code) or str(symbol_or_code or "").strip().upper()
    inst = get_instrument(symbol_or_code)
    if inst is None:
        master = get_master_symbol_for_code(code)
        inst = get_instrument(master)
    ct_val = inst.contract_value if inst else 1.0
    name = inst.name if inst else code
    return {
        "code": code,
        "name": name,
        "multiplier": ct_val,
        "margin_rate": 0.1,  # 默认 10% 保证金
        "fee_mode": "rate",
        "open_fee": 0.0005,  # 5 bps
        "close_fee": 0.0005,
    }


def list_all_product_specs() -> list[dict[str, Any]]:
    """列出全部品种规格"""
    codes = sorted(_BY_CODE.keys())
    return [get_product_spec(c) for c in codes]


CRYPTO_KEYWORDS: dict[str, list[str]] = {
    "BTC": ["比特币", "BTC", "Bitcoin"],
    "ETH": ["以太坊", "ETH", "Ethereum"],
    "SOL": ["Solana", "SOL"],
    "DOGE": ["狗狗币", "DOGE", "Dogecoin"],
    "XRP": ["瑞波币", "XRP", "Ripple"],
}


def extract_base_symbol(symbol: str) -> str:
    """提取基础 symbol (如 btc-usdt-swap -> btc)"""
    code = get_code_for_symbol(symbol)
    if code:
        return code.lower()
    return symbol.split("-")[0].lower() if symbol else ""


def get_primary_keyword(base: str) -> str:
    """获取基础 symbol 的主搜索词"""
    b = str(base or "").strip().upper()
    kws = CRYPTO_KEYWORDS.get(b)
    if kws:
        return kws[0]
    return b


def find_matching_symbols(text: str) -> list[str]:
    """从文本中匹配包含的币种代码"""
    matches: list[str] = []
    text_upper = text.upper()
    for code, kws in CRYPTO_KEYWORDS.items():
        for kw in kws:
            if kw.upper() in text_upper:
                matches.append(code.lower())
                break
    return matches


MOCK_BASE_PRICES: dict[str, float] = {
    "btc-usdt-swap": 60000.0,
    "eth-usdt-swap": 3000.0,
    "sol-usdt-swap": 150.0,
    "doge-usdt-swap": 0.15,
    "xrp-usdt-swap": 0.6,
    "btc-usdt": 60000.0,
    "eth-usdt": 3000.0,
    "sol-usdt": 150.0,
    "doge-usdt": 0.15,
    "xrp-usdt": 0.6,
    "btc": 60000.0,
    "eth": 3000.0,
    "sol": 150.0,
    "doge": 0.15,
    "xrp": 0.6,
}


def get_mock_base_price(symbol: str) -> float:
    """获取合约的模拟基准价格，未定义的品种返回默认值 100.0"""
    s = str(symbol or "").strip().lower()
    if s in MOCK_BASE_PRICES:
        return MOCK_BASE_PRICES[s]
    code = extract_base_symbol(s)
    return MOCK_BASE_PRICES.get(code, 100.0)


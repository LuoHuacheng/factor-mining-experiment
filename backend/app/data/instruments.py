"""OKX 品种定义与查找表 —— 顶替原期货合约表（app.data.contracts）

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


def _kind_rank(symbol: str) -> int:
    """symbol 的品种类型权重：永续 0，现货 1，其它 2"""
    if symbol.endswith("-swap"):
        return 0
    if symbol.count("-") == 1:
        return 1
    return 2


def set_instruments(items: Iterable[Instrument]) -> None:
    """整体替换品种表并重建全部查找索引"""
    global _INSTRUMENTS, _BY_SYMBOL, _BY_CODE, _MASTER_BY_CODE

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

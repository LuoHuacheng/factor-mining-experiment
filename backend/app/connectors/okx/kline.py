"""OKX K 线 REST —— 近期 + 历史

OKX candle 行格式（全部为字符串）：
  [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
confirm="1" 表示该根已收盘，"0" 为形成中。

两个端点限额不同，必须分别夹取：
- /api/v5/market/candles       最近数据，单次上限 300
- /api/v5/market/history-candles 更早数据，单次上限 100
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("app.okx.kline")

_CANDLES_PATH = "/api/v5/market/candles"
_HISTORY_CANDLES_PATH = "/api/v5/market/history-candles"

_CANDLES_MAX = 300
_HISTORY_MAX = 100

# 内部周期名 → OKX bar 参数
BAR_MAP: dict[str, str] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "1w": "1W",
}

_CANDLE_FIELDS = 9


def _f(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def candle_to_bar(raw: list[Any], symbol: str) -> dict[str, Any] | None:
    """OKX candle 行 → bar dict；不可用返回 None"""
    if not isinstance(raw, list) or len(raw) < _CANDLE_FIELDS:
        return None

    ts = _f(raw[0])
    o = _f(raw[1])
    h = _f(raw[2])
    low = _f(raw[3])
    c = _f(raw[4])
    vol = _f(raw[5])
    if None in (ts, o, h, low, c, vol):
        return None

    return {
        "symbol": str(symbol or "").lower(),
        "ts": int(ts),
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "volume": int(vol),
        # OKX candle 不提供持仓量；因子层对 has_oi=False 整体置零，
        # 这里恒填 0 以保持字段存在（不造伪信号）
        "open_interest": 0,
        "confirm": str(raw[8]) == "1",
    }


def _resolve_bar(bar: str) -> str:
    okx_bar = BAR_MAP.get(str(bar or "").strip())
    if okx_bar is None:
        raise ValueError(f"不支持的 K 线周期：{bar}")
    return okx_bar


def _params(symbol: str, okx_bar: str, limit: int, after: int | None) -> dict[str, str]:
    params = {
        "instId": str(symbol or "").strip().upper(),
        "bar": okx_bar,
        "limit": str(limit),
    }
    if after is not None:
        params["after"] = str(int(after))
    return params


async def fetch_candles(
    client: Any,
    symbol: str,
    bar: str = "1m",
    limit: int = _CANDLES_MAX,
    after: int | None = None,
) -> list[dict[str, Any]]:
    """拉取近期 K 线（单次上限 300）"""
    okx_bar = _resolve_bar(bar)
    capped = max(1, min(int(limit), _CANDLES_MAX))
    rows = await client.get(_CANDLES_PATH, _params(symbol, okx_bar, capped, after))
    return [
        parsed
        for raw in rows
        if isinstance(raw, list) and (parsed := candle_to_bar(raw, symbol)) is not None
    ]


async def fetch_history_candles(
    client: Any,
    symbol: str,
    bar: str = "1m",
    limit: int = _HISTORY_MAX,
    after: int | None = None,
) -> list[dict[str, Any]]:
    """拉取更早的 K 线（单次上限 100，配合 after 向前翻页）"""
    okx_bar = _resolve_bar(bar)
    capped = max(1, min(int(limit), _HISTORY_MAX))
    rows = await client.get(
        _HISTORY_CANDLES_PATH, _params(symbol, okx_bar, capped, after)
    )
    return [
        parsed
        for raw in rows
        if isinstance(raw, list) and (parsed := candle_to_bar(raw, symbol)) is not None
    ]

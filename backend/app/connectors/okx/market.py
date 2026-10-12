"""OKX 行情 REST —— ticker 快照

输出统一 quote dict，字段集必须能被 app.data.quote_schema.normalize_quote_fields
接受（下游 K 线/WS 依赖同一契约）。

与期货的关键差异：
- 无 settlement_price / position（持仓量）：OKX ticker 不含，永续持仓量需
  另调 /api/v5/public/open-interest；本 Task 不取，quote_schema 会填 0。
- 涨跌幅基准用 sodUtc8（北京时区零点价），其次 sodUtc0，都没有则置 None
  （绝不用 last 充当基准，避免涨跌幅恒为 0）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("qihuo.okx.market")

_TICKERS_PATH = "/api/v5/market/tickers"

EXCHANGE_OKX = "OKX"


def _f(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value


def _i(raw: Any) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def ticker_to_quote(raw: dict[str, Any]) -> dict[str, Any] | None:
    """OKX ticker → 统一 quote dict；不可用返回 None"""
    inst_id = str(raw.get("instId") or "").strip()
    if not inst_id:
        return None

    last = _f(raw.get("last"))
    if last is None or last <= 0:
        return None

    symbol = inst_id.lower()
    code = symbol.split("-")[0].upper()

    # 基准价：北京零点优先，其次 UTC 零点
    pre = _f(raw.get("sodUtc8"))
    if pre is None or pre <= 0:
        pre = _f(raw.get("sodUtc0"))
    if pre is not None and pre <= 0:
        pre = None

    return {
        "symbol": symbol,
        "name": code,
        "exchange": EXCHANGE_OKX,
        "last_price": last,
        "open_price": pre if pre is not None else last,
        "high_price": _f(raw.get("high24h")) or last,
        "low_price": _f(raw.get("low24h")) or last,
        "pre_close": pre,
        "bid_price": _f(raw.get("bidPx")) or last,
        "ask_price": _f(raw.get("askPx")) or last,
        "bid_vol": _i(raw.get("bidSz")),
        "ask_vol": _i(raw.get("askSz")),
        "volume": _i(raw.get("vol24h")),
        "turnover": _f(raw.get("volCcy24h")),
        "tick_time": str(raw.get("ts") or ""),
        "trade_date": "",
    }


async def fetch_tickers(client: Any, inst_type: str = "SWAP") -> list[dict[str, Any]]:
    """拉取全市场 ticker 快照（一次请求覆盖全部品种）"""
    rows = await client.get(_TICKERS_PATH, {"instType": inst_type})
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        quote = ticker_to_quote(raw)
        if quote is not None:
            out.append(quote)
    return out

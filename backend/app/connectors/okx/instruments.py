"""从 OKX 拉取品种规格并灌入 app.data.instruments 查找表"""

from __future__ import annotations

import logging
from typing import Any

from app.data.instruments import EXCHANGE_OKX, Instrument, set_instruments

logger = logging.getLogger("qihuo.okx.instruments")

_INSTRUMENTS_PATH = "/api/v5/public/instruments"

# 只保留 USDT 计价：同名 base 在 USDC/USD 下会与 USDT 行冲突，
# 且本项目账户/计价统一 USDT
_KEEP_QUOTE = "USDT"

# 只保留可交易状态
_LIVE_STATE = "live"


def _f(raw: Any) -> float | None:
    """安全转 float，失败返回 None"""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _quote_ccy(raw: dict[str, Any]) -> str:
    """永续取 settleCcy，现货取 quoteCcy"""
    return str(raw.get("settleCcy") or raw.get("quoteCcy") or "").upper()


def parse_instrument(raw: dict[str, Any]) -> Instrument | None:
    """OKX instruments 条目 → Instrument；不可用返回 None"""
    inst_id = str(raw.get("instId") or "").strip()
    if not inst_id:
        return None
    if str(raw.get("state") or "") != _LIVE_STATE:
        return None

    quote = _quote_ccy(raw)
    if quote != _KEEP_QUOTE:
        return None

    symbol = inst_id.lower()
    # code 取第一段：btc-usdt-swap → BTC
    code = symbol.split("-")[0].upper()
    if not code:
        return None

    tick = _f(raw.get("tickSz"))
    lot = _f(raw.get("lotSz"))
    min_sz = _f(raw.get("minSz"))
    if tick is None or tick <= 0 or lot is None or min_sz is None:
        return None

    is_swap = symbol.endswith("-swap")
    if is_swap:
        ct_val = _f(raw.get("ctVal"))
        if ct_val is None or ct_val <= 0:
            return None
        kind = "永续"
    else:
        ct_val = 1.0
        kind = "现货"

    return Instrument(
        symbol=symbol,
        code=code,
        name=f"{code}/{quote} {kind}",
        exchange=EXCHANGE_OKX,
        tick_size=tick,
        contract_value=ct_val,
        min_qty=min_sz,
        lot_size=lot,
        quote_ccy=quote,
    )


async def fetch_instruments(
    client: Any,
    inst_type: str = "SWAP",
) -> list[Instrument]:
    """拉取指定 instType 的品种清单（只读公开接口）"""
    rows = await client.get(_INSTRUMENTS_PATH, {"instType": inst_type})
    out: list[Instrument] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = parse_instrument(raw)
        if item is not None:
            out.append(item)
    return out


async def refresh_instruments(client: Any) -> int:
    """拉取 SWAP + SPOT 并整体替换查找表，返回写入条数"""
    swap = await fetch_instruments(client, "SWAP")
    spot = await fetch_instruments(client, "SPOT")
    merged = {i.symbol: i for i in (*swap, *spot)}
    set_instruments(list(merged.values()))
    logger.info(
        "OKX 品种表已更新：SWAP %d 条，SPOT %d 条，去重后 %d 条",
        len(swap), len(spot), len(merged),
    )
    return len(merged)

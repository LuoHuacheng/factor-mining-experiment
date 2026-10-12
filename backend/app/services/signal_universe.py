"""信号扫描宇宙 —— 全部主力标的"""

from __future__ import annotations

import logging
from typing import Any

from app.data.instruments import (
    all_instruments,
    get_contract_name,
    get_master_symbol_for_code,
    get_product_name,
)

logger = logging.getLogger("app.signal_universe")


async def list_all_master_symbols(redis_conn: Any = None) -> list[dict[str, str]]:
    """列出全部主力标的。

    返回 [{product_code, symbol, name, product_name, contract_name}]
    """
    instruments = all_instruments()
    codes = sorted({inst.code for inst in instruments})
    items: list[dict[str, str]] = []
    for code_u in codes:
        symbol = get_master_symbol_for_code(code_u)
        product_name = get_product_name(code_u)
        contract_name = get_contract_name(symbol)
        items.append(
            {
                "product_code": code_u,
                "symbol": symbol,
                "name": product_name,
                "product_name": product_name,
                "contract_name": contract_name,
            }
        )
    return items

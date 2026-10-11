"""模拟交易工具分发"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.tools.paper.exec import (
    tool_paper_cancel_order,
    tool_paper_close_position,
    tool_paper_get_account,
    tool_paper_list_orders,
    tool_paper_list_positions,
    tool_paper_open_long,
    tool_paper_open_short,
    tool_paper_place_limit,
)

_PAPER_NAMES = frozenset(
    {
        "paper_open_long",
        "paper_open_short",
        "paper_close_position",
        "paper_place_limit",
        "paper_cancel_order",
        "paper_list_positions",
        "paper_list_orders",
        "paper_get_account",
    }
)


def is_paper_tool(name: str) -> bool:
    """是否模拟交易工具"""
    return name in _PAPER_NAMES


def _to_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def dispatch_paper_tool(
    name: str,
    arguments: dict[str, Any],
    session: AsyncSession | None,
    user_id: str | None,
    redis_conn: object | None,
) -> str | None:
    """执行模拟交易工具；非 paper 工具返回 None"""
    if name == "paper_open_long":
        return _to_json(
            await tool_paper_open_long(arguments, session, user_id, redis_conn)
        )
    if name == "paper_open_short":
        return _to_json(
            await tool_paper_open_short(arguments, session, user_id, redis_conn)
        )
    if name == "paper_close_position":
        return _to_json(
            await tool_paper_close_position(
                arguments, session, user_id, redis_conn
            )
        )
    if name == "paper_place_limit":
        return _to_json(
            await tool_paper_place_limit(arguments, session, user_id, redis_conn)
        )
    if name == "paper_cancel_order":
        return _to_json(
            await tool_paper_cancel_order(arguments, session, user_id)
        )
    if name == "paper_list_positions":
        return _to_json(await tool_paper_list_positions(session, user_id))
    if name == "paper_list_orders":
        return _to_json(
            await tool_paper_list_orders(arguments, session, user_id)
        )
    if name == "paper_get_account":
        return _to_json(await tool_paper_get_account(session, user_id))
    return None

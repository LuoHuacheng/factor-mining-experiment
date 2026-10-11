"""AI 工具箱 API —— 列表、启用开关、自由交易"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.models.user import User
from app.services.ai.tools.catalog import list_tool_catalog
from app.services.ai.tools.preferences import (
    get_disabled_tools,
    get_free_trade_tools,
    set_tool_enabled,
    set_tool_free_trade,
)

router = APIRouter(prefix="/api/ai/tools", tags=["AI 工具箱"])


class ToolEnableBody(BaseModel):
    """启用开关请求体"""

    enabled: bool = Field(..., description="true=启用，false=禁用")


class ToolFreeTradeBody(BaseModel):
    """自由交易开关请求体"""

    free_trade: bool = Field(
        ...,
        description="true=跳过确认直接执行，false=仍需确认",
    )


@router.get("")
async def list_tools(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """列出内置工具（中文名/简介 + 启用 + 自由交易）"""
    redis_conn = getattr(request.app.state, "redis", None)
    uid = str(current_user.id)
    disabled = await get_disabled_tools(redis_conn, uid)
    free_trade = await get_free_trade_tools(redis_conn, uid)
    items = []
    for item in list_tool_catalog():
        name = item["name"]
        requires = bool(item["requires_confirmation"])
        items.append(
            {
                **item,
                "enabled": name not in disabled,
                # 仅需确认的工具可开自由交易；查询类恒为 false
                "free_trade": requires and name in free_trade,
                "supports_free_trade": requires,
            }
        )
    items.sort(key=lambda x: (x["category"], x["name_zh"]))
    return {
        "total": len(items),
        "disabled_count": len(disabled),
        "free_trade_count": len(free_trade),
        "items": items,
    }


@router.put("/{tool_name}/enabled")
async def update_tool_enabled(
    tool_name: str,
    body: ToolEnableBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """启用/禁用指定工具；关闭后 AI 不可见也不可执行"""
    redis_conn = getattr(request.app.state, "redis", None)
    if redis_conn is None:
        raise HTTPException(status_code=503, detail="Redis 不可用，无法保存开关")
    try:
        disabled = await set_tool_enabled(
            redis_conn,
            str(current_user.id),
            tool_name,
            body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "name": tool_name,
        "enabled": body.enabled,
        "disabled_tools": sorted(disabled),
    }


@router.put("/{tool_name}/free-trade")
async def update_tool_free_trade(
    tool_name: str,
    body: ToolFreeTradeBody,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    """自由交易：开启后该写操作无需确认直接执行"""
    redis_conn = getattr(request.app.state, "redis", None)
    if redis_conn is None:
        raise HTTPException(status_code=503, detail="Redis 不可用，无法保存开关")
    try:
        free_set = await set_tool_free_trade(
            redis_conn,
            str(current_user.id),
            tool_name,
            body.free_trade,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "name": tool_name,
        "free_trade": body.free_trade,
        "free_trade_tools": sorted(free_set),
    }

"""统一聊天网关 —— ReAct 多轮工具编排入口

工具定义/执行见 tools/；编排辅助见 tool_loop。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_model import AIModel
from app.models.ai_provider import AIProvider
from app.services.ai.providers.base import StreamEvent
from app.services.ai.providers.factory import create_provider
from app.services.ai.tools.loop import (
    build_assistant_tool_call_message,
    build_tool_result_message,
    execute_tools_parallel,
    strip_images,
)
from app.services.ai.tools import (
    execute_tool,
    get_tool_definitions,
    get_tool_map,
    load_skill_tools,
)
from app.services.ai.tools.preferences import get_enabled_tool_definitions
from app.services.ai.tools.stream_exec import is_streamable_tool, run_streamable_tool
from app.services.crypto import decrypt

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


async def chat_stream(
    session: AsyncSession,
    user_id: str,
    model_id: str,
    messages: list[dict[str, Any]],
    redis_conn: Any | None = None,
    indicator_config: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """统一流式聊天入口（支持多工具编排、重试、确认、ReAct）。

    indicator_config: 前端当前图表指标设置，供 get/update_indicator_settings 使用。
    """
    # 可变副本：同轮 update 后后续 get 能读到最新
    live_indicator_config: dict[str, Any] | None = (
        dict(indicator_config) if isinstance(indicator_config, dict) else None
    )
    stmt = (
        select(AIModel, AIProvider)
        .join(AIProvider, AIModel.provider_id == AIProvider.id)
        .where(AIModel.model_id == model_id, AIModel.user_id == UUID(user_id))
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        yield StreamEvent(type="error", content="模型未找到")
        yield StreamEvent(type="done")
        return

    model, provider = row
    api_key = decrypt(provider.api_key)
    try:
        provider_impl = create_provider(
            provider.api_type,
            provider.base_url,
            api_key,
            model_id,
            thinking_enabled=provider.thinking_enabled,
        )
    except ValueError as exc:
        # 如 Jev（System One 决策模型）不支持对话：干净地结束流而非 500
        yield StreamEvent(type="error", content=str(exc))
        yield StreamEvent(type="done")
        return

    working_messages = messages
    if not model.is_multimodal:
        working_messages = strip_images(messages)

    # 尊重用户在「工具箱」中的开关：关闭的工具不下发给模型
    default_tools = await get_enabled_tool_definitions(redis_conn, user_id)
    skill_tools = await load_skill_tools(session, user_id)
    tools = default_tools + skill_tools
    tool_map = {tool.name: tool for tool in tools}
    current_messages = list(working_messages)

    # 确定性意图：图表指标设置 —— 不依赖模型是否自觉选 tool
    # 若用户关闭了 update_indicator_settings，则不强制执行
    from app.services.ai.indicator_intent import force_indicator_settings
    from app.services.ai.tools.preferences import is_tool_enabled

    if await is_tool_enabled(
        redis_conn, user_id, "update_indicator_settings"
    ):
        forced = await force_indicator_settings(
            current_messages,
            live_indicator_config,
            provider.api_type,
            MAX_TOOL_ROUNDS,
        )
        if forced is not None:
            events, current_messages, live_indicator_config = forced
            for event in events:
                yield event

    for round_num in range(MAX_TOOL_ROUNDS):
        tool_calls_collected: list[dict[str, Any]] = []
        yield StreamEvent(
            type="react_round",
            content=str(round_num + 1),
            tool_call_id=str(MAX_TOOL_ROUNDS),
        )

        async for event in provider_impl.chat_stream(current_messages, tools):
            if event.type in ("message", "thinking"):
                # 立刻推给前端：正文 / 思考打字效果
                yield event
            elif event.type == "tool_call":
                if event.tool_name:
                    # 同 call_id 合并（OpenAI 先发 name 再发完整 args）
                    existing = next(
                        (
                            item
                            for item in tool_calls_collected
                            if event.tool_call_id
                            and item["tool_call_id"] == event.tool_call_id
                        ),
                        None,
                    )
                    if existing is not None:
                        if event.tool_args:
                            existing["tool_args"] = event.tool_args
                        if event.tool_name:
                            existing["tool_name"] = event.tool_name
                    else:
                        tool_calls_collected.append(
                            {
                                "tool_name": event.tool_name,
                                "tool_args": event.tool_args,
                                "tool_call_id": event.tool_call_id,
                            }
                        )
                    # 立刻推 tool_call，前端显示「正在调用…」
                    yield event
                elif event.tool_args and tool_calls_collected:
                    tool_calls_collected[-1]["tool_args"] += event.tool_args
                    # Claude 参数增量：继续转发给前端合并展示
                    yield StreamEvent(
                        type="tool_call",
                        tool_name=tool_calls_collected[-1]["tool_name"],
                        tool_args=event.tool_args,
                        tool_call_id=tool_calls_collected[-1]["tool_call_id"],
                    )
            elif event.type == "error":
                yield event
                return

        if not tool_calls_collected:
            break

        needs_confirmation: list[dict[str, Any]] = []
        auto_execute: list[dict[str, Any]] = []
        for tool_call in tool_calls_collected:
            tool_def = tool_map.get(tool_call["tool_name"])
            # 解析参数：用户已确认（confirmed=true）的写操作直接执行
            try:
                args_parsed = (
                    json.loads(tool_call["tool_args"])
                    if tool_call.get("tool_args")
                    else {}
                )
            except (json.JSONDecodeError, TypeError):
                args_parsed = {}
            tool_call["tool_args_parsed"] = args_parsed
            user_confirmed = bool(args_parsed.get("confirmed"))
            if (
                tool_def
                and tool_def.requires_confirmation
                and not user_confirmed
            ):
                needs_confirmation.append(tool_call)
            else:
                auto_execute.append(tool_call)

        for tool_call in needs_confirmation:
            yield StreamEvent(
                type="confirmation_request",
                tool_name=tool_call["tool_name"],
                tool_args=tool_call["tool_args"],
                tool_call_id=tool_call["tool_call_id"],
            )
            pending = json.dumps(
                {
                    "status": "pending_confirmation",
                    "message": (
                        f"工具 {tool_call['tool_name']} 需要用户确认才能执行。"
                        "请向用户说明即将执行的操作并请求确认；"
                        "用户明确同意后，请用相同参数再次调用并设置 confirmed=true。"
                    ),
                },
                ensure_ascii=False,
            )
            yield StreamEvent(
                type="tool_result",
                tool_name=tool_call["tool_name"],
                content=pending,
                tool_call_id=tool_call["tool_call_id"],
            )

        tool_results: list[tuple[dict[str, Any], str]] = []
        if auto_execute:
            # 可流式工具（如 research_products）中途 yield 子代理状态
            streamable = [
                tc for tc in auto_execute if is_streamable_tool(tc["tool_name"])
            ]
            normal = [
                tc for tc in auto_execute if not is_streamable_tool(tc["tool_name"])
            ]
            for tool_call in streamable:
                args_parsed = tool_call.get("tool_args_parsed") or {}
                final_result = ""
                async for se in run_streamable_tool(
                    tool_call["tool_name"],
                    args_parsed if isinstance(args_parsed, dict) else {},
                    tool_call.get("tool_call_id") or "",
                    redis_conn,
                ):
                    if se.type == "tool_result":
                        final_result = se.content
                        yield se
                    else:
                        yield se
                tool_results.append((tool_call, final_result))
            if normal:
                normal_results = await execute_tools_parallel(
                    normal,
                    session,
                    user_id,
                    redis_conn,
                    live_indicator_config,
                )
                for tool_call, result_str in normal_results:
                    if tool_call["tool_name"] == "update_indicator_settings":
                        try:
                            payload = json.loads(result_str)
                            if payload.get("success") and isinstance(
                                payload.get("apply_config"), dict
                            ):
                                live_indicator_config = payload["apply_config"]
                        except (json.JSONDecodeError, TypeError):
                            pass
                    yield StreamEvent(
                        type="tool_result",
                        tool_name=tool_call["tool_name"],
                        content=result_str,
                        tool_call_id=tool_call["tool_call_id"],
                    )
                    tool_results.append((tool_call, result_str))

        all_executed = auto_execute + needs_confirmation
        current_messages.append(
            build_assistant_tool_call_message(all_executed, provider.api_type)
        )
        for tool_call in auto_execute:
            result_str = next(
                (
                    result
                    for item, result in tool_results
                    if item["tool_call_id"] == tool_call["tool_call_id"]
                ),
                "",
            )
            current_messages.append(
                build_tool_result_message(
                    tool_call["tool_call_id"],
                    tool_call["tool_name"],
                    result_str,
                    provider.api_type,
                )
            )
        for tool_call in needs_confirmation:
            current_messages.append(
                build_tool_result_message(
                    tool_call["tool_call_id"],
                    tool_call["tool_name"],
                    json.dumps(
                        {
                            "status": "pending_confirmation",
                            "message": "等待用户确认",
                        },
                        ensure_ascii=False,
                    ),
                    provider.api_type,
                )
            )

        if round_num >= MAX_TOOL_ROUNDS - 1:
            yield StreamEvent(type="error", content="工具调用轮次已达上限")

    yield StreamEvent(type="done")


__all__ = [
    "MAX_TOOL_ROUNDS",
    "chat_stream",
    "execute_tool",
    "get_tool_definitions",
    "get_tool_map",
    "load_skill_tools",
]

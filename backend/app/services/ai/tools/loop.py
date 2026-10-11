"""工具调用编排 —— 并行执行、重试、消息构造

从 gateway 拆出，保持网关文件在行数限制内。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.tools import execute_tool

logger = logging.getLogger("qihuo.ai.tool_loop")

TOOL_RETRY_COUNT = 1


async def execute_tool_with_retry(
    name: str,
    arguments: dict[str, Any],
    session: AsyncSession | None,
    user_id: str | None,
    redis_conn: Any | None,
    indicator_config: dict[str, Any] | None = None,
) -> str:
    """执行工具调用，超时类错误重试一次。"""
    for attempt in range(1 + TOOL_RETRY_COUNT):
        try:
            return await execute_tool(
                name,
                arguments,
                session,
                user_id,
                redis_conn,
                indicator_config,
            )
        except (asyncio.TimeoutError, TimeoutError):
            if attempt < TOOL_RETRY_COUNT:
                logger.info("工具 %s 超时，正在重试...", name)
                continue
            return json.dumps(
                {"error": f"工具 {name} 执行超时", "success": False},
                ensure_ascii=False,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "error": f"工具 {name} 执行失败: {str(exc)[:200]}",
                    "success": False,
                },
                ensure_ascii=False,
            )
    return ""


def build_tool_result_message(
    tool_call_id: str,
    tool_name: str,
    result: str,
    api_type: str,
) -> dict[str, Any]:
    """构造工具结果消息。"""
    if api_type == "claude":
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": result,
                }
            ],
        }
    return {"role": "tool", "tool_call_id": tool_call_id, "content": result}


def build_assistant_tool_call_message(
    tool_calls: list[dict[str, Any]],
    api_type: str,
) -> dict[str, Any]:
    """构造助手工具调用消息。"""
    if api_type == "claude":
        content = []
        for tool_call in tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_call["tool_call_id"],
                    "name": tool_call["tool_name"],
                    "input": tool_call.get("tool_args_parsed", {}),
                }
            )
        return {"role": "assistant", "content": content}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call["tool_call_id"],
                "type": "function",
                "function": {
                    "name": tool_call["tool_name"],
                    "arguments": tool_call["tool_args"],
                },
            }
            for tool_call in tool_calls
        ],
    }


async def execute_tools_parallel(
    tool_calls: list[dict[str, Any]],
    session: AsyncSession | None,
    user_id: str | None,
    redis_conn: Any | None,
    indicator_config: dict[str, Any] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """并行执行多个工具调用。"""
    tasks = []
    for tool_call in tool_calls:
        try:
            args_parsed = (
                json.loads(tool_call["tool_args"]) if tool_call["tool_args"] else {}
            )
        except json.JSONDecodeError:
            args_parsed = {}
        tool_call["tool_args_parsed"] = args_parsed
        tasks.append(
            execute_tool_with_retry(
                tool_call["tool_name"],
                args_parsed,
                session,
                user_id,
                redis_conn,
                indicator_config,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    output: list[tuple[dict[str, Any], str]] = []
    for tool_call, result in zip(tool_calls, results):
        if isinstance(result, Exception):
            result_str = json.dumps(
                {"error": str(result)[:200], "success": False},
                ensure_ascii=False,
            )
        else:
            result_str = result
        output.append((tool_call, result_str))
    return output


def strip_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去除消息中的图片内容。"""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            filtered = [item for item in content if item.get("type") != "image_url"]
            if filtered:
                cleaned.append({**msg, "content": filtered})
        else:
            cleaned.append(msg)
    return cleaned

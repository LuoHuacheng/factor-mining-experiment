"""OpenAI 规范 Provider —— 兼容 OpenAI/DeepSeek/通义千问等

工具调用在拿到 name 时即向前端发出 tool_call（loading），
参数增量继续拼接，流结束时再发完整参数。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.services.ai.providers.base import (
    AIProviderBase,
    StreamEvent,
    ToolDef,
)
from app.services.ai.providers.urls import resolve_endpoint


class OpenAIProvider(AIProviderBase):
    """OpenAI 兼容接口实现"""

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[ToolDef] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式聊天"""
        body = self.build_request(messages, tools)
        url = resolve_endpoint(self.base_url, "/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield StreamEvent(type="error", content=text.decode()[:500])
                    return
                async for event in self.parse_stream(resp):
                    yield event

        yield StreamEvent(type="done")

    async def list_models(self) -> list[str]:
        """获取模型列表"""
        url = resolve_endpoint(self.base_url, "/models")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

    def build_request(
        self,
        messages: list[dict],
        tools: list[ToolDef] | None = None,
    ) -> dict:
        """构造 OpenAI 格式请求体"""
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        return body

    async def parse_stream(self, response: Any) -> AsyncIterator[StreamEvent]:
        """解析 OpenAI SSE 流 —— 文本/思考增量；工具调用尽早通知前端"""
        tool_calls_buffer: dict[int, dict[str, Any]] = {}

        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                for tool_call in tool_calls_buffer.values():
                    yield StreamEvent(
                        type="tool_call",
                        tool_name=tool_call.get("function", {}).get("name", ""),
                        tool_args=tool_call.get("function", {}).get("arguments", ""),
                        tool_call_id=tool_call.get("id", ""),
                    )
                return

            chunk = json.loads(data)
            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            finish_reason = choice.get("finish_reason")

            if delta.get("reasoning_content"):
                yield StreamEvent(type="thinking", content=delta["reasoning_content"])

            if delta.get("content"):
                yield StreamEvent(type="message", content=delta["content"])

            if delta.get("tool_calls"):
                for tool_delta in delta["tool_calls"]:
                    index = tool_delta.get("index", 0)
                    if index not in tool_calls_buffer:
                        tool_calls_buffer[index] = {
                            "id": tool_delta.get("id", ""),
                            "function": {"name": "", "arguments": ""},
                            "started": False,
                        }
                    entry = tool_calls_buffer[index]
                    if tool_delta.get("id"):
                        entry["id"] = tool_delta["id"]
                    function_delta = tool_delta.get("function", {})
                    if function_delta.get("name"):
                        entry["function"]["name"] = function_delta["name"]
                    if function_delta.get("arguments"):
                        entry["function"]["arguments"] += function_delta["arguments"]

                    # 首次拿到工具名就推送，前端立刻显示「正在调用」
                    if entry["function"]["name"] and not entry["started"]:
                        entry["started"] = True
                        yield StreamEvent(
                            type="tool_call",
                            tool_name=entry["function"]["name"],
                            tool_args="",
                            tool_call_id=entry.get("id", ""),
                        )

            # finish_reason=tool_calls 时立刻刷出完整参数（不必等 [DONE]）
            if finish_reason == "tool_calls" and tool_calls_buffer:
                for tool_call in tool_calls_buffer.values():
                    yield StreamEvent(
                        type="tool_call",
                        tool_name=tool_call.get("function", {}).get("name", ""),
                        tool_args=tool_call.get("function", {}).get("arguments", ""),
                        tool_call_id=tool_call.get("id", ""),
                    )
                tool_calls_buffer.clear()

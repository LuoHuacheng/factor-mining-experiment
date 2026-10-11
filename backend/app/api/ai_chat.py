"""AI 聊天 REST API —— SSE 流式接口，支持对话持久化、短期记忆、长期记忆、RAG"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_conversation import auto_rename_conversation, save_message
from app.core.deps import get_current_user, get_session
from app.models.ai_conversation import AIConversation
from app.models.user import User
from app.services.ai.gateway import chat_stream
from app.services.ai.knowledge import format_context_from_results, hybrid_search
from app.services.ai.long_term_memory import retrieve_relevant_memories
from app.services.ai.memory import load_context_messages

router = APIRouter(prefix="/api/ai", tags=["AI 聊天"])

# 系统提示：意图分流（图表设置 vs 行情分析）必须放在最前
HALLUCINATION_CONTROL = (
    "你是本期货交易终端内置的 AI 助手，直接操控用户当前打开的 K 线图表。"
    "用户正在终端里看图，不是空口问行情。\n\n"
    "【回答必须可操作 · 禁止模棱两可】\n"
    "用户问方向/点位/买卖时，必须先调用合适工具拿真实数据，再给出：\n"
    "1) 明确方向：做多 / 做空 / 观望（三选一，不要写「偏多观望」这类含糊词）\n"
    "2) 具体数字：现价、入场点、支撑位、压力位、止损价、止盈价\n"
    "3) 缺数据就继续调工具，禁止编造价格；工具失败就直说失败原因\n"
    "禁止：「附近」「酌情」「看情况」「建议关注」「可以考虑」等无数字空话。\n\n"
    "【多品种/全市场调研】\n"
    "用户要求调研全部品种、扫描多个主力、汇报做多/做空点位时，"
    "必须调用 research_products（scope=all 或品种列表），"
    "禁止用 get_quote/get_kline 逐个扫全市场。\n"
    "research_products 返回后：优先把 report_markdown 原样展示给用户；"
    "表格列必须包含 方向/现价/入场点/支撑位/压力位/止损/止盈；"
    "震荡已过滤，不要编造未返回的品种。\n\n"
    "【最高优先级 · 图表指标设置】\n"
    "下列意图一律调用 update_indicator_settings（可先 get_indicator_settings），"
    "禁止反问合约代码，禁止用 calculate_indicator 代替：\n"
    "- 打开/关闭/显示/隐藏 RSI、MACD、布林带、均线\n"
    "- 修改指标参数（周期、超买超卖、标准差等）\n"
    "- 改颜色、实线/虚线、恢复默认指标\n"
    "示例：用户说「打开 RSI」→ 立刻 tool 调用 "
    "update_indicator_settings 参数 {\"rsi\":{\"enabled\":true}}，"
    "然后简短确认「已为您开启 RSI 副图」。\n"
    "示例：「布林上轨改实线」→ "
    "{\"boll\":{\"enabled\":true,\"upperStyle\":\"solid\"}}\n"
    "示例：「均线改成5/10/20」→ "
    "{\"maLines\":[{\"period\":5,\"color\":\"#3b82f6\"},"
    "{\"period\":10,\"color\":\"#f59e0b\"},{\"period\":20,\"color\":\"#a855f7\"}]}\n\n"
    "【行情分析 · 需要合约】\n"
    "仅当用户要「分析/计算/查询某品种价格、持仓、新闻、数值指标」时，"
    "才使用 get_quote / get_kline / calculate_indicator 等行情工具；"
    "若未给合约代码再询问。\n"
    "严禁编造价格与指标数值；知识库内容需引用来源。\n"
    "calculate_indicator 只返回计算数值，不会改图表显示；"
    "改图表显示必须用 update_indicator_settings。"
)

# session_factory 类型：返回 async context manager 的可调用对象
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ChatRequest(BaseModel):
    """聊天请求"""
    model_id: str = Field(..., description="模型标识（如 gpt-4o）")
    messages: list[dict] = Field(default_factory=list, description="消息列表（有 conversation_id 时可选）")
    conversation_id: UUID | None = Field(default=None, description="对话 ID，传入则持久化消息并启用记忆")
    # 前端当前图表指标设置，供 Agent get/update_indicator_settings 使用
    indicator_config: dict | None = Field(
        default=None,
        description="当前 IndicatorConfig JSON（maLines/macd/rsi/boll）",
    )


def _format_sse(event_type: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _assert_conversation_owner(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> None:
    """校验对话归属当前用户，不存在或不属于本人则 404（避免泄露是否存在）"""
    stmt = select(AIConversation.id).where(
        AIConversation.id == conversation_id,
        AIConversation.user_id == user_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        )


def _format_indicator_context(config: dict | None) -> str:
    """把当前图表指标配置压缩成系统提示，帮助模型理解「已在图表里」"""
    if not isinstance(config, dict):
        return (
            "[当前图表指标] 前端未上报配置。用户要改 RSI/MACD/布林/均线时，"
            "仍直接调用 update_indicator_settings，不要问合约代码。"
        )
    ma_lines = config.get("maLines") or []
    ma_desc = ",".join(
        f"MA{line.get('period')}" for line in ma_lines if isinstance(line, dict)
    ) or "无"
    macd = config.get("macd") or {}
    rsi = config.get("rsi") or {}
    boll = config.get("boll") or {}
    return (
        "[当前图表指标设置 · 已同步，可直接改]\n"
        f"- 均线: {ma_desc}\n"
        f"- MACD: {'开' if macd.get('enabled') else '关'}"
        f" ({macd.get('fastPeriod')}/{macd.get('slowPeriod')}/{macd.get('signalPeriod')})\n"
        f"- RSI: {'开' if rsi.get('enabled') else '关'}"
        f" (周期{rsi.get('period')}, 超买{rsi.get('overbought')}/超卖{rsi.get('oversold')})\n"
        f"- 布林: {'开' if boll.get('enabled') else '关'}"
        f" (周期{boll.get('period')}, σ={boll.get('std')},"
        f" 上轨{boll.get('upperStyle')}/中轨{boll.get('middleStyle')}/下轨{boll.get('lowerStyle')})\n"
        "用户说打开/关闭/改参数/改颜色/改线型 → update_indicator_settings，不要问合约。"
    )


async def _build_enriched_context(
    session: AsyncSession,
    user_id: str,
    conversation_id: UUID | None,
    client_messages: list[dict],
    indicator_config: dict | None,
) -> tuple[list[dict], str]:
    """构建增强上下文（滑动窗口 + 长期记忆 + RAG + 指标设置）"""
    user_content = ""
    context_messages: list[dict] = []

    # 1. 提取用户最新消息
    if client_messages:
        last_msg = client_messages[-1]
        user_content = last_msg.get("content", "")
        if isinstance(user_content, list):
            text_parts = [
                p.get("text", "") for p in user_content if p.get("type") == "text"
            ]
            user_content = " ".join(text_parts)

    # 2. 从 DB 加载对话历史（含滑动窗口 + 摘要）
    if conversation_id is not None:
        context_messages = await load_context_messages(session, conversation_id)

    # 3. 注入长期记忆（相关历史摘要）
    memory_injection = ""
    if conversation_id is not None and user_content.strip():
        try:
            memories = await retrieve_relevant_memories(
                session, user_id, user_content, top_k=3
            )
            if memories:
                memory_parts = ["[相关历史记忆]"]
                for i, m in enumerate(memories, 1):
                    memory_parts.append(f"{i}. {m[:200]}")
                memory_injection = "\n".join(memory_parts)
        except Exception:
            pass

    # 4. RAG 知识库检索
    rag_injection = ""
    if user_content.strip():
        try:
            rag_results = await hybrid_search(session, user_id, user_content, top_k=5)
            if rag_results:
                rag_injection = format_context_from_results(rag_results)
        except Exception:
            pass

    # 5. 构建最终上下文（系统提示不可被 client_messages 覆盖）
    enriched: list[dict] = []
    enriched.append({"role": "system", "content": HALLUCINATION_CONTROL})
    enriched.append(
        {"role": "system", "content": _format_indicator_context(indicator_config)}
    )

    if memory_injection:
        enriched.append({"role": "system", "content": memory_injection})
    if rag_injection:
        enriched.append({"role": "system", "content": rag_injection})

    # 对话历史：有 DB 历史用 DB；否则用客户端消息（去掉 system）
    if context_messages:
        enriched.extend(context_messages)
        if user_content.strip() and context_messages[-1].get("role") != "user":
            enriched.append({"role": "user", "content": user_content})
    elif client_messages:
        for msg in client_messages:
            if msg.get("role") == "system":
                continue
            enriched.append(msg)
    elif user_content.strip():
        enriched.append({"role": "user", "content": user_content})

    return enriched, user_content


async def _stream_generator(
    session_factory: SessionFactory,
    user_id: str,
    model_id: str,
    client_messages: list[dict],
    conversation_id: UUID | None,
    redis_conn: object | None,
    indicator_config: dict | None,
) -> AsyncIterator[str]:
    """SSE 流式生成器

    使用独立 session_factory，而不是 request-scoped Depends session。
    FastAPI 会在 endpoint 返回 StreamingResponse 时清理 Depends session，
    若流式生成器继续复用该 session 会导致落库失败。
    redis_conn 供 Agent 工具读行情/K 线缓存。
    indicator_config 供指标设置工具读写。
    """
    full_content = ""
    collected_tool_calls: list[dict] = []
    collected_tool_results: list[dict] = []
    user_content = ""
    context_messages: list[dict] = []

    # 阶段 1：构建上下文 + 持久化用户消息（独立短事务）
    async with session_factory() as session:
        try:
            context_messages, user_content = await _build_enriched_context(
                session,
                user_id,
                conversation_id,
                client_messages,
                indicator_config,
            )

            # 30 分钟无操作检测：触发长期记忆存储
            if conversation_id is not None:
                try:
                    from datetime import datetime, timedelta, timezone

                    from sqlalchemy import func

                    from app.models.ai_conversation import AIMessage
                    from app.services.ai.long_term_memory import store_conversation_summary

                    stmt = select(func.max(AIMessage.created_at)).where(
                        AIMessage.conversation_id == conversation_id
                    )
                    result = await session.execute(stmt)
                    last_msg_time = result.scalar_one_or_none()
                    if last_msg_time and (datetime.now(timezone.utc) - last_msg_time) > timedelta(minutes=30):
                        await store_conversation_summary(session, user_id, conversation_id)
                except Exception:
                    pass

            # 持久化用户消息
            if conversation_id is not None and user_content.strip():
                await save_message(session, conversation_id, "user", user_content)

                stmt = select(AIConversation.title).where(
                    AIConversation.id == conversation_id,
                    AIConversation.user_id == UUID(user_id),
                )
                result = await session.execute(stmt)
                title = result.scalar_one_or_none()
                if title == "新对话":
                    await auto_rename_conversation(session, conversation_id, user_content)

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # 阶段 2：流式调用 AI（独立 session，覆盖整个流生命周期）
    async with session_factory() as session:
        try:
            async for event in chat_stream(
                session,
                user_id,
                model_id,
                context_messages,
                redis_conn,
                indicator_config,
            ):
                if event.type == "message":
                    full_content += event.content
                    yield _format_sse("message", {"content": event.content})
                elif event.type == "thinking":
                    yield _format_sse("thinking", {"content": event.content})
                elif event.type == "tool_call":
                    collected_tool_calls.append({
                        "name": event.tool_name,
                        "args": event.tool_args,
                        "call_id": event.tool_call_id,
                    })
                    yield _format_sse("tool_call", {
                        "name": event.tool_name,
                        "arguments": event.tool_args,
                        "call_id": event.tool_call_id,
                    })
                elif event.type == "tool_result":
                    collected_tool_results.append({
                        "name": event.tool_name,
                        "content": event.content,
                        "call_id": event.tool_call_id,
                    })
                    yield _format_sse("tool_result", {
                        "name": event.tool_name,
                        "content": event.content,
                        "call_id": event.tool_call_id,
                    })
                elif event.type == "confirmation_request":
                    yield _format_sse("confirmation_request", {
                        "name": event.tool_name,
                        "arguments": event.tool_args,
                        "call_id": event.tool_call_id,
                    })
                elif event.type == "react_round":
                    yield _format_sse("react_round", {
                        "round": int(event.content),
                        "max_rounds": int(event.tool_call_id),
                    })
                elif event.type == "subagent_plan":
                    extra = event.extra if isinstance(event.extra, dict) else {}
                    yield _format_sse("subagent_plan", {
                        "agents": extra.get("agents") or [],
                        "total": extra.get("total") or 0,
                    })
                elif event.type == "subagent_update":
                    extra = event.extra if isinstance(event.extra, dict) else {}
                    yield _format_sse("subagent_update", {
                        "id": extra.get("id") or "",
                        "name": extra.get("name") or "",
                        "status": extra.get("status") or "pending",
                        "detail": extra.get("detail") or "",
                        "progress": extra.get("progress"),
                        "long_count": extra.get("long_count"),
                        "short_count": extra.get("short_count"),
                        "error": extra.get("error"),
                    })
                elif event.type == "error":
                    yield _format_sse("error", {"message": event.content})
                elif event.type == "done":
                    # 持久化助手消息（含工具调用记录）
                    if conversation_id is not None and (full_content or collected_tool_calls):
                        tool_calls_data = collected_tool_calls if collected_tool_calls else None
                        tool_results_data = collected_tool_results if collected_tool_results else None
                        await save_message(
                            session,
                            conversation_id,
                            "assistant",
                            full_content,
                            tool_calls=tool_calls_data,
                            tool_result=tool_results_data,
                        )
                        await session.commit()
                    yield _format_sse("done", {})
        except Exception as e:
            try:
                if conversation_id is not None and (full_content or collected_tool_calls):
                    tool_calls_data = collected_tool_calls if collected_tool_calls else None
                    tool_results_data = collected_tool_results if collected_tool_results else None
                    await save_message(
                        session,
                        conversation_id,
                        "assistant",
                        full_content,
                        tool_calls=tool_calls_data,
                        tool_result=tool_results_data,
                    )
                    await session.commit()
            except Exception:
                await session.rollback()
            yield _format_sse("error", {"message": str(e)[:500]})
            yield _format_sse("done", {})

    # 阶段 3：长期记忆（独立短事务，失败不阻塞）
    if conversation_id is not None and full_content:
        async with session_factory() as session:
            try:
                from app.services.ai.long_term_memory import (
                    extract_and_store_preferences,
                    store_conversation_summary,
                )
                await store_conversation_summary(session, user_id, conversation_id)
                if user_content.strip():
                    await extract_and_store_preferences(
                        session, user_id, user_content, full_content
                    )
                await session.commit()
            except Exception:
                await session.rollback()


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 流式聊天接口，支持对话持久化、短期记忆、长期记忆、RAG"""
    # 流开始前强制校验对话归属，防止水平越权写/读他人会话
    if body.conversation_id is not None:
        await _assert_conversation_owner(session, body.conversation_id, current_user.id)

    session_factory: SessionFactory = request.app.state.session_factory
    redis_conn = getattr(request.app.state, "redis", None)
    return StreamingResponse(
        _stream_generator(
            session_factory,
            str(current_user.id),
            body.model_id,
            body.messages,
            body.conversation_id,
            redis_conn,
            body.indicator_config,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # 禁用反向代理/浏览器对 SSE 的缓冲，保证 token 级推送
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )

"""行情 Agent 工具：quote / kline（合并秒级实时）"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import redis.asyncio as aioredis

SUPPORTED_PERIODS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "60m", "1d")
from app.services.kline import get_kline_history

logger = logging.getLogger("app.ai.tools_market")
_Q = "market:quote:"
_R = "kline:realtime:"
_BJ = timezone(timedelta(hours=8))


def _limit(limit: int | None, default: int, maximum: int) -> int:
    """规范化 limit。"""
    try:
        value = int(limit) if limit is not None else default
    except (TypeError, ValueError):
        return default
    return default if value <= 0 else min(value, maximum)


def _f(value: Any) -> float | None:
    """安全 float。"""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    """安全 int。"""
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _slim(bar: dict[str, Any]) -> dict[str, Any]:
    """精简 bar。"""
    return {
        "time": bar.get("time"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "settle": bar.get("settle"),
        "open_interest": bar.get("open_interest"),
    }


def _overlay_quote(bars: list[dict[str, Any]], quote: dict[str, Any] | None) -> bool:
    """用 quote 刷新末根价与持仓。"""
    if not bars or not quote:
        return False
    last = bars[-1]
    price = _f(quote.get("last_price"))
    if price is not None:
        last["close"] = price
        high, low = _f(last.get("high")), _f(last.get("low"))
        if high is None or price > high:
            last["high"] = price
        if low is None or price < low:
            last["low"] = price
    pos = _i(quote.get("position"))
    if pos is not None:
        last["open_interest"] = pos
    return price is not None or pos is not None


def _merge(
    history: list[dict[str, Any]],
    rt_bar: dict[str, Any] | None,
    quote: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], bool, str]:
    """合并 forming bar；兼容 time 标签不一致。"""
    bars = [_slim(item) for item in history]
    mode, done = "none", False
    oi = _i(quote.get("position")) if quote else None
    if rt_bar is not None:
        rt = _slim(rt_bar)
        if oi is not None and rt.get("open_interest") is None:
            rt["open_interest"] = oi
        if not bars:
            bars, done, mode = [rt], True, "append"
        else:
            lt, rt_t = str(bars[-1].get("time") or ""), str(rt.get("time") or "")
            if rt_t and lt == rt_t:
                last = bars[-1]
                bars[-1] = {
                    **last,
                    "open": rt.get("open", last.get("open")),
                    "high": rt.get("high", last.get("high")),
                    "low": rt.get("low", last.get("low")),
                    "close": rt.get("close", last.get("close")),
                    "volume": rt.get("volume", last.get("volume")),
                    "settle": rt.get("settle") if rt.get("settle") is not None else last.get("settle"),
                    "open_interest": (
                        rt.get("open_interest")
                        if rt.get("open_interest") is not None
                        else last.get("open_interest")
                    ),
                }
                done, mode = True, "equal"
            elif rt_t and lt < rt_t:
                bars.append(rt)
                done, mode = True, "append"
            elif rt_t and lt > rt_t:
                last = bars[-1]
                close = _f(rt.get("close"))
                if close is not None:
                    last["close"] = close
                    high, low = _f(last.get("high")), _f(last.get("low"))
                    if high is None or close > high:
                        last["high"] = close
                    if low is None or close < low:
                        last["low"] = close
                if oi is not None:
                    last["open_interest"] = oi
                done, mode = True, "label_mismatch"
    if _overlay_quote(bars, quote):
        done = True
        if mode == "none":
            mode = "quote_only"
    return bars, done, mode


def _sum_quote(quote: dict[str, Any]) -> dict[str, Any]:
    """精简 quote。"""
    return {
        "symbol": quote.get("symbol"),
        "name": quote.get("name"),
        "exchange": quote.get("exchange"),
        "last_price": quote.get("last_price"),
        "change": quote.get("change"),
        "change_pct": quote.get("change_pct"),
        "open_price": quote.get("open_price"),
        "high_price": quote.get("high_price"),
        "low_price": quote.get("low_price"),
        "pre_settle": quote.get("pre_close"),
        "bid_price": quote.get("bid_price"),
        "ask_price": quote.get("ask_price"),
        "volume": quote.get("volume"),
        "open_interest": quote.get("position"),
        "tick_time": quote.get("tick_time"),
        "decimal_places": quote.get("decimal_places"),
        "source_note": "pre_settle=昨结算; open_interest=持仓; ~1s",
    }


async def _redis_json(
    redis_conn: aioredis.Redis | None,
    keys: list[str],
) -> dict[str, Any] | None:
    """按候选 key 读 JSON dict。"""
    if redis_conn is None:
        return None
    for key in keys:
        raw = await redis_conn.get(key)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


async def _read_quote(redis_conn: aioredis.Redis | None, symbol: str) -> dict[str, Any] | None:
    """读行情缓存。"""
    s = symbol.lower().strip()
    return await _redis_json(redis_conn, [f"{_Q}{s}", f"{_Q}{symbol.strip()}"])


async def _read_rt(
    redis_conn: aioredis.Redis | None,
    symbol: str,
    period: str,
) -> dict[str, Any] | None:
    """读实时 bar。"""
    s = symbol.lower().strip()
    payload = await _redis_json(
        redis_conn,
        [f"{_R}{s}:{period}", f"{_R}{symbol.strip()}:{period}"],
    )
    if not payload:
        return None
    bar = payload.get("bar")
    return bar if isinstance(bar, dict) and bar.get("time") is not None else None


async def tool_get_quote(
    symbol: str,
    redis_conn: aioredis.Redis | None,
) -> dict[str, Any]:
    """实时行情（Redis 优先，调度约 1 秒）。"""
    symbol_clean = symbol.strip()
    if not symbol_clean:
        return {"success": False, "error": "symbol 不能为空"}
    as_of = datetime.now(_BJ).isoformat(timespec="seconds")
    cached = await _read_quote(redis_conn, symbol_clean)
    if cached is not None:
        return {
            "success": True,
            "source": "redis",
            "as_of": as_of,
            "freshness": "scheduler_~1s",
            "quote": _sum_quote(cached),
        }
    return {"success": False, "error": f"未获取到行情: {symbol_clean}"}


async def tool_get_kline(
    symbol: str,
    period: str,
    limit: int | None,
    redis_conn: aioredis.Redis | None,
) -> dict[str, Any]:
    """K 线 = 历史 + 实时 forming + quote 覆盖最新价/持仓。"""
    symbol_clean, period_clean = symbol.strip(), period.strip()
    if not symbol_clean:
        return {"success": False, "error": "symbol 不能为空"}
    if period_clean not in SUPPORTED_PERIODS:
        return {
            "success": False,
            "error": f"不支持的周期: {period_clean}，可选: {', '.join(SUPPORTED_PERIODS)}",
        }
    bar_limit = _limit(limit, 50, 200)
    as_of = datetime.now(_BJ).isoformat(timespec="seconds")
    bars: list[dict[str, Any]] = []
    source = "history"
    if redis_conn is not None:
        bars = await get_kline_history(
            redis_conn, symbol_clean, period_clean, limit=bar_limit, end_time="", session=None
        )
        source = "kline_service"
    else:
        # 无 Redis：走多数据源统一入口（主渠道优先，失败自动降级备用渠道）
        from app.data.kline_provider import fetch_kline_with_fallback

        bars = await fetch_kline_with_fallback(
            None, symbol_clean, period_clean
        )
        if bars:
            bars = bars[-bar_limit:]

    quote = await _read_quote(redis_conn, symbol_clean)
    rt = await _read_rt(redis_conn, symbol_clean, period_clean)
    slim, merged, mode = _merge(bars, rt, quote)
    if bar_limit > 0 and len(slim) > bar_limit:
        slim = slim[-bar_limit:]
    if not slim:
        return {"success": False, "error": f"未获取到 K 线: {symbol_clean} {period_clean}"}
    first, last = slim[0], slim[-1]
    live = quote.get("last_price") if quote else last.get("close")
    return {
        "success": True,
        "source": source,
        "as_of": as_of,
        "realtime_merged": merged,
        "merge_mode": mode,
        "freshness": "history+realtime+quote_~1s" if merged else "history_only",
        "symbol": symbol_clean,
        "period": period_clean,
        "limit": bar_limit,
        "summary": {
            "bar_count": len(slim),
            "first_time": first.get("time"),
            "last_time": last.get("time"),
            "last_close": last.get("close"),
            "live_last_price": live,
            "last_volume": last.get("volume"),
            "last_open_interest": last.get("open_interest"),
            "last_settle": last.get("settle"),
            "realtime_merged": merged,
            "merge_mode": mode,
        },
        "bars": slim,
    }

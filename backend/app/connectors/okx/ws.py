"""OKX 公开 WebSocket —— tickers / books5 / trades

公开频道无需登录。订阅信封：
  {"op": "subscribe", "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]}

断线重连由本模块负责；上层只需提供 on_quote 回调。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

import websockets

from app.connectors.okx.market import ticker_to_quote

logger = logging.getLogger("qihuo.okx.ws")

OKX_PUBLIC_WS = "wss://ws.okx.com:8443/ws/v5/public"
OKX_DEMO_PUBLIC_WS = "wss://wspap.okx.com:8443/ws/v5/public"

# 重连退避（秒）
_RECONNECT_MIN = 1.0
_RECONNECT_MAX = 30.0

# 服务端要求 30 秒内至少一次心跳
_PING_INTERVAL = 20.0

QuoteCallback = Callable[[dict[str, Any]], Awaitable[None]]


def subscribe_args(symbols: list[str], channels: list[str]) -> list[dict[str, str]]:
    """构造订阅 args（symbol 转 OKX instId 大写）"""
    return [
        {"channel": channel, "instId": str(symbol).strip().upper()}
        for channel in channels
        for symbol in symbols
        if str(symbol or "").strip()
    ]


def parse_ws_message(msg: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """解析数据帧 → (channel, 首条数据)；事件帧/错误帧/空数据返回 None"""
    if not isinstance(msg, dict):
        return None
    arg = msg.get("arg")
    if not isinstance(arg, dict):
        return None
    data = msg.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    return str(arg.get("channel") or ""), first


class OkxPublicWs:
    """公开行情 WS 长连接，带指数退避重连"""

    def __init__(self, url: str | None = None, demo: bool = False) -> None:
        if url is not None:
            self._url = url
        else:
            self._url = OKX_DEMO_PUBLIC_WS if demo else OKX_PUBLIC_WS
        self._stop = asyncio.Event()
        self._channels: list[str] = ["tickers"]

    async def stop(self) -> None:
        self._stop.set()

    async def _send_subscribe(self, ws: Any, args: list[dict[str, str]]) -> None:
        await ws.send(json.dumps({"op": "subscribe", "args": args}))

    async def _handle(self, raw: str, on_quote: QuoteCallback) -> None:
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(msg, dict) and msg.get("event") == "error":
            logger.warning("OKX WS 错误帧：%s", msg)
            return
        parsed = parse_ws_message(msg)
        if parsed is None:
            return
        channel, payload = parsed
        if channel != "tickers":
            return
        quote = ticker_to_quote(payload)
        if quote is None:
            return
        await on_quote(quote)

    async def run(self, symbols: list[str], on_quote: QuoteCallback) -> None:
        """持续运行直到 stop()；每次断线按指数退避重连"""
        args = subscribe_args(symbols, self._channels)
        if not args:
            logger.warning("OKX WS 无订阅标的，退出")
            return

        backoff = _RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._url) as ws:
                    await self._send_subscribe(ws, args)
                    logger.info("OKX WS 已连接，订阅 %d 个频道", len(args))
                    backoff = _RECONNECT_MIN
                    while not self._stop.is_set():
                        try:
                            raw = await asyncio.wait_for(
                                ws.recv(), timeout=_PING_INTERVAL
                            )
                        except asyncio.TimeoutError:
                            await ws.send("ping")
                            continue
                        await self._handle(raw, on_quote)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("OKX WS 断开（%.0fs 后重连）：%s", backoff, exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, _RECONNECT_MAX)

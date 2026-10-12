"""OKX 行情写入 Redis —— WS 增量 + REST 快照兜底

写入两个键（与既有 market_keys 契约一致）：
- market:live:quote:{symbol}           统一报价（下游唯一读入口）
- market:live:source:okx:quote:{symbol} 原始源快照（收盘/断线时兜底）

quote 必须先过 normalize_quote_fields：下游 K 线/WS/前端都按该契约读字段。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.connectors.okx.client import OkxRestClient
from app.connectors.okx.market import fetch_tickers
from app.connectors.okx.ws import OkxPublicWs
from app.data.quote_schema import normalize_quote_fields
from app.services.market_keys import quote_key, source_quote_key

logger = logging.getLogger("qihuo.okx.quote")

# 统一报价键 TTL：OKX 24/7，10 分钟无更新视为过期
_QUOTE_TTL = 600

SOURCE_OKX = "okx"
MODE_LIVE = "live"

# REST 快照兜底间隔（秒）
_SNAPSHOT_INTERVAL = 60.0


class OkxQuoteService:
    """把 OKX 行情写进 Redis 的对应 trading_mode 命名空间"""

    def __init__(
        self,
        redis_conn: Any,
        client: OkxRestClient | None = None,
        ws: OkxPublicWs | None = None,
        mode: str = MODE_LIVE,
        source: str = SOURCE_OKX,
    ) -> None:
        self._redis = redis_conn
        self._mode = mode
        self._source = source
        self._client = client or OkxRestClient(demo=(mode != MODE_LIVE))
        self._ws = ws or OkxPublicWs(demo=(mode != MODE_LIVE))
        self._tasks: list[asyncio.Task] = []

    async def write_quote(self, quote: dict[str, Any]) -> bool:
        """归一化并写入 Redis；无效 quote 返回 False"""
        normalized = normalize_quote_fields(quote)
        if normalized is None:
            return False
        symbol = normalized["symbol"]
        payload = json.dumps(normalized, ensure_ascii=False)
        try:
            await self._redis.set(
                quote_key(self._mode, symbol), payload, ex=_QUOTE_TTL
            )
            await self._redis.set(
                source_quote_key(self._source, symbol, self._mode),
                payload,
                ex=_QUOTE_TTL,
            )
        except Exception as exc:
            logger.warning("OKX 报价写入 Redis 失败 %s：%s", symbol, exc)
            return False
        return True

    async def snapshot_once(self) -> int:
        """REST 全市场快照（WS 未覆盖或断线时的兜底）"""
        written = 0
        seen: set[str] = set()
        for inst_type in ("SWAP", "SPOT"):
            try:
                quotes = await fetch_tickers(self._client, inst_type)
            except Exception as exc:
                logger.warning("OKX %s 快照拉取失败：%s", inst_type, exc)
                continue
            for quote in quotes:
                sym = quote.get("symbol")
                if sym and sym in seen:
                    continue
                if await self.write_quote(quote):
                    if sym:
                        seen.add(sym)
                    written += 1
        return written

    async def _snapshot_loop(self) -> None:
        while True:
            try:
                count = await self.snapshot_once()
                logger.info("OKX 快照兜底完成：%d 条", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("OKX 快照兜底异常：%s", exc)
            await asyncio.sleep(_SNAPSHOT_INTERVAL)

    async def start(self, symbols: list[str]) -> None:
        """启动 WS 增量 + REST 快照兜底两个任务"""
        self._tasks = [
            asyncio.create_task(
                self._ws.run(symbols, self.write_quote), name="okx-ws-quote"
            ),
            asyncio.create_task(self._snapshot_loop(), name="okx-snapshot"),
        ]
        logger.info("OKX 行情服务已启动：WS %d 个标的 + REST 快照兜底", len(symbols))

    async def stop(self) -> None:
        await self._ws.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

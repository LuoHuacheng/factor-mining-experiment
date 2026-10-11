"""Redis 连接模块 —— 异步 Redis 连接"""

import redis.asyncio as aioredis
import redis.exceptions
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from app.core.config import Settings


async def create_redis_connection(settings: Settings) -> aioredis.Redis:
    """创建异步 Redis 连接。

    开启 health_check + retry_on_error：redis 抖动/短暂断连时由 redis-py 自动
    重连重试，避免 ConnectionError 冒泡到应用导致进程崩溃（曾引发 backend exit 128）。
    """
    connection = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=20,
        health_check_interval=30,
        retry=Retry(backoff=ExponentialBackoff(cap=1.0, base=0.1), retries=5),
        retry_on_error=[
            redis.exceptions.ConnectionError,
            redis.exceptions.TimeoutError,
        ],
    )
    # 验证连接
    await connection.ping()
    return connection


async def close_redis_connection(connection: aioredis.Redis) -> None:
    """关闭 Redis 连接"""
    await connection.close()

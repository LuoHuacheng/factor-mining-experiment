"""用量配额服务 —— 任务数/因子实验室/回测 每日次数限制

规则：
- 全局默认：SystemSettings(max_tasks_per_user / factor_lab_daily_limit / backtest_daily_limit)
- per-user 覆盖：User(max_tasks_override / factor_lab_daily_override / backtest_daily_override)，
  非 null 时覆盖全局默认
- 管理员(role=admin)不限（全部 None）
- 0 表示不限；null(override) 表示用全局默认
- 每日次数按上海时区日历日计数（redis），次日 key 变更自动归零
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_trading.task import AITradingTask
from app.models.user import User

_BJ_TZ = ZoneInfo("Asia/Shanghai")

# 每日计数 feature 名
FEATURE_FACTOR = "factor"
FEATURE_BACKTEST = "backtest"


def _today_key() -> str:
    """上海时区当日日期键 yyyymmdd（次日自动变更 → 计数归零）"""
    return datetime.now(_BJ_TZ).strftime("%Y%m%d")


def _quota_key(user_id: UUID, feature: str) -> str:
    """redis 配额计数 key"""
    return f"quota:{user_id}:{feature}:{_today_key()}"


def _resolve_limit(override: int | None, default: int) -> int | None:
    """合并 override 与默认；0 表示不限（返回 None）"""
    raw = int(override) if override is not None else int(default)
    return None if raw <= 0 else raw


async def get_effective_limits(
    session: AsyncSession,
    user: User,
) -> dict[str, int | None]:
    """返回用户生效配额 {max_tasks, factor_daily, backtest_daily}；None=不限"""
    if str(getattr(user, "role", "user")) == "admin":
        return {"max_tasks": None, "factor_daily": None, "backtest_daily": None}
    from app.services.system_settings_svc import ensure_system_settings

    settings = await ensure_system_settings(session)
    return {
        "max_tasks": _resolve_limit(
            getattr(user, "max_tasks_override", None),
            int(getattr(settings, "max_tasks_per_user", 5)),
        ),
        "factor_daily": _resolve_limit(
            getattr(user, "factor_lab_daily_override", None),
            int(getattr(settings, "factor_lab_daily_limit", 3)),
        ),
        "backtest_daily": _resolve_limit(
            getattr(user, "backtest_daily_override", None),
            int(getattr(settings, "backtest_daily_limit", 2)),
        ),
    }


async def count_active_tasks(session: AsyncSession, user: User) -> int:
    """用户活跃任务数（running + paused）"""
    stmt = select(func.count(AITradingTask.id)).where(
        AITradingTask.user_id == user.id,
        AITradingTask.status.in_(("running", "paused")),
    )
    result = await session.execute(stmt)
    return int(result.scalar() or 0)


async def daily_used(
    redis_conn: Any,
    user_id: UUID,
    feature: str,
) -> int:
    """用户今日某功能已用次数"""
    if redis_conn is None:
        return 0
    raw = await redis_conn.get(_quota_key(user_id, feature))
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def check_and_incr(
    redis_conn: Any,
    user: User,
    feature: str,
    limit: int | None,
    label: str,
) -> int:
    """检查并自增当日计数。

    - limit=None → 放行（不限，如 admin）
    - 已用 >= limit → raise 403
    - 否则 INCR（首次设 36h 过期，跨日失效）
    返回自增后次数。
    """
    if limit is None:
        return 0
    if redis_conn is None:
        return 0  # 无 redis 时不拦截（保证可用性）
    used = await daily_used(redis_conn, user.id, feature)
    if used >= int(limit):
        raise HTTPException(
            status_code=403,
            detail=f"{label}今日已达上限 {limit} 次",
        )
    new_val = await redis_conn.incr(_quota_key(user.id, feature))
    if int(new_val) == 1:
        # 首次写入设过期（36h，覆盖到次日结束）
        await redis_conn.expire(_quota_key(user.id, feature), 36 * 3600)
    return int(new_val)

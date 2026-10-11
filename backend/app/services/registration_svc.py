"""注册策略校验 —— 开关、日限额、重置窗口"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.system_settings_svc import (
    current_register_window_start,
    ensure_system_settings,
    settings_to_dict,
)


def _window_start_utc(reset_hour: int) -> datetime:
    """注册窗口起点转 UTC（naive 比较时用 aware）"""
    local_start = current_register_window_start(reset_hour)
    return local_start.astimezone(timezone.utc)


async def get_public_registration_status(session: AsyncSession) -> dict:
    """公开注册状态（无需登录）"""
    settings = await ensure_system_settings(session)
    window_start = _window_start_utc(settings.register_reset_hour)

    # 兼容历史 naive UTC 写入
    count_stmt = select(func.count()).select_from(User).where(
        User.created_at >= window_start.replace(tzinfo=None)
    )
    # 同时兼容 aware 列：再 OR 一次带时区
    # PostgreSQL timestamptz 与 naive 比较时会按 session timezone；此处用 UTC naive 更稳
    registered_in_window = int((await session.execute(count_stmt)).scalar_one())

    limit = int(settings.daily_register_limit)
    remaining = None
    if limit > 0:
        remaining = max(0, limit - registered_in_window)

    can_register = bool(settings.registration_enabled)
    reason = ""
    if not settings.registration_enabled:
        can_register = False
        reason = "系统已关闭注册"
    elif limit > 0 and registered_in_window >= limit:
        can_register = False
        reason = f"今日注册名额已满（{limit} 人），请 {settings.register_reset_hour:02d}:00 后重试"

    return {
        "registration_enabled": bool(settings.registration_enabled),
        "daily_register_limit": limit,
        "register_reset_hour": int(settings.register_reset_hour),
        "registered_in_window": registered_in_window,
        "remaining": remaining,
        "can_register": can_register,
        "reason": reason,
        "system_name": settings.system_name,
        "window_start": window_start.isoformat().replace("+00:00", "Z"),
    }


async def assert_can_register(session: AsyncSession) -> None:
    """注册前硬校验，不通过则抛 403"""
    status_info = await get_public_registration_status(session)
    if not status_info["can_register"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=status_info["reason"] or "当前不可注册",
        )

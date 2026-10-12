"""交易时段 —— OKX 加密 24/7，无夜盘/无休市

替代原期货时段配置。OKX 现货与永续全年无休，
因此所有时段函数退化为「恒在交易中 + 墙钟对齐」。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

# 北京时间（UTC+8）
_BJ_TZ = timezone(timedelta(hours=8))

# OKX 24/7：恒定
ALWAYS_OPEN = True


def beijing_now() -> datetime:
    """当前北京时间（带时区）"""
    return datetime.now(_BJ_TZ)


def is_trading_now(at: datetime | None = None) -> bool:
    """OKX 全年无休"""
    return True


def is_trading_hours() -> bool:
    """OKX 全年无休"""
    return True


def is_symbol_trading(symbol: str, now: datetime | None = None) -> bool:
    """OKX 标的全年无休"""
    return True


def get_session_status(
    symbol: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """返回标的交易时段状态详情（24/7 恒开）"""
    bj = (now or datetime.now(timezone.utc)).astimezone(_BJ_TZ)
    s = str(symbol or "").strip().lower()
    return {
        "symbol": s,
        "product_code": s.split("-")[0].upper() if "-" in s else s.upper(),
        "profile": "24/7",
        "profile_label": "24/7 连续交易",
        "is_open": True,
        "reason": "交易中",
        "now_bj": bj.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": bj.weekday(),
        "sessions": [{"start": "00:00", "end": "24:00", "cross_midnight": False}],
        "message": "24/7 交易中",
    }


def is_near_day_close(within_minutes: int = 5) -> bool:
    """24/7 无日盘收盘"""
    return False


def get_trading_day(now: datetime) -> datetime:
    """返回当前时间所属交易日（自然日零点，北京时间）"""
    bj = now.astimezone(_BJ_TZ)
    d = bj.date()
    return datetime(d.year, d.month, d.day, tzinfo=_BJ_TZ)


def trading_day_of_bar_time(bar_time: str) -> str:
    """K 线 bar 时间串 → 所属交易日（YYYY-MM-DD）"""
    text = str(bar_time or "").strip()
    if len(text) >= 10:
        return text[:10]
    return ""


def period_end_for_product(product_code: str, at: datetime, minutes: int) -> datetime | None:
    """当前多分钟 K 线的结束时刻：24/7 下即墙钟上取整到 minutes 边界"""
    if minutes <= 0:
        return None
    base = at.replace(second=0, microsecond=0)
    remainder = base.minute % minutes
    if remainder == 0 and at.second == 0:
        return base
    return base + timedelta(minutes=minutes - remainder)


def period_start_for_product(product_code: str, at: datetime, minutes: int) -> datetime | None:
    """at 所属多分钟桶的起点：24/7 下即墙钟下取整"""
    if minutes <= 0:
        return None
    base = at.replace(second=0, microsecond=0)
    return base - timedelta(minutes=base.minute % minutes)


def fold_tick_minute_edge(product_code: str, at: datetime) -> datetime:
    """24/7 无收盘打印语义，原样返回"""
    return at

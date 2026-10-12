"""分钟线历史 PostgreSQL 查询层 —— 从 kline_minute 表读写 TqSdk 导入的分钟线

仿 services/kline_history.py（日线）。本期只入库 1m，查询时按需返回 1m，
多周期由调用方用 aggregate_from_1m 现算。

存储口径（勿改）：ts 列为 timestamptz，但写入方把北京墙钟 naive 串按 UTC
存入（asyncpg 对 naive 的默认解释），读取方 to_char/strftime 原样取回墙钟串
——两端自洽往返。若需改为真正带时区存储，必须一次性迁移全部存量行并同步
改 upsert_minute_bars* / _row_to_bar / backfill_tickdata_1m_from_mainpg。
bar 的 time 键一律为周期起点（bob）口径。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kline_minute import KlineMinute


async def query_minute_history(
    session: AsyncSession,
    code: str,
    period: str,
    end_time: str | None = None,
    limit: int = 8964,
) -> list[dict[str, Any]]:
    """查询 PG 中的分钟线历史

    Args:
        code: 品种代码，如 "rb"
        period: 周期，如 "1m"
        end_time: 查询此时间之前的记录（含），格式 "2026-07-31 23:59:59" 或 None=最新
        limit: 最多返回条数

    Returns:
        标准 bar 列表 [{time,open,high,low,close,volume}]，按时间升序
    """
    stmt = (
        select(KlineMinute)
        .where(
            KlineMinute.code == code,
            KlineMinute.period == period,
        )
        .order_by(KlineMinute.ts.desc())
        .limit(limit)
    )
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            stmt = stmt.where(KlineMinute.ts <= end_dt)
        except ValueError:
            pass
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_row_to_bar(r) for r in reversed(rows)]


async def get_latest_minute_ts(
    session: AsyncSession,
    code: str,
    period: str = "1m",
) -> str | None:
    """查询品种在某周期下 PG 中的最新时间戳"""
    stmt = select(func.max(KlineMinute.ts)).where(
        KlineMinute.code == code,
        KlineMinute.period == period,
    )
    result = await session.execute(stmt)
    latest = result.scalar_one_or_none()
    return latest.strftime("%Y-%m-%d %H:%M:%S") if latest else None


async def get_minute_coverage(
    session: AsyncSession,
    code: str,
    period: str = "1m",
) -> dict[str, Any] | None:
    """查询品种分钟线数据覆盖范围（最早/最新/条数），供前端提示"""
    stmt = select(
        func.min(KlineMinute.ts).label("from"),
        func.max(KlineMinute.ts).label("to"),
        func.count().label("n"),
    ).where(
        KlineMinute.code == code,
        KlineMinute.period == period,
    )
    result = await session.execute(stmt)
    row = result.fetchone()
    if row is None or row.n == 0:
        return None
    return {
        "from": row.from_.strftime("%Y-%m-%d %H:%M:%S") if row.from_ else None,
        "to": row.to.strftime("%Y-%m-%d %H:%M:%S") if row.to else None,
        "count": int(row.n),
    }


async def upsert_minute_bars(
    session: AsyncSession,
    code: str,
    symbol: str,
    period: str,
    bars: list[dict[str, Any]],
) -> int:
    """批量写入分钟线（ON CONFLICT 去重），返回新增条数"""
    if not bars:
        return 0
    rows = []
    for b in bars:
        try:
            ts = datetime.fromisoformat(str(b["time"]).replace(" ", "T"))
        except ValueError:
            continue
        rows.append(
            {
                "code": code,
                "symbol": symbol,
                "period": period,
                "ts": ts,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b.get("volume", 0) or 0),
                "hold": int(b.get("hold", 0) or 0),
            }
        )
    if not rows:
        return 0
    # 分批写入：asyncpg 单次参数上限 32767，每行 10 列，
    # 每批最多 2000 行（2000×10=20000 参数，安全余量）
    BATCH_SIZE = 2000
    total_inserted = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        stmt = pg_insert(KlineMinute).values(batch)
        stmt = stmt.on_conflict_do_nothing(
            constraint="uq_code_period_ts"
        )
        result = await session.execute(stmt)
        total_inserted += result.rowcount or 0
    await session.commit()
    return total_inserted


async def upsert_minute_bars_update(
    session: AsyncSession,
    code: str,
    symbol: str,
    period: str,
    bars: list[dict[str, Any]],
) -> int:
    """批量 upsert 分钟线（ON CONFLICT DO UPDATE，覆盖已有数据）

    TqSdk 定时修正用此函数：交叉验证后的权威数据覆盖 SimNow 实时写入的数据。
    唯一约束：uq_code_period_ts (code, period, ts)。
    """
    if not bars:
        return 0
    rows = []
    for b in bars:
        try:
            ts = datetime.fromisoformat(str(b["time"]).replace(" ", "T"))
        except ValueError:
            continue
        rows.append(
            {
                "code": code,
                "symbol": symbol,
                "period": period,
                "ts": ts,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": int(b.get("volume", 0) or 0),
                "hold": int(b.get("hold", b.get("open_interest", 0)) or 0),
            }
        )
    if not rows:
        return 0
    BATCH_SIZE = 2000
    total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        stmt = pg_insert(KlineMinute).values(batch)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_code_period_ts",
            set_={
                "symbol": stmt.excluded.symbol,
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "hold": stmt.excluded.hold,
            },
        )
        result = await session.execute(stmt)
        total += result.rowcount or 0
    await session.commit()
    return total


def _row_to_bar(row: KlineMinute) -> dict[str, Any]:
    """ORM 行 → 标准 bar 格式"""
    return {
        "time": row.ts.strftime("%Y-%m-%d %H:%M:%S") if row.ts else "",
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
    }


_PERIOD_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60, "4h": 240}


def aggregate_from_1m(
    bars_1m: list[dict[str, Any]],
    period: str,
    symbol: str = "",
) -> list[dict[str, Any]]:
    """从 1m K 线聚合为多分钟 K 线"""
    minutes = _PERIOD_MINUTES.get(str(period).lower())
    if minutes is None or minutes <= 1 or not bars_1m:
        return list(bars_1m)

    from collections import OrderedDict
    from datetime import timedelta
    from app.services.trading_hours import period_start_for_product

    buckets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for bar in bars_1m:
        t_str = str(bar.get("time") or "")
        try:
            dt = datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, IndexError):
            continue
        try:
            o = float(bar.get("open") or 0)
            h = float(bar.get("high") or 0)
            l = float(bar.get("low") or 0)
            c = float(bar.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            continue

        start = period_start_for_product(symbol, dt, minutes)
        if start is None:
            total = dt.hour * 60 + dt.minute
            start_total = (total // minutes) * minutes
            base = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            start = base + timedelta(minutes=start_total)
        key = start.strftime("%Y-%m-%d %H:%M:%S")
        vol = int(bar.get("volume") or 0)
        oi = bar.get("open_interest")
        settle = bar.get("settle")
        if key not in buckets:
            buckets[key] = {
                "time": key,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
                "settle": settle,
                "open_interest": oi,
            }
            continue
        b = buckets[key]
        b["high"] = max(float(b["high"]), h)
        b["low"] = min(float(b["low"]), l)
        b["close"] = c
        b["volume"] = int(b["volume"] or 0) + vol
        if oi is not None:
            b["open_interest"] = oi
        if settle is not None:
            b["settle"] = settle
    return list(buckets.values())

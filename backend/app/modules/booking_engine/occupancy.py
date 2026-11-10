"""Chỗ chiếm (booking / sự kiện / giữ chỗ) trên tài nguyên – dùng cho kiểm D4 / D5.

Bảng ``allocation`` được T-006 hoàn thiện (cột chủ sở hữu); ở T-005 chỉ đọc các dòng ``active``.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.dto import OccupiedSlot
from app.modules.booking_engine.holds import hold_visible
from app.modules.booking_engine.models import Allocation, Hold
from app.modules.booking_engine.schedules import to_hhmm

MAX_LISTED = 6


def _local_minutes(start: datetime, end: datetime, tz: ZoneInfo) -> tuple[date, int, int]:
    s, e = start.astimezone(tz), end.astimezone(tz)
    start_min = s.hour * 60 + s.minute
    end_min = (e - datetime.combine(s.date(), time(), tz)).total_seconds() // 60
    return s.date(), start_min, int(end_min)


async def occupied_from(
    session: AsyncSession,
    tenant_id: int,
    resource_id: int,
    from_day: date,
    tz: ZoneInfo,
    outside: tuple[int, int] | None = None,
) -> list[OccupiedSlot]:
    """Chỗ chiếm còn hiệu lực bắt đầu từ ngày ``from_day`` trở đi (mọi ngày sau đó).

    ``outside=(open, close)``: giờ mới áp dụng cho **mọi ngày** từ ``from_day`` – chỉ lấy chỗ chiếm
    có phần nằm ngoài [open, close) của ngày chứa nó.
    """
    since = datetime.combine(from_day, time(), tz)
    rows = await session.scalars(
        select(Allocation)
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.resource_id == resource_id,
            Allocation.active.is_(True),
            func.lower(Allocation.time_range) >= since,
        )
        .order_by(func.lower(Allocation.time_range))
    )
    result: list[OccupiedSlot] = []
    for row in rows:
        _, start_min, end_min = _local_minutes(row.time_range.lower, row.time_range.upper, tz)
        if outside is not None and outside[0] <= start_min and end_min <= outside[1]:
            continue
        result.append(slot_of(row, tz))
    return result


async def unfinished(
    session: AsyncSession, tenant_id: int, resource_id: int, now: datetime, tz: ZoneInfo
) -> list[OccupiedSlot]:
    """Booking / sự kiện (kể cả vé) / giữ chỗ còn hiệu lực CHƯA KẾT THÚC (đang diễn ra cũng tính) –
    chặn ngừng / xóa sân. Lịch đã kết thúc trong ngày không chặn."""
    rows = await session.scalars(
        select(Allocation)
        .outerjoin(Hold, (Hold.id == Allocation.hold_id) & hold_visible(now))
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.resource_id == resource_id,
            Allocation.active.is_(True),
            func.upper(Allocation.time_range) > now,
            or_(Allocation.kind != "hold", Hold.id.is_not(None)),
        )
        .order_by(func.lower(Allocation.time_range))
    )
    return [slot_of(row, tz) for row in rows]


def slot_of(row: Allocation, tz: ZoneInfo) -> OccupiedSlot:
    day, start_min, end_min = _local_minutes(row.time_range.lower, row.time_range.upper, tz)
    return OccupiedSlot(
        code=row.owner_code,
        date=day,
        start_time=to_hhmm(start_min),
        end_time=to_hhmm(end_min),
        kind=row.kind,
    )


def listing(slots: list[OccupiedSlot]) -> dict:
    """Trường phụ cho lỗi E-CFG-3/4: tối đa 6 dòng + số còn lại ("và n khung khác")."""
    return {
        "items": [s.model_dump(mode="json") for s in slots[:MAX_LISTED]],
        "more": max(0, len(slots) - MAX_LISTED),
    }

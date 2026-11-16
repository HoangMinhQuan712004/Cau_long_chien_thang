"""Công suất theo giờ (SRS Báo cáo & phân tích BR-016, BR-017) – lưới khung 1 giờ × ngày.

Mẫu số: giờ sân mở theo lịch có hiệu lực đúng ngày đó (``resource_schedule.effective_from``),
chỉ sân đang hoạt động (không có lịch sử trạng thái sân). Tử số: chỗ chiếm ``active`` của
booking / sự kiện (mọi trạng thái thu tiền; giữ chỗ không tính), chỉ phần nằm trong giờ mở.
"""

from datetime import date, timedelta

from sqlalchemy import Date, cast, func, literal, select, true
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import Ctx
from app.modules.booking_engine.models import Allocation, Resource
from app.modules.booking_engine.report_dto import OccupancyCell, OccupancyGrid
from app.modules.booking_engine.schedules import effective_on, schedules_of

Hours = tuple[int, int]  # (phút mở, phút đóng) trong ngày


def open_fraction(hours: Hours | None, hour: int) -> float:
    """Phần giờ mở của khung ``[hour, hour+1)``: 06:30 mở -> khung 06h–07h = 0,5."""
    if hours is None:
        return 0.0
    start, end = max(hours[0], hour * 60), min(hours[1], (hour + 1) * 60)
    return max(0, end - start) / 60


def hour_rows(open_by: dict[tuple[int, date], Hours]) -> list[int]:
    """Từ giờ mở sớm nhất tới giờ đóng muộn nhất của mọi sân trong kỳ (05:00–22:00 -> 5…21)."""
    if not open_by:
        return []
    first = min(o for o, _ in open_by.values()) // 60
    last = -(-max(c for _, c in open_by.values()) // 60)  # làm tròn lên
    return list(range(first, last))


async def _open_hours(
    session: AsyncSession, tenant_id: int, resource_ids: list[int], days: list[date]
) -> dict[tuple[int, date], Hours]:
    versions = await schedules_of(session, tenant_id, resource_ids)
    result: dict[tuple[int, date], Hours] = {}
    for rid in resource_ids:
        for day in days:
            row = effective_on(versions.get(rid, []), day)
            if row is not None:
                result[(rid, day)] = (row.open_minute, row.close_minute)
    return result


async def _booked_slots(
    session: AsyncSession, ctx: Ctx, tenant_id: int, resource_ids: list[int], days: list[date]
) -> list[tuple[int, date, int]]:
    """(sân, ngày, giờ) của từng khung 1 giờ đã chiếm – chỗ chiếm luôn biên giờ tròn (CHECK)."""
    window = func.tstzrange(
        ctx.at(days[0], 0), ctx.at(days[-1] + timedelta(days=1), 0), "[)", type_=TSTZRANGE
    )
    tr = Allocation.time_range
    slots = (
        func.generate_series(
            func.lower(tr), func.upper(tr) - timedelta(hours=1), timedelta(hours=1)
        )
        .table_valued("slot")
        .render_derived()
        .lateral()
    )
    local = func.timezone(literal(ctx.tenant.timezone), slots.c.slot)
    rows = await session.execute(
        select(Allocation.resource_id, cast(local, Date), func.extract("hour", local))
        .join(slots, true())
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.active.is_(True),
            Allocation.kind.in_(("booking", "session")),
            Allocation.resource_id.in_(resource_ids),
            tr.op("&&")(window),
        )
    )
    return [(rid, day, int(hour)) for rid, day, hour in rows]


async def occupancy(
    session: AsyncSession, ctx: Ctx, tenant_id: int, date_from: date, date_to: date
) -> OccupancyGrid:
    days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    resource_ids = list(
        await session.scalars(
            select(Resource.id).where(Resource.tenant_id == tenant_id, Resource.is_active.is_(True))
        )
    )
    open_by = await _open_hours(session, tenant_id, resource_ids, days)
    hours = hour_rows(open_by)
    column = {d: j for j, d in enumerate(days)}
    row_of = {h: i for i, h in enumerate(hours)}
    booked = [[0.0] * len(days) for _ in hours]
    opened = [[0.0] * len(days) for _ in hours]
    for (_, day), span in open_by.items():
        for h in hours:
            opened[row_of[h]][column[day]] += open_fraction(span, h)
    if resource_ids:
        for rid, day, h in await _booked_slots(session, ctx, tenant_id, resource_ids, days):
            if day in column and h in row_of:
                booked[row_of[h]][column[day]] += open_fraction(open_by.get((rid, day)), h)
    cells = [
        [OccupancyCell(booked_hours=b, open_hours=o) for b, o in zip(br, orow, strict=True)]
        for br, orow in zip(booked, opened, strict=True)
    ]
    return OccupancyGrid(hours=hours, days=days, cells=cells)

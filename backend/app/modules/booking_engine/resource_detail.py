"""Ngăn chi tiết sân ở /admin/san: thông tin + giá của loại sân + lịch sắp tới; thống kê theo kỳ.

Thống kê tính như màn Báo cáo: doanh thu = booking / vé ``paid`` theo ngày chơi (vé sự kiện nhiều
sân chia theo giờ dùng sân); giờ đã đặt = chỗ chiếm ``active`` nằm trong giờ mở cửa.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine import report_occupancy, report_revenue
from app.modules.booking_engine.common import Ctx, context
from app.modules.booking_engine.config_service import (
    _resource_by_code,
    _resource_view,
)
from app.modules.booking_engine.dto import Band, DayType, ResourceOut
from app.modules.booking_engine.models import (
    BANDS,
    DAY_TYPES,
    Allocation,
    Booking,
    EventSession,
    PriceRule,
)

UPCOMING_MAX = 20
Period = Literal["week", "month", "year"]


class ResourcePriceOut(BaseModel):
    day_type: DayType
    band: Band
    price_per_hour: int


class UpcomingOut(BaseModel):
    code: str
    kind: Literal["booking", "session"]
    play_date: dt.date
    start_time: str
    end_time: str
    title: str = Field(description="Tên khách (booking) hoặc tên sự kiện")
    payment_status: str | None = Field(description="Chỉ booking: unpaid / paid / …")


class ResourceDetailOut(BaseModel):
    resource: ResourceOut
    prices: list[ResourcePriceOut] = Field(description="Giá của loại sân (chỉ xem)")
    upcoming: list[UpcomingOut] = Field(description=f"Tối đa {UPCOMING_MAX}, sớm nhất trước")


class StatsFigures(BaseModel):
    booked_hours: float
    revenue: int
    bookings_count: int


class ResourceStatsOut(StatsFigures):
    period: Period
    start: dt.date
    end: dt.date
    until: dt.date = Field(description="Ngày cuối được tính (kỳ có hôm nay -> hôm nay)")
    occupancy_pct: float = Field(description="Giờ đã đặt / giờ mở cửa × 100 (tới ``until``)")
    prev: StatsFigures = Field(description="Kỳ trước, cùng số ngày tính từ đầu kỳ")


async def resource_detail(session: AsyncSession, tenant_id: int, code: str) -> ResourceDetailOut:
    r = await _resource_by_code(session, tenant_id, code)
    ctx = await context(session, tenant_id)
    rules = await session.scalars(
        select(PriceRule).where(
            PriceRule.tenant_id == tenant_id, PriceRule.resource_type_id == r.resource_type_id
        )
    )
    order = {(d, b): i for i, (d, b) in enumerate((d, b) for d in DAY_TYPES for b in BANDS)}
    prices = sorted(
        (
            ResourcePriceOut(day_type=p.day_type, band=p.band, price_per_hour=p.price_per_hour)
            for p in rules
        ),
        key=lambda p: order.get((p.day_type, p.band), len(order)),
    )
    return ResourceDetailOut(
        resource=await _resource_view(session, tenant_id, r),
        prices=prices,
        upcoming=await _upcoming(session, ctx, tenant_id, r.id),
    )


async def _upcoming(
    session: AsyncSession, ctx: Ctx, tenant_id: int, resource_id: int
) -> list[UpcomingOut]:
    """Booking / sự kiện chưa kết thúc trên sân (chỗ chiếm ``active``)."""
    start, end = func.lower(Allocation.time_range), func.upper(Allocation.time_range)
    rows = await session.execute(
        select(Allocation.kind, start, end, Booking, EventSession)
        .outerjoin(Booking, Booking.id == Allocation.booking_id)
        .outerjoin(EventSession, EventSession.id == Allocation.session_id)
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.resource_id == resource_id,
            Allocation.active.is_(True),
            Allocation.kind.in_(("booking", "session")),
            end > ctx.now,
        )
        .order_by(start)
        .limit(UPCOMING_MAX)
    )
    result = []
    for kind, begin, finish, booking, event in rows:
        day = begin.astimezone(ctx.tz).date()
        if kind == "booking" and booking is not None:
            code, title, status = booking.code, booking.customer_name, booking.payment_status
        elif event is not None:
            code, title, status = event.code, event.name, None
        else:
            continue
        result.append(
            UpcomingOut(
                code=code,
                kind=kind,
                play_date=day,
                start_time=ctx.hhmm(day, begin),
                end_time=ctx.hhmm(day, finish),
                title=title,
                payment_status=status,
            )
        )
    return result


def period_range(period: Period, anchor: dt.date) -> tuple[dt.date, dt.date]:
    """Tuần (thứ Hai → Chủ nhật) / tháng / năm dương lịch chứa ``anchor``."""
    if period == "week":
        start = anchor - dt.timedelta(days=anchor.weekday())
        return start, start + dt.timedelta(days=6)
    if period == "month":
        start = anchor.replace(day=1)
        nxt = (start + dt.timedelta(days=32)).replace(day=1)
        return start, nxt - dt.timedelta(days=1)
    return anchor.replace(month=1, day=1), anchor.replace(month=12, day=31)


def _previous_start(period: Period, start: dt.date) -> dt.date:
    if period == "week":
        return start - dt.timedelta(days=7)
    if period == "month":
        return (start - dt.timedelta(days=1)).replace(day=1)
    return start.replace(year=start.year - 1)


async def _figures(
    session: AsyncSession,
    ctx: Ctx,
    tenant_id: int,
    resource_id: int,
    code: str,
    date_from: dt.date,
    date_to: dt.date,
) -> tuple[StatsFigures, float]:
    """(số liệu, giờ mở cửa) của sân trong [date_from, date_to]."""
    days = [date_from + dt.timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    open_by = await report_occupancy._open_hours(session, tenant_id, [resource_id], days)
    opened = sum((c - o) / 60 for o, c in open_by.values())
    booked = sum(
        report_occupancy.open_fraction(open_by.get((rid, day)), hour)
        for rid, day, hour in await report_occupancy._booked_slots(
            session, ctx, tenant_id, [resource_id], days
        )
    )
    courts = await report_revenue.by_court(session, tenant_id, date_from, date_to)
    revenue = next((c.revenue for c in courts if c.code == code), 0)
    count = await session.scalar(
        select(func.count(Booking.id)).where(
            *report_revenue._bookings(tenant_id, date_from, date_to, None),
            Booking.resource_id == resource_id,
        )
    )
    return StatsFigures(booked_hours=booked, revenue=revenue, bookings_count=count or 0), opened


async def resource_stats(
    session: AsyncSession, tenant_id: int, code: str, period: Period, anchor: dt.date | None
) -> ResourceStatsOut:
    """Kỳ chứa ``anchor`` (mặc định hôm nay), chỉ tính tới hôm nay; kỳ trước cùng số ngày."""
    r = await _resource_by_code(session, tenant_id, code)
    ctx = await context(session, tenant_id)
    start, end = period_range(period, min(anchor or ctx.today, ctx.today))
    until = min(end, ctx.today)
    current, opened = await _figures(session, ctx, tenant_id, r.id, r.code, start, until)
    prev_start = _previous_start(period, start)
    prev_end = min(prev_start + (until - start), start - dt.timedelta(days=1))
    previous, _ = await _figures(session, ctx, tenant_id, r.id, r.code, prev_start, prev_end)
    return ResourceStatsOut(
        **current.model_dump(),
        period=period,
        start=start,
        end=end,
        until=until,
        occupancy_pct=round(current.booked_hours / opened * 100, 1) if opened else 0.0,
        prev=previous,
    )

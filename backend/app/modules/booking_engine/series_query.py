"""Gói đặt theo tháng: các ngày của gói, xem trước (giá + lý do vướng), xem gói (chỉ đọc).

Xem trước đọc lịch để báo trước; chặn trùng thật là exclusion constraint lúc tạo
(``series_service``).
"""

import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.booking_engine.common import Ctx, context, has_started
from app.modules.booking_engine.config_service import _resource_by_code, price_slots
from app.modules.booking_engine.dto import QuoteItem
from app.modules.booking_engine.holds import expire_holds
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    BookingSeries,
    Resource,
)
from app.modules.booking_engine.series_dto import (
    SeriesCustomer,
    SeriesItemOut,
    SeriesOut,
    SeriesPlanIn,
    SeriesPreviewDate,
    SeriesPreviewOut,
    SeriesResource,
)


async def series_by_code(
    session: AsyncSession, tenant_id: int, code: str, lock: bool = False
) -> BookingSeries:
    """Gói theo mã (không phân biệt hoa thường); ``lock`` = ``FOR UPDATE``. Không có -> 404."""
    query = select(BookingSeries).where(
        BookingSeries.tenant_id == tenant_id, BookingSeries.code == code.strip().upper()
    )
    series = await session.scalar(query.with_for_update() if lock else query)
    if series is None:
        raise AppError("E-SERIES-3", f"Không tìm thấy gói {code}.", 404)
    return series


def plan_dates(ctx: Ctx, plan: SeriesPlanIn) -> list[date]:
    """Các ngày của gói còn đặt được: đúng thứ, trong tháng, chưa qua; hôm nay chỉ khi khung
    chưa bắt đầu (giờ VN). Tháng trước tháng này -> 422 ``E-SERIES-2``."""
    first = plan.first_day
    if plan.end_hour <= plan.start_hour:
        raise AppError("E-001", "Giờ kết thúc phải sau giờ bắt đầu.", 422)
    if first < ctx.today.replace(day=1):
        raise AppError("E-SERIES-2", "Chỉ đặt được tháng này hoặc các tháng sau.", 422)
    days = calendar.monthrange(first.year, first.month)[1]
    result = []
    for i in range(days):
        day = first.replace(day=i + 1)
        if day.isoweekday() not in plan.weekdays or day < ctx.today:
            continue
        if day == ctx.today and has_started(ctx, ctx.at(day, plan.start_hour * 60)):
            continue
        result.append(day)
    return result


async def taken_reason(
    session: AsyncSession, ctx: Ctx, r: Resource, day: date, start_hour: int, end_hour: int
) -> str | None:
    """Lý do khung đã bị chiếm (chỉ để báo – chặn thật là exclusion constraint)."""
    row = (
        await session.execute(
            select(Allocation.kind, Allocation.owner_code)
            .where(
                Allocation.tenant_id == ctx.tenant.id,
                Allocation.resource_id == r.id,
                Allocation.active.is_(True),
                Allocation.time_range.overlaps(
                    Range(ctx.at(day, start_hour * 60), ctx.at(day, end_hour * 60), bounds="[)")
                ),
            )
            .order_by(Allocation.time_range)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    kind, owner = row
    if kind == "session":
        return f"Trùng sự kiện {owner}"
    if kind == "hold":
        return "Đang có khách giữ chỗ thanh toán online"
    return f"Đã có booking {owner}"


async def price_or_reason(
    session: AsyncSession, ctx: Ctx, r: Resource, day: date, plan: SeriesPlanIn
) -> tuple[int, list[QuoteItem], str | None]:
    """(giá, các khung, lý do không bán): sân ngừng / ngoài giờ mở cửa / thiếu giá."""
    try:
        _, items = await price_slots(session, ctx.tenant, r, day, plan.start_hour, plan.end_hour)
    except AppError as e:
        return 0, [], e.message
    return sum(i.price for i in items), items, None


async def preview(session: AsyncSession, tenant_id: int, plan: SeriesPlanIn) -> SeriesPreviewOut:
    ctx = await context(session, tenant_id)
    r = await _resource_by_code(session, tenant_id, plan.resource_code)
    await expire_holds(session)
    dates = []
    for day in plan_dates(ctx, plan):
        price, _, reason = await price_or_reason(session, ctx, r, day, plan)
        if reason is None:
            reason = await taken_reason(session, ctx, r, day, plan.start_hour, plan.end_hour)
        status = "ok" if reason is None else "conflict"
        dates.append(SeriesPreviewDate(date=day, price=price, status=status, reason=reason))
    return SeriesPreviewOut(dates=dates, total_ok=sum(d.price for d in dates if d.status == "ok"))


async def get(session: AsyncSession, tenant_id: int, code: str) -> SeriesOut:
    series = await series_by_code(session, tenant_id, code)
    r = await session.get(Resource, series.resource_id)
    rows = (
        await session.execute(
            select(Booking, Allocation.active)
            .join(BookingOrder, BookingOrder.id == Booking.order_id)
            .outerjoin(
                Allocation, (Allocation.booking_id == Booking.id) & (Allocation.kind == "booking")
            )
            .where(BookingOrder.series_id == series.id)
            .order_by(Booking.play_date)
        )
    ).all()
    items = [
        SeriesItemOut(
            date=b.play_date,
            booking_code=b.code,
            price=b.amount,
            status="active" if active else "cancelled",
            payment_status=b.payment_status,
        )
        for b, active in rows
    ]
    return SeriesOut(
        code=series.code,
        resource=SeriesResource(code=r.code, name=r.name),
        month=f"{series.month:%Y-%m}",
        weekdays=list(series.weekdays),
        start_hour=series.start_hour,
        end_hour=series.end_hour,
        customer=SeriesCustomer(
            name=series.customer_name,
            phone=series.customer_phone,
            kind=series.customer_kind,
            member_code=series.member_code,
            tier=series.member_tier,
        ),
        total=series.total,
        paid_total=sum(b.amount for b, _ in rows if b.payment_status == "paid"),
        status=series.status,
        items=items,
    )

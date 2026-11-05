"""Gói đặt theo tháng tại quầy: tạo gói (xem trước / xem gói ở ``series_query``).

Mỗi ngày của gói = một đơn (``series_id``) một booking ``unpaid`` – giá chụp lúc đặt theo bảng giá
hiện hành từng ngày. Chống trùng **chỉ** bằng exclusion constraint của ``allocation``: xem trước
đọc lịch để báo trước, còn lúc tạo thì từng ngày chèn trong savepoint, vướng constraint -> gom
lý do; còn ngày vướng -> 409 ``E-SERIES-1``, không tạo ngày nào. Hàm ở đây **không commit**.
"""

from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine.audit_fields import customer_text, new_values, vnd
from app.modules.booking_engine.codes import next_code, next_series_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    Ctx,
    audit_actor,
    context,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code
from app.modules.booking_engine.dto import Actor, CustomerSnapshot, QuoteItem
from app.modules.booking_engine.holds import expire_holds
from app.modules.booking_engine.models import (
    Booking,
    BookingOrder,
    BookingSeries,
    Resource,
)
from app.modules.booking_engine.orders import add_block, emit_created, new_order, snapshot_values
from app.modules.booking_engine.series_dto import SeriesConflict, SeriesCreateIn, SeriesOut
from app.modules.booking_engine.series_query import (
    get,
    plan_dates,
    price_or_reason,
    taken_reason,
)

WEEKDAY_LABELS = {1: "T2", 2: "T3", 3: "T4", 4: "T5", 5: "T6", 6: "T7", 7: "CN"}


def _conflicts_error(conflicts: list[SeriesConflict]) -> AppError:
    return AppError(
        "E-SERIES-1",
        "Có ngày bị trùng hoặc không đặt được. Bỏ các ngày đó rồi gửi lại.",
        409,
        conflicts=[c.model_dump(mode="json") for c in conflicts],
    )


async def create(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    data: SeriesCreateIn,
    customer: CustomerSnapshot,
    note: str | None = None,
) -> SeriesOut:
    """Tạo gói: mọi ngày trong ``dates`` hoặc không ngày nào (all-or-nothing)."""
    ctx = await context(session, tenant_id)
    r = await _resource_by_code(session, tenant_id, data.resource_code)
    allowed = set(plan_dates(ctx, data))
    wanted = sorted(set(data.dates))
    if bad := [d for d in wanted if d not in allowed]:
        raise AppError(
            "E-SERIES-2",
            "Ngày không thuộc gói hoặc đã qua: " + ", ".join(f"{d:%d/%m}" for d in bad),
            422,
        )
    priced = []
    conflicts: list[SeriesConflict] = []
    for day in wanted:
        _, items, reason = await price_or_reason(session, ctx, r, day, data)
        if reason is not None:
            conflicts.append(SeriesConflict(date=day, reason=reason))
        priced.append((day, items))
    if conflicts:
        raise _conflicts_error(conflicts)

    await expire_holds(session)
    snapshot = snapshot_values(customer)
    clean_note = (note or "").strip() or None
    series = BookingSeries(
        tenant_id=tenant_id,
        code=await next_series_code(session, tenant_id, data.first_day),
        resource_id=r.id,
        month=data.first_day,
        weekdays=data.weekdays,
        start_hour=data.start_hour,
        end_hour=data.end_hour,
        total=sum(i.price for _, items in priced for i in items),
        status="active",
        note=clean_note,
        created_by_type=actor.type,
        created_by_id=actor.id,
        created_by_label=actor.label,
        **snapshot,
    )
    created: list[tuple[BookingOrder, Booking]] = []
    async with session.begin_nested():  # vướng ngày nào -> bỏ cả gói
        session.add(series)
        await session.flush()
        for day, items in priced:
            try:
                created.append(
                    await _add_day(session, ctx, actor, series, r, day, items, snapshot, clean_note)
                )
            except IntegrityError as e:
                if sqlstate(e) != EXCLUSION_VIOLATION:
                    raise
                reason = await taken_reason(session, ctx, r, day, data.start_hour, data.end_hour)
                conflicts.append(SeriesConflict(date=day, reason=reason or "Vừa có người đặt"))
        if conflicts:
            raise _conflicts_error(conflicts)

    audit(
        session,
        audit_actor(actor),
        "booking.series.create",
        "booking_series",
        series.code,
        audit_detail(
            series.code,
            customer.display_name,
            new_values(
                **{
                    "Sân": r.name,
                    "Tháng": f"{data.first_day:%m/%Y}",
                    "Thứ": ", ".join(WEEKDAY_LABELS[d] for d in data.weekdays),
                    "Khung giờ": f"{data.start_hour:02d}:00–{data.end_hour:02d}:00",
                    "Số ngày": str(len(created)),
                    "Tổng tiền": vnd(series.total),
                    "Khách": customer_text(customer),
                }
            ),
            resource=r.code,
            amount=series.total,
            booking_codes=[b.code for _, b in created],
            customer_kind=customer.kind,
            member_code=customer.member_code,
        ),
    )
    for order, booking in created:
        await emit_created(session, tenant_id, order, booking)
    await session.flush()
    return await get(session, tenant_id, series.code)


async def _add_day(
    session: AsyncSession,
    ctx: Ctx,
    actor: Actor,
    series: BookingSeries,
    r: Resource,
    day: date,
    items: list[QuoteItem],
    snapshot: dict,
    note: str | None,
) -> tuple[BookingOrder, Booking]:
    """Một ngày = 1 đơn + 1 booking + 1 chỗ chiếm, trong savepoint riêng."""
    order_code = await next_code(session, ctx.tenant.id, ctx.code_prefix, day)
    async with session.begin_nested():
        order = new_order(ctx.tenant.id, order_code, day, "counter", snapshot, actor.label)
        order.series_id = series.id
        session.add(order)
        await session.flush()
        booking = await add_block(
            session,
            ctx,
            actor,
            order,
            1,
            r.id,
            day,
            series.start_hour,
            series.end_hour,
            items,
            snapshot,
            note,
        )
    return order, booking

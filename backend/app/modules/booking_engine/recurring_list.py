"""Danh sách đơn định kỳ (T-039) – chỉ đọc.

Không lưu thêm lịch lúc tạo: thứ / giờ / khoảng ngày **suy từ các buổi** của đơn (một đơn = một
sân, mọi buổi cùng khung giờ – T-035). Trạng thái đơn tính từ trạng thái thanh toán các buổi.
"""

import re

from sqlalchemy import Integer, case, cast, distinct, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context
from app.modules.booking_engine.dto import (
    RecurringCounts,
    RecurringOrderList,
    RecurringOrderRow,
    RecurringStatus,
)
from app.modules.booking_engine.models import Booking, BookingOrder, Resource

MAX_SIZE = 50


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def list_orders(
    session: AsyncSession,
    tenant_id: int,
    status: RecurringStatus | None,
    q: str | None,
    page: int,
    size: int,
) -> RecurringOrderList:
    ctx = await context(session, tenant_id)
    size = max(1, min(size, MAX_SIZE))
    page = max(1, page)
    unpaid = func.count().filter(Booking.payment_status == "unpaid")
    uncollectible = func.count().filter(Booking.payment_status == "uncollectible")
    weekday = cast(func.extract("isodow", Booking.play_date), Integer)
    agg = (
        select(
            Booking.order_id.label("order_id"),
            func.count().label("sessions"),
            func.sum(Booking.amount).label("total"),
            func.sum(func.coalesce(Booking.list_amount, Booking.amount)).label("original"),
            func.min(Booking.play_date).label("date_from"),
            func.max(Booking.play_date).label("date_to"),
            func.min(Booking.start_at).label("first_start"),
            func.min(Booking.end_at).label("first_end"),
            func.min(Booking.resource_id).label("resource_id"),
            func.array_agg(aggregate_order_by(distinct(weekday), weekday)).label("weekdays"),
            case(
                (unpaid > 0, "unpaid"),
                (uncollectible > 0, "uncollectible"),
                else_="paid",
            ).label("status"),
        )
        .where(Booking.tenant_id == tenant_id)
        .group_by(Booking.order_id)
        .subquery()
    )
    conds = [BookingOrder.tenant_id == tenant_id, BookingOrder.kind == "recurring"]
    text = (q or "").strip()
    if text:
        found = [
            BookingOrder.code.ilike(_like(text.replace(" ", "").upper())),
            BookingOrder.customer_name.ilike(_like(text)),
        ]
        digits = re.sub(r"[\s.]", "", text)
        if digits.isdigit():
            found.append(BookingOrder.customer_phone.like(_like(digits)))
        conds.append(or_(*found))

    base = (
        select(BookingOrder, agg, Resource.code, Resource.name)
        .join(agg, agg.c.order_id == BookingOrder.id)
        .join(Resource, Resource.id == agg.c.resource_id)
        .where(*conds)
    )
    count_rows = await session.execute(
        select(agg.c.status, func.count())
        .select_from(BookingOrder)
        .join(agg, agg.c.order_id == BookingOrder.id)
        .where(*conds)
        .group_by(agg.c.status)
    )
    by_status = {s: n for s, n in count_rows}
    counts = RecurringCounts(
        all=sum(by_status.values()),
        unpaid=by_status.get("unpaid", 0),
        paid=by_status.get("paid", 0),
        uncollectible=by_status.get("uncollectible", 0),
    )
    filtered = base.where(agg.c.status == status) if status else base
    rows = await session.execute(
        filtered.order_by(BookingOrder.created_at.desc(), BookingOrder.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = []
    for order, *values in rows:
        a = dict(zip(agg.c.keys(), values[: len(agg.c)], strict=True))
        resource_code, resource_name = values[len(agg.c) :]
        first_day = a["date_from"]
        items.append(
            RecurringOrderRow(
                order_code=order.code,
                customer_name=order.customer_name,
                customer_phone=order.customer_phone,
                resource_code=resource_code,
                resource_name=resource_name,
                weekdays=[int(w) for w in a["weekdays"]],
                start_hour=ctx.minute_of(first_day, a["first_start"]) // 60,
                end_hour=ctx.minute_of(first_day, a["first_end"]) // 60,
                date_from=first_day,
                date_to=a["date_to"],
                sessions=a["sessions"],
                original_amount=int(a["original"]),
                discount_pct=order.discount_pct or 0,
                discount_amount=order.discount_amount or 0,
                total=int(a["total"]),
                status=a["status"],
                created_at=order.created_at,
                created_by=order.created_by_label,
            )
        )
    total = counts.all if status is None else getattr(counts, status)
    return RecurringOrderList(items=items, counts=counts, page=page, size=size, total=total)

"""Lịch đặt sân của hội viên + đơn của mình (T-023 AC1–AC6) – chỉ đọc.

"Của mình" = ``customer_ref`` thuộc ``refs`` của hồ sơ (cùng cách ``member_history``). Lịch công
khai không bao giờ có mã đơn của người khác; ở đây chỉ thêm mã đơn cho ô của chính mình.
"""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context, not_found
from app.modules.booking_engine.dto import (
    MemberCalendar,
    MemberCalendarResource,
    MemberOrder,
    MemberOrderItem,
    MemberSlot,
)
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    Checkout,
    EventSession,
    Hold,
    Resource,
    Ticket,
)
from app.modules.booking_engine.online_service import _order_status, public_calendar
from app.modules.booking_engine.orders import order_blocks
from app.modules.booking_engine.schedules import to_hhmm


async def member_calendar(
    session: AsyncSession, tenant_id: int, day: date, refs: list[str]
) -> MemberCalendar:
    cal = await public_calendar(session, tenant_id, day)
    ctx = await context(session, tenant_id)
    mine: dict[tuple[str, int], str] = {}
    rows = await session.execute(
        select(Booking, BookingOrder.code, Resource.code)
        .join(BookingOrder, BookingOrder.id == Booking.order_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.play_date == day,
            Booking.customer_ref.in_(refs),
            Booking.payment_status != "cancelled",
        )
    )
    for b, order_code, resource_code in rows:
        start = ctx.minute_of(day, b.start_at) // 60
        end = -(-ctx.minute_of(day, b.end_at) // 60)
        for h in range(start, end):
            mine[(resource_code, h)] = order_code
    # Ô đang giữ của chính mình (lượt chờ thanh toán còn hạn) – chưa có booking
    held: dict[tuple[str, int], str] = {}
    hold_rows = await session.execute(
        select(Allocation.time_range, Resource.code, Checkout.order_code)
        .join(Hold, Hold.id == Allocation.hold_id)
        .join(Checkout, Checkout.id == Hold.checkout_id)
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.active.is_(True),
            Checkout.play_date == day,
            Checkout.status == "pending",
            Checkout.expires_at > datetime.now(UTC),
            Checkout.customer_ref.in_(refs),
        )
    )
    for rng, resource_code, order_code in hold_rows:
        start = ctx.minute_of(day, rng.lower) // 60
        end = -(-ctx.minute_of(day, rng.upper) // 60)
        for h in range(start, end):
            held[(resource_code, h)] = order_code
    with_ticket = set(
        await session.scalars(
            select(EventSession.code)
            .join(Ticket, Ticket.session_id == EventSession.id)
            .where(
                EventSession.tenant_id == tenant_id,
                EventSession.play_date == day,
                Ticket.customer_ref.in_(refs),
                Ticket.payment_status != "cancelled",
            )
            .distinct()
        )
    )

    resources = []
    for r in cal.resources:
        slots = []
        for s in r.slots:
            slot = MemberSlot(**s.model_dump())
            if s.state == "booked" and (r.code, s.start_hour) in mine:
                slot.mine = True
                slot.order_code = mine[(r.code, s.start_hour)]
            elif s.state == "held" and (r.code, s.start_hour) in held:
                slot.holding = True
                slot.order_code = held[(r.code, s.start_hour)]
            if s.state == "event":
                slot.has_ticket = s.event_code in with_ticket
            slots.append(slot)
        resources.append(MemberCalendarResource(code=r.code, name=r.name, slots=slots))
    return MemberCalendar(
        date=cal.date, server_now=cal.server_now, columns=cal.columns, resources=resources
    )


async def member_order(
    session: AsyncSession, tenant_id: int, refs: list[str], order_code: str
) -> MemberOrder:
    """Đơn của chính hội viên theo mã đơn; không có hoặc của người khác -> 404 (AC4)."""
    ctx = await context(session, tenant_id)
    order = await session.scalar(
        select(BookingOrder).where(
            BookingOrder.tenant_id == tenant_id,
            BookingOrder.code == "".join(order_code.split()).upper(),
        )
    )
    blocks = await order_blocks(session, order.id) if order is not None else []
    if not blocks or not any(b.customer_ref in refs for b in blocks):
        raise not_found("đơn đặt sân")
    names = {
        r.id: r.name
        for r in await session.scalars(
            select(Resource).where(Resource.id.in_({b.resource_id for b in blocks}))
        )
    }
    items = []
    for b in blocks:
        s_min = ctx.minute_of(b.play_date, b.start_at)
        e_min = ctx.minute_of(b.play_date, b.end_at)
        items.append(
            MemberOrderItem(
                code=b.code,
                resource_name=names[b.resource_id],
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                hours=(e_min - s_min) // 60,
                amount=b.amount,
                pay_status=b.payment_status,
            )
        )
    return MemberOrder(
        order_code=order.code,
        play_date=order.play_date,
        source=order.channel,
        pay_status=_order_status([b.payment_status for b in blocks]),
        amount=sum(b.amount for b in blocks if b.payment_status != "cancelled"),
        items=items,
    )

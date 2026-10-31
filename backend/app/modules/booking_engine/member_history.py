"""Khoản đã thanh toán + booking sắp tới theo ``customer_ref`` (khu hội viên, T-018) – chỉ đọc.

DTO không có SĐT. ``refs`` = các ref của một hồ sơ (``[id, "phone:<sđt>"]``).
"""

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import String, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.dto import PaidItem, UpcomingBooking
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    EventSession,
    Resource,
    ResourceType,
    Ticket,
)


def _refs(model, refs: list[str]):
    return model.customer_ref == any_(bindparam("refs", sorted(set(refs)), type_=ARRAY(String)))


async def _booking_items(session: AsyncSession, tenant_id: int, refs: list[str], *where):
    rows = await session.execute(
        select(Booking, BookingOrder.code, Resource.name)
        .join(BookingOrder, BookingOrder.id == Booking.order_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(
            Booking.tenant_id == tenant_id,
            _refs(Booking, refs),
            Booking.payment_status == "paid",
            *where,
        )
    )
    return [
        PaidItem(
            kind="booking",
            code=b.code,
            order_code=order_code,
            event_name=None,
            resource_names=[name],
            play_date=b.play_date,
            start_at=b.start_at,
            end_at=b.end_at,
            amount=b.amount,
            paid_at=b.paid_at,
            payment_method=b.payment_method,
            channel=b.source,
        )
        for b, order_code, name in rows
    ]


async def _ticket_items(session: AsyncSession, tenant_id: int, refs: list[str], *where):
    rows = list(
        await session.execute(
            select(Ticket, EventSession)
            .join(EventSession, EventSession.id == Ticket.session_id)
            .where(
                Ticket.tenant_id == tenant_id,
                _refs(Ticket, refs),
                Ticket.payment_status == "paid",
                *where,
            )
        )
    )
    names = await _session_resources(session, {ev.id for _, ev in rows})
    return [
        PaidItem(
            kind="ticket",
            code=t.code,
            order_code=None,
            event_name=ev.name,
            resource_names=names.get(ev.id, []),
            play_date=ev.play_date,
            start_at=ev.start_at,
            end_at=ev.end_at,
            amount=t.amount,
            paid_at=t.paid_at,
            payment_method=t.payment_method,
            channel=t.source,
        )
        for t, ev in rows
    ]


async def _session_resources(session: AsyncSession, ids: set[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Allocation.session_id, Resource.name)
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(Allocation.session_id.in_(sorted(ids)))
        .distinct()
        .order_by(Allocation.session_id, Resource.name)
    )
    out: dict[int, list[str]] = {}
    for sid, name in rows:
        out.setdefault(sid, []).append(name)
    return out


async def paid_items(
    session: AsyncSession, tenant_id: int, refs: list[str], from_at: dt.datetime, to_at: dt.datetime
) -> list[PaidItem]:
    """Khoản đã thanh toán (booking + vé), ``paid_at`` trong ``[from_at, to_at)``, mới trước."""
    if not refs:
        return []
    items = await _booking_items(
        session, tenant_id, refs, Booking.paid_at >= from_at, Booking.paid_at < to_at
    ) + await _ticket_items(
        session, tenant_id, refs, Ticket.paid_at >= from_at, Ticket.paid_at < to_at
    )
    return sorted(items, key=lambda i: (i.paid_at, i.code), reverse=True)


async def paid_item(
    session: AsyncSession, tenant_id: int, refs: list[str], code: str
) -> PaidItem | None:
    if not refs:
        return None
    found = await _booking_items(session, tenant_id, refs, Booking.code == code)
    found = found or await _ticket_items(session, tenant_id, refs, Ticket.code == code)
    return found[0] if found else None


async def paid_months(
    session: AsyncSession, tenant_id: int, refs: list[str], since: dt.datetime, tz: ZoneInfo
) -> list[dt.date]:
    """Ngày 1 các tháng (múi giờ IANA ``tz``) có khoản đã thanh toán từ ``since``, mới trước."""
    if not refs:
        return []
    months: set[dt.date] = set()
    for model in (Booking, Ticket):
        rows = await session.scalars(
            select(
                func.distinct(func.date_trunc("month", func.timezone(tz.key, model.paid_at)))
            ).where(
                model.tenant_id == tenant_id,
                _refs(model, refs),
                model.payment_status == "paid",
                model.paid_at >= since,
            )
        )
        months |= {m.date() for m in rows}
    return sorted(months, reverse=True)


async def upcoming(
    session: AsyncSession, tenant_id: int, refs: list[str], after: dt.datetime
) -> list[UpcomingBooking]:
    """Khối booking của các ref chưa kết thúc tại ``after`` (mọi trạng thái thanh toán)."""
    if not refs:
        return []
    rows = await session.execute(
        select(Booking, BookingOrder.code, Resource.name, ResourceType.name)
        .join(BookingOrder, BookingOrder.id == Booking.order_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .join(ResourceType, ResourceType.id == Resource.resource_type_id)
        .where(Booking.tenant_id == tenant_id, _refs(Booking, refs), Booking.end_at > after)
        .order_by(Booking.start_at, Booking.code)
    )
    return [
        UpcomingBooking(
            code=b.code,
            order_code=order_code,
            resource_name=name,
            resource_type_name=type_name,
            play_date=b.play_date,
            start_at=b.start_at,
            end_at=b.end_at,
        )
        for b, order_code, name, type_name in rows
    ]

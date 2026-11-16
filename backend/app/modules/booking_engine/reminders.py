"""Khối / vé tới hạn nhắc giờ chơi (T-076 Q2, AC8–AC10). Chỉ đọc.

Nhắc khi đủ cả ba: ``start_at − 60' ≤ now`` · ``start_at − now > 15'`` (còn đúng 15' thì bỏ) ·
``created_at ≤ start_at − 60'`` (đặt sau mốc nhắc thì không nhắc). Bỏ khối / vé đã hủy và vé
của sự kiện đã hủy. Chống trùng ở lớp gọi (``notify_once`` theo mã khối / mã vé).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import Booking, EventSession, Resource, Ticket

LEAD = timedelta(minutes=60)
CUTOFF = timedelta(minutes=15)


@dataclass(frozen=True)
class DueReminder:
    code: str  # mã khối / mã vé – khóa chống trùng
    kind: str  # booking | ticket
    display_code: str  # mã đơn (khối) / mã vé – hiện trong câu
    label: str  # tên sân / tên sự kiện
    customer_ref: str  # có thể chứa SĐT: không ghi log
    start_at: datetime
    end_at: datetime


async def due(session: AsyncSession, tenant_id: int, now: datetime) -> list[DueReminder]:
    lo, hi = now + CUTOFF, now + LEAD  # lo < start_at <= hi
    bookings = await session.execute(
        select(Booking, Resource.name)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.payment_status != "cancelled",
            Booking.start_at > lo,
            Booking.start_at <= hi,
            Booking.created_at <= Booking.start_at - LEAD,
        )
        .order_by(Booking.start_at, Booking.code)
    )
    out = [
        DueReminder(
            b.code, "booking", b.code.rsplit("-", 1)[0], name, b.customer_ref, b.start_at, b.end_at
        )
        for b, name in bookings
    ]
    tickets = await session.execute(
        select(Ticket, EventSession)
        .join(EventSession, EventSession.id == Ticket.session_id)
        .where(
            Ticket.tenant_id == tenant_id,
            Ticket.payment_status != "cancelled",
            EventSession.status == "active",
            EventSession.start_at > lo,
            EventSession.start_at <= hi,
            Ticket.created_at <= EventSession.start_at - LEAD,
        )
        .order_by(EventSession.start_at, Ticket.code)
    )
    out += [
        DueReminder(t.code, "ticket", t.code, ev.name, t.customer_ref, ev.start_at, ev.end_at)
        for t, ev in tickets
    ]
    return out

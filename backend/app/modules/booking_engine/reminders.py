"""Khối / vé tới hạn nhắc giờ chơi (T-076 Q2, T-077 C). Chỉ đọc.

- **Thường** – ``created_at ≤ start − 60'``: nhắc khi ``start − 60' ≤ now`` và
  ``start − now > 15'`` (còn đúng 15' thì bỏ).
- **Sát giờ** – ``created_at > start − 60'`` và ``start − created_at > 20'``: nhắc khi
  ``start − 15' ≤ now`` và ``start − now > 5'`` (quá ``start − 5'`` thì bỏ).
- Đặt khi còn ≤ 20 phút: không nhắc. ``created_at`` = lúc tạo khối / vé (online: lúc tiền về).

Bỏ khối / vé đã hủy và vé của sự kiện đã xóa. Mỗi khối / vé một lần: chống trùng ở lớp gọi
(``notify_once`` theo mã khối / mã vé) – hai quy tắc không bao giờ cùng nhắc một khối.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import Booking, EventSession, Resource, Ticket

LEAD = timedelta(minutes=60)
CUTOFF = timedelta(minutes=15)
LATE_LEAD = timedelta(minutes=15)  # đặt sát giờ: nhắc 15' trước
LATE_CUTOFF = timedelta(minutes=5)
LATE_MIN_NOTICE = timedelta(minutes=20)  # đặt khi còn ≤ 20' thì không nhắc


def _due_window(start, created, now: datetime):
    normal = and_(created <= start - LEAD, start > now + CUTOFF, start <= now + LEAD)
    late = and_(
        created > start - LEAD,
        start - created > LATE_MIN_NOTICE,
        start > now + LATE_CUTOFF,
        start <= now + LATE_LEAD,
    )
    return or_(normal, late)


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
    bookings = await session.execute(
        select(Booking, Resource.name)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.payment_status != "cancelled",
            _due_window(Booking.start_at, Booking.created_at, now),
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
            _due_window(EventSession.start_at, Ticket.created_at, now),
        )
        .order_by(EventSession.start_at, Ticket.code)
    )
    out += [
        DueReminder(t.code, "ticket", t.code, ev.name, t.customer_ref, ev.start_at, ev.end_at)
        for t, ev in tickets
    ]
    return out

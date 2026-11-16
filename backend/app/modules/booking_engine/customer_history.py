"""Lượt đặt theo khách (chỉ đọc) – cho màn Hội viên (T-014); engine chỉ biết ``customer_ref``.

Tính mọi booking (online + tại quầy, kể cả chưa thanh toán); không tính vé sự kiện. Đơn online hết
hạn vẫn là ``hold``, không thành booking. Lượt đã hủy (T-051) không vào thống kê, vẫn vào lịch sử.
"""

from sqlalchemy import String, any_, bindparam, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context
from app.modules.booking_engine.dto import CustomerBookingRow, CustomerStats
from app.modules.booking_engine.models import Booking, BookingOrder, Checkout, Resource, Ticket


def _ref_in(refs: list[str]):
    """Một tham số mảng (``= ANY``) thay cho ``IN (…)``: nhiều ref không vượt 32.767 tham số."""
    return Booking.customer_ref == any_(bindparam("refs", sorted(set(refs)), type_=ARRAY(String)))


async def stats(session: AsyncSession, tenant_id: int, refs: list[str]) -> dict[str, CustomerStats]:
    """Số lượt + tổng phút theo từng ``customer_ref``; ref không có booking thì vắng mặt."""
    if not refs:
        return {}
    live = Booking.payment_status != "cancelled"
    minutes = func.sum(func.extract("epoch", Booking.end_at - Booking.start_at) / 60).filter(live)
    rows = await session.execute(
        select(Booking.customer_ref, func.count().filter(live), minutes, func.count())
        .where(Booking.tenant_id == tenant_id, _ref_in(refs))
        .group_by(Booking.customer_ref)
    )
    return {
        ref: CustomerStats(bookings=n, minutes=int(m or 0), listed=listed)
        for ref, n, m, listed in rows
    }


async def recent(
    session: AsyncSession, tenant_id: int, refs: list[str], limit: int, offset: int = 0
) -> list[CustomerBookingRow]:
    """``limit`` booking mới nhất (theo giờ chơi) của các ref, bỏ ``offset`` dòng đầu."""
    if not refs:
        return []
    ctx = await context(session, tenant_id)
    rows = await session.execute(
        select(Booking, Resource.name, BookingOrder.code)
        .join(Resource, Resource.id == Booking.resource_id)
        .join(BookingOrder, BookingOrder.id == Booking.order_id)
        .where(Booking.tenant_id == tenant_id, _ref_in(refs))
        .order_by(Booking.start_at.desc(), Booking.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        CustomerBookingRow(
            code=b.code,
            order_code=order_code,
            play_date=b.play_date,
            start_time=ctx.hhmm(b.play_date, b.start_at),
            end_time=ctx.hhmm(b.play_date, b.end_at),
            resource_name=name,
            amount=b.amount,
            payment_status=b.payment_status,
        )
        for b, name, order_code in rows
    ]


async def rename_customer(session: AsyncSession, tenant_id: int, refs: list[str], name: str) -> int:
    """Hồ sơ đổi Họ tên -> tên khách trên booking / vé / lượt thanh toán của các ref (T-016 AC13,
    SRS BR-004 – kể cả booking cũ). Không commit; trả số booking + vé đã đổi."""
    if not refs:
        return 0
    changed = 0
    for model in (Booking, Ticket, Checkout):
        result = await session.execute(
            update(model)
            .where(
                model.tenant_id == tenant_id,
                model.customer_ref.in_(sorted(set(refs))),
                model.customer_name != name,
            )
            .values(customer_name=name[:100])
            .execution_options(synchronize_session=False)
        )
        if model is not Checkout:
            changed += result.rowcount or 0
    return changed

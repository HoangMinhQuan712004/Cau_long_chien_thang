"""Lượt đặt theo khách (chỉ đọc) – cho màn Hội viên (T-014); engine chỉ biết ``customer_ref``.

Tính mọi booking (online + tại quầy, kể cả chưa thanh toán); không tính vé sự kiện. Booking không
có trạng thái hủy – đơn online hết hạn vẫn là ``hold``, không thành booking.
"""

from sqlalchemy import String, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context
from app.modules.booking_engine.dto import CustomerBookingRow, CustomerStats
from app.modules.booking_engine.models import Booking, Resource


def _ref_in(refs: list[str]):
    """Một tham số mảng (``= ANY``) thay cho ``IN (…)``: nhiều ref không vượt 32.767 tham số."""
    return Booking.customer_ref == any_(bindparam("refs", sorted(set(refs)), type_=ARRAY(String)))


async def stats(session: AsyncSession, tenant_id: int, refs: list[str]) -> dict[str, CustomerStats]:
    """Số lượt + tổng phút theo từng ``customer_ref``; ref không có booking thì vắng mặt."""
    if not refs:
        return {}
    minutes = func.sum(func.extract("epoch", Booking.end_at - Booking.start_at) / 60)
    rows = await session.execute(
        select(Booking.customer_ref, func.count(), minutes)
        .where(Booking.tenant_id == tenant_id, _ref_in(refs))
        .group_by(Booking.customer_ref)
    )
    return {ref: CustomerStats(bookings=n, minutes=int(m or 0)) for ref, n, m in rows}


async def recent(
    session: AsyncSession, tenant_id: int, refs: list[str], limit: int, offset: int = 0
) -> list[CustomerBookingRow]:
    """``limit`` booking mới nhất (theo giờ chơi) của các ref, bỏ ``offset`` dòng đầu."""
    if not refs:
        return []
    ctx = await context(session, tenant_id)
    rows = await session.execute(
        select(Booking, Resource.name)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(Booking.tenant_id == tenant_id, _ref_in(refs))
        .order_by(Booking.start_at.desc(), Booking.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        CustomerBookingRow(
            code=b.code,
            play_date=b.play_date,
            start_time=ctx.hhmm(b.play_date, b.start_at),
            end_time=ctx.hhmm(b.play_date, b.end_at),
            resource_name=name,
            amount=b.amount,
            payment_status=b.payment_status,
        )
        for b, name in rows
    ]

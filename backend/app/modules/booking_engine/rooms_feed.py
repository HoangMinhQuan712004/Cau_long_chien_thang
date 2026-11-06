"""Nguồn dữ liệu cho phòng chơi (T-017) – chỉ đọc.

Phòng chơi (module ``play_rooms``) không query bảng ``booking``: lấy khối booking qua hàm này.
``customer_ref`` chỉ trả qua hàm (không đi vào payload sự kiện – có thể là ``phone:…``).
"""

import datetime as dt

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.dto import RoomSource
from app.modules.booking_engine.models import Booking, BookingOrder, Resource, ResourceType


def _query(tenant_id: int) -> Select:
    return (
        select(
            Booking.code,
            Booking.customer_ref,
            Resource.code,
            Resource.name,
            ResourceType.name,
            Booking.start_at,
            Booking.end_at,
            BookingOrder.min_tier,
            BookingOrder.max_tier,
        )
        .join(BookingOrder, BookingOrder.id == Booking.order_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .join(ResourceType, ResourceType.id == Resource.resource_type_id)
        .where(Booking.tenant_id == tenant_id, Booking.payment_status != "cancelled")
        .order_by(Booking.start_at, Booking.code)
    )


def _row(r) -> RoomSource:
    return RoomSource(
        code=r[0],
        customer_ref=r[1],
        resource_code=r[2],
        resource_name=r[3],
        resource_type_name=r[4],
        start_at=r[5],
        end_at=r[6],
        min_tier=r[7],
        max_tier=r[8],
    )


async def by_codes(session: AsyncSession, tenant_id: int, codes: list[str]) -> list[RoomSource]:
    if not codes:
        return []
    rows = await session.execute(_query(tenant_id).where(Booking.code.in_(sorted(set(codes)))))
    return [_row(r) for r in rows]


async def cancelled_codes(session: AsyncSession, tenant_id: int, codes: list[str]) -> set[str]:
    """Mã nào đã bị hủy (T-051) – phòng ẩn ngay trong transaction hủy, không chờ worker."""
    if not codes:
        return set()
    return set(
        await session.scalars(
            select(Booking.code).where(
                Booking.tenant_id == tenant_id,
                Booking.code.in_(sorted(set(codes))),
                Booking.payment_status == "cancelled",
            )
        )
    )


async def ending_after(
    session: AsyncSession, tenant_id: int, after: dt.datetime, play_dates: list[dt.date]
) -> list[RoomSource]:
    """Khối booking của các ngày ``play_dates`` còn chưa kết thúc tại ``after``."""
    rows = await session.execute(
        _query(tenant_id).where(Booking.play_date.in_(play_dates), Booking.end_at > after)
    )
    return [_row(r) for r in rows]

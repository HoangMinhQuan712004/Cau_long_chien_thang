"""Hồ sơ rút gọn cho phòng chơi (T-017) – chỉ đọc, gom theo danh sách id."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Customer, CustomerAvatar


@dataclass(frozen=True)
class RoomPerson:
    customer_id: int
    display_name: str  # Biệt danh nếu có, không thì Họ tên (T-017 AC7)
    member_code: str | None
    avatar_etag: str | None
    is_active_member: bool  # hồ sơ hội viên, đang Hoạt động
    phone: str  # nội bộ – chỉ để xét liên kết tài khoản, không trả ra API
    show_on_records: bool = False  # T-030: Tắt -> "Hội viên ẩn danh" trên bảng xếp hạng
    tier: str | None = None  # T-031: hạng (trình độ) – None = chưa xếp hạng


async def people(session: AsyncSession, ids: set[int] | list[int]) -> dict[int, RoomPerson]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Customer, CustomerAvatar.etag)
        .outerjoin(CustomerAvatar, CustomerAvatar.customer_id == Customer.id)
        .where(Customer.id.in_(sorted(set(ids))))
    )
    return {
        c.id: RoomPerson(
            customer_id=c.id,
            display_name=c.nickname or c.full_name,
            member_code=c.member_code,
            avatar_etag=etag,
            is_active_member=c.kind == "member" and c.is_active,
            phone=c.phone,
            show_on_records=c.show_on_records,
            tier=c.tier,
        )
        for c, etag in rows
    }


async def id_of_ref(session: AsyncSession, ref: str) -> int | None:
    """``customer_ref`` của booking -> id hồ sơ (``phone:…`` = khách chưa có hồ sơ -> None)."""
    if not ref.isdigit():
        return None
    return await session.scalar(select(Customer.id).where(Customer.id == int(ref)))

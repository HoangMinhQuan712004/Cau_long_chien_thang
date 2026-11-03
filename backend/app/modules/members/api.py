"""Mặt tiền của module Hội viên – module khác (front_desk, seed) chỉ gọi các hàm ở đây.

Hàm ghi **không commit**; người gọi sở hữu transaction.
"""

import asyncio
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.modules.members import avatar, enrollment, profiles, self_service, service
from app.modules.members import room_people as room_people_mod
from app.modules.members.avatar import Crop, StoredAvatar
from app.modules.members.enrollment import MemberEnsured
from app.modules.members.models import TIERS, Customer
from app.modules.members.room_people import RoomPerson
from app.modules.members.schemas import CustomerIn, CustomerProfile, MemberSearchItem, Tier
from app.modules.members.self_service import SelfProfile, SelfUpdate, not_member
from app.modules.members.service import PHONE_RE, normalize_phone

__all__ = [
    "Crop",
    "Tier",
    "tier_rank",
    "MemberEnsured",
    "ensure_member_for_phone",
    "member_of_phone",
    "RoomPerson",
    "customer_id_of_ref",
    "booking_refs_of",
    "count_new_members",
    "room_people",
    "SelfProfile",
    "SelfUpdate",
    "StoredAvatar",
    "delete_avatar",
    "get_self_profile",
    "load_avatar",
    "member_id_by_phone",
    "not_member",
    "save_avatar",
    "update_self_profile",
    "CustomerIn",
    "CustomerProfile",
    "PHONE_RE",
    "find_by_phone",
    "normalize_phone",
    "MemberSearchItem",
    "resolve_customer",
    "search_members",
    "upsert_member",
    "upsert_temp",
]


async def search_members(session: AsyncSession, q: str) -> list[MemberSearchItem]:
    return await service.search_members(session, q)


async def resolve_customer(
    session: AsyncSession, data: CustomerIn, actor: AuditActor
) -> CustomerProfile:
    return await service.resolve_customer(session, data, actor)


async def upsert_member(
    session: AsyncSession,
    member_code: str,
    full_name: str,
    phone: str,
    tier: str | None,
    is_active: bool = True,
) -> None:
    await service.upsert_member(session, member_code, full_name, phone, tier, is_active)


async def upsert_temp(session: AsyncSession, full_name: str, phone: str) -> None:
    await service.upsert_temp(session, full_name, phone)


async def find_by_phone(session: AsyncSession, phone: str) -> CustomerProfile | None:
    return await service.find_by_phone(session, phone)


# ------------------------------------------------------------------ R1: đăng ký là hội viên (T-021)


async def ensure_member_for_phone(
    session: AsyncSession, phone: str, full_name: str, actor: AuditActor
) -> MemberEnsured:
    """SĐT vừa xác minh OTP -> bảo đảm có hồ sơ hội viên: tạo mới / nâng hồ sơ tạm (cùng dòng,
    giữ lịch sử) / liên kết hội viên sẵn có. Không commit."""
    return await enrollment.ensure_member_for_phone(session, phone, full_name, actor)


async def member_of_phone(session: AsyncSession, phone: str) -> MemberEnsured | None:
    return await enrollment.member_of_phone(session, phone)


# ------------------------------------------------------------------ khu hội viên (T-016)


async def member_id_by_phone(session: AsyncSession, phone: str) -> int | None:
    """Id hồ sơ **hội viên** cùng SĐT (hồ sơ tạm / không có -> None) – liên kết tài khoản web."""
    return await self_service.member_id_by_phone(session, phone)


async def get_self_profile(session: AsyncSession, customer_id: int) -> SelfProfile | None:
    return await self_service.get_profile(session, customer_id)


async def update_self_profile(
    session: AsyncSession, customer_id: int, data: SelfUpdate, actor: AuditActor
) -> tuple[SelfProfile, bool]:
    """Không commit. 422 ``fields`` (E-HV-1/10/11), 409 E-HV-12. Trả (hồ sơ, có đổi?)."""
    return await self_service.update_profile(session, customer_id, data, actor)


async def save_avatar(
    session: AsyncSession, customer_id: int, data: bytes, crop: Crop, actor: AuditActor
) -> StoredAvatar:
    """Giải mã + mã hóa lại ảnh (thread riêng), ghi DB (không commit). 422 E-HV-13."""
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.kind != "member":
        raise not_member()
    clean = await asyncio.to_thread(avatar.process, data, crop)
    return await avatar.save(session, customer, clean, actor)


async def delete_avatar(session: AsyncSession, customer_id: int, actor: AuditActor) -> bool:
    customer = await session.get(Customer, customer_id)
    if customer is None or customer.kind != "member":
        raise not_member()
    return await avatar.remove(session, customer, actor)


async def load_avatar(session: AsyncSession, customer_id: int) -> StoredAvatar | None:
    return await avatar.load(session, customer_id)


# ------------------------------------------------------------------ phòng chơi (T-017)


async def room_people(session: AsyncSession, ids: set[int] | list[int]) -> dict[int, RoomPerson]:
    """Tên hiển thị (Biệt danh / Họ tên), ảnh, còn là hội viên Hoạt động – theo id hồ sơ."""
    return await room_people_mod.people(session, ids)


def tier_rank(tier: str | None) -> int | None:
    """Thứ tự hạng theo ``TIERS`` (0 = Yếu … 7 = Chuyên nghiệp); None / tên lạ -> None (T-031)."""
    return TIERS.index(tier) if tier in TIERS else None


async def member_ids(session: AsyncSession) -> list[int]:
    """Id mọi hồ sơ hội viên (không gồm hồ sơ tạm) – cho script dữ liệu thử của module khác."""
    return list(await session.scalars(select(Customer.id).where(Customer.kind == "member")))


async def customer_id_of_ref(session: AsyncSession, ref: str) -> int | None:
    """``customer_ref`` trên booking -> id hồ sơ khách (chưa có hồ sơ -> None)."""
    return await room_people_mod.id_of_ref(session, ref)


async def booking_refs_of(session: AsyncSession, customer_id: int) -> list[str]:
    """``customer_ref`` của hồ sơ trên booking / vé: id hồ sơ + ``phone:<sđt>`` (booking online
    đặt trước khi có hồ sơ). Không có hồ sơ -> []."""
    customer = await session.get(Customer, customer_id)
    return profiles.booking_refs(customer) if customer is not None else []


# ------------------------------------------------------------------ báo cáo


async def count_new_members(session: AsyncSession, start: datetime, end: datetime) -> int:
    """Hội viên có ngày tạo trong ``[start, end)``; không tính hồ sơ tạm (SRS Báo cáo BR-008).

    Hồ sơ tạm nâng lên hội viên tính theo ngày tạo hồ sơ (không lưu ngày nâng, OQ-4).
    """
    stmt = select(func.count(Customer.id)).where(
        Customer.kind == "member", Customer.created_at >= start, Customer.created_at < end
    )
    return int(await session.scalar(stmt) or 0)


async def rackets_of(session: AsyncSession, ids: set[int] | list[int]) -> dict[int, str | None]:
    """Vợt đang dùng (chuỗi tự nhập, T-033) của các hồ sơ – thẻ Kỷ lục mới (T-036)."""
    if not ids:
        return {}
    rows = await session.execute(
        select(Customer.id, Customer.racket).where(Customer.id.in_(sorted(set(ids))))
    )
    return {cid: racket for cid, racket in rows}

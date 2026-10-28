"""Mặt tiền của module Hội viên – module khác (front_desk, seed) chỉ gọi các hàm ở đây.

Hàm ghi **không commit**; người gọi sở hữu transaction.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.modules.members import service
from app.modules.members.schemas import CustomerIn, CustomerProfile, MemberSearchItem
from app.modules.members.service import PHONE_RE, normalize_phone

__all__ = [
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

"""Tra hội viên, tạo / dùng lại hồ sơ tạm (SRS BR-007, BR-008).

Hàm ở đây **không commit** – lớp gọi sở hữu transaction (hồ sơ tạm + booking cùng commit).
"""

import re

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.core.privacy import mask_phone
from app.modules.members.models import Customer
from app.modules.members.schemas import CustomerIn, CustomerProfile, MemberSearchItem

SEARCH_LIMIT = 20
NAME_MAX = 100
PHONE_RE = re.compile(r"^0\d{9}$")
MIN_PHONE_DIGITS = 3


def normalize_phone(raw: str) -> str:
    """Bỏ khoảng trắng, dấu chấm, gạch; ``+84`` -> ``0`` (BR-008)."""
    phone = re.sub(r"[\s.\-()]", "", raw or "")
    if phone.startswith("+84"):
        phone = "0" + phone[3:]
    return phone


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _profile(c: Customer, created: bool = False) -> CustomerProfile:
    return CustomerProfile(
        ref=str(c.id),
        kind=c.kind,
        full_name=c.full_name,
        phone=c.phone,
        member_code=c.member_code,
        tier=c.tier,
        created=created,
        is_active=c.is_active,
    )


async def search_members(session: AsyncSession, q: str) -> list[MemberSearchItem]:
    """Tìm hội viên (BR-007).

    Mã HV / tên / SĐT (≥ 3 chữ số), chứa chuỗi, không phân biệt hoa thường; gồm hội viên Ngừng.
    """
    q = q.strip()
    conditions = [Customer.member_code.ilike(_like(q)), Customer.full_name.ilike(_like(q))]
    digits = normalize_phone(q)
    if digits.isdigit() and len(digits) >= MIN_PHONE_DIGITS:
        conditions.append(Customer.phone.like(_like(digits)))
    rows = await session.scalars(
        select(Customer)
        .where(Customer.kind == "member", or_(*conditions))
        .order_by(Customer.member_code)
        .limit(SEARCH_LIMIT)
    )
    return [
        MemberSearchItem(
            ref=c.member_code,
            member_code=c.member_code,
            name=c.full_name,
            phone_masked=mask_phone(c.phone),
            tier=c.tier,
            is_active=c.is_active,
        )
        for c in rows
    ]


def _missing(field: str) -> AppError:
    return AppError("E-001", f"Vui lòng nhập {field}.", 422)


async def resolve_customer(
    session: AsyncSession, data: CustomerIn, actor: AuditActor
) -> CustomerProfile:
    """Xác định khách cho lượt đặt tại quầy.

    - Hội viên: theo mã (không phân biệt hoa thường); không có -> E-014.
    - Hồ sơ tạm: SĐT trùng hội viên -> E-018; trùng hồ sơ tạm -> dùng lại, giữ tên cũ (OQ-21);
      mới -> tạo (ghi nhật ký ``member.temp.create``).
    """
    if data.member_code is not None:
        code = data.member_code.strip().upper()
        member = await session.scalar(
            select(Customer).where(Customer.kind == "member", Customer.member_code == code)
        )
        if member is None:
            raise AppError(
                "E-014", "Không tìm thấy hội viên. Kiểm tra lại hoặc chọn Hồ sơ tạm.", 422
            )
        return _profile(member)

    temp = data.temp
    full_name = " ".join(temp.full_name.split())
    if not full_name:
        raise _missing("Họ tên")
    if len(full_name) > NAME_MAX:
        raise AppError("E-001", f"Họ tên tối đa {NAME_MAX} ký tự.", 422)
    if not temp.phone.strip():
        raise _missing("Số điện thoại")
    phone = normalize_phone(temp.phone)
    if not PHONE_RE.match(phone):
        raise AppError("E-002", "Số điện thoại không hợp lệ.", 422)

    # Hai máy tạo cùng SĐT cùng lúc: ON CONFLICT DO NOTHING rồi đọc lại -> dùng chung một hồ sơ
    created_id = await session.scalar(
        insert(Customer)
        .values(kind="temp", full_name=full_name, phone=phone, is_active=True)
        .on_conflict_do_nothing(index_elements=[Customer.phone])
        .returning(Customer.id)
    )
    existing = await session.scalar(select(Customer).where(Customer.phone == phone))
    if existing.kind == "member":
        raise AppError(
            "E-018",
            f"Số điện thoại này đã là của hội viên {existing.member_code} – {existing.full_name}. "
            "Vui lòng chọn Hồ sơ hội viên.",
            409,
        )
    created = created_id is not None
    if created:
        audit(
            session,
            actor,
            "member.temp.create",
            "customer",
            None,
            {"full_name": full_name},
        )
    return _profile(existing, created=created)


async def upsert_member(
    session: AsyncSession,
    member_code: str,
    full_name: str,
    phone: str,
    tier: str | None,
    is_active: bool = True,
) -> None:
    """Seed / nhập hội viên (dữ liệu demo dev)."""
    stmt = insert(Customer).values(
        kind="member",
        member_code=member_code,
        full_name=full_name,
        phone=phone,
        tier=tier,
        is_active=is_active,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Customer.member_code],
            set_={"full_name": full_name, "tier": tier, "is_active": is_active},
        )
    )


async def upsert_temp(session: AsyncSession, full_name: str, phone: str) -> None:
    await session.execute(
        insert(Customer)
        .values(kind="temp", full_name=full_name, phone=phone, is_active=True)
        .on_conflict_do_nothing(index_elements=[Customer.phone])
    )


async def find_by_phone(session: AsyncSession, phone: str) -> CustomerProfile | None:
    """Hồ sơ theo SĐT đã chuẩn hóa – chỉ đọc (đặt online không tạo hồ sơ lúc giữ chỗ)."""
    c = await session.scalar(select(Customer).where(Customer.phone == phone))
    return _profile(c) if c else None

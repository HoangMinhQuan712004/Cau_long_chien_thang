"""R1 (T-021): tài khoản web có SĐT đã xác minh OTP = hội viên.

``ensure_member_for_phone`` bảo đảm có hồ sơ ``kind=member`` cùng SĐT:

- chưa có hồ sơ -> tạo hội viên mới (Mã HV, chưa xếp hạng, Hoạt động, Họ tên lấy từ tài khoản,
  nguồn "Tự đăng ký online");
- có **hồ sơ tạm** -> nâng lên hội viên trên **cùng dòng** (giữ lịch sử đặt sân), giữ Họ tên của
  hồ sơ, ngày tạo hội viên = hôm nay;
- đã là hội viên -> chỉ liên kết, không đổi gì (kể cả đang Ngừng – lớp gọi khóa tài khoản).

Chỉ gọi **sau khi** chính chủ SĐT nhập đúng OTP (SEC4). Màn quản trị không gọi hàm này: Thêm hội
viên trùng hồ sơ tạm vẫn báo E-MEM-1 (R2). Không commit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.modules.members.models import Customer
from app.modules.members.profiles import next_code
from app.modules.members.service import NAME_MAX, PHONE_RE, collapse_spaces

SELF_REGISTER = "self_register"
SOURCE_LABELS = {"counter": "Quầy", SELF_REGISTER: "Tự đăng ký online"}
DEFAULT_NAME = "Hội viên"

Outcome = Literal["created", "upgraded", "linked"]


@dataclass(frozen=True)
class MemberEnsured:
    customer_id: int
    member_code: str
    full_name: str
    outcome: Outcome
    is_active: bool

    @property
    def became_member(self) -> bool:
        """Vừa thành hội viên ở lần xác minh này (tạo mới hoặc nâng hồ sơ tạm)."""
        return self.outcome != "linked"


def _masked(phone: str) -> str:
    from app.core.privacy import mask_phone

    return mask_phone(phone)


async def _lock_codes(session: AsyncSession) -> None:
    """Cùng khóa với màn quản trị (cấp Mã HV) – hai luồng cùng lúc không trùng mã."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))


async def _by_phone(session: AsyncSession, phone: str) -> Customer | None:
    return await session.scalar(
        select(Customer)
        .where(Customer.phone == phone)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _ensured(c: Customer, outcome: Outcome) -> MemberEnsured:
    if c.member_code is None:  # không xảy ra: kind=member luôn có mã (CHECK)
        raise RuntimeError("member without code")
    return MemberEnsured(c.id, c.member_code, c.full_name, outcome, c.is_active)


async def ensure_member_for_phone(
    session: AsyncSession, phone: str, full_name: str, actor: AuditActor
) -> MemberEnsured:
    """R1. ``phone`` đã chuẩn hóa (``0xxxxxxxxx``); ``full_name`` = họ tên tài khoản."""
    if not PHONE_RE.match(phone):
        raise ValueError("phone must be normalized")
    await _lock_codes(session)
    existing = await _by_phone(session, phone)
    if existing is not None and existing.kind == "member":
        return _ensured(existing, "linked")

    code = await next_code(session)
    if existing is not None:  # hồ sơ tạm -> hội viên, cùng dòng
        existing.kind, existing.member_code = "member", code
        existing.source = SELF_REGISTER
        existing.created_at = datetime.now(UTC)  # ngày tạo hội viên = hôm nay
        existing.is_active = True
        existing.version += 1
        await session.flush()
        audit(
            session,
            actor,
            "member.auto_upgrade_temp",
            "customer",
            code,
            audit_detail(
                code,
                existing.full_name,
                [
                    audit_change("Loại hồ sơ", "Hồ sơ tạm", "Hội viên"),
                    audit_change("Mã HV", None, code),
                ],
                member_code=code,
                phone=_masked(phone),
                source=SELF_REGISTER,
            ),
        )
        return _ensured(existing, "upgraded")

    name = collapse_spaces(full_name)[:NAME_MAX] or DEFAULT_NAME
    created_id = await session.scalar(
        insert(Customer)
        .values(
            kind="member",
            member_code=code,
            full_name=name,
            phone=phone,
            is_active=True,
            source=SELF_REGISTER,
        )
        .on_conflict_do_nothing(index_elements=[Customer.phone])
        .returning(Customer.id)
    )
    created = await _by_phone(session, phone)
    if created is None:  # không xảy ra: vừa chèn hoặc dòng đã có
        raise RuntimeError("customer vanished")
    if created_id is None:
        # Quầy vừa tạo hồ sơ cùng SĐT (không qua khóa SĐT): lặp lại theo hồ sơ đó
        return await ensure_member_for_phone(session, phone, full_name, actor)
    audit(
        session,
        actor,
        "member.self_register",
        "customer",
        code,
        audit_detail(
            code,
            name,
            [audit_change("Họ tên", None, name), audit_change("Mã HV", None, code)],
            member_code=code,
            phone=_masked(phone),
            source=SELF_REGISTER,
        ),
    )
    return _ensured(created, "created")


async def member_of_phone(session: AsyncSession, phone: str) -> MemberEnsured | None:
    """Hồ sơ hội viên cùng SĐT (chỉ đọc) – không có / hồ sơ tạm -> None."""
    c = await session.scalar(
        select(Customer).where(Customer.phone == phone, Customer.kind == "member")
    )
    return _ensured(c, "linked") if c is not None else None

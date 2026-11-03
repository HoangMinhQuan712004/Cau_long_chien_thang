"""Hồ sơ của tôi – hội viên tự xem / sửa hồ sơ (T-016, ADR-009 sửa đổi 30/10, nền PR #21).

Cùng bản ghi ``customer`` mà màn Hội viên quản trị sửa: Họ tên, Trình độ (= Hạng, NULL = chưa
xếp), Vợt (tên vợt dạng chữ, tự nhập, không dùng danh mục – T-033). Riêng khu hội viên: biệt danh,
email liên hệ, công tắc "Hiện trên Video & kỷ lục", ``version`` (khóa lạc quan).
Hàm ghi **không commit** – lớp gọi (BFF ``member_area``) gộp cùng việc đồng bộ ``users.full_name``.
"""

from dataclasses import dataclass, field
from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_changes, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.members import rackets
from app.modules.members.models import TIERS, Customer, CustomerAvatar
from app.modules.members.profiles import booking_refs

NAME_MAX = 100
NICKNAME_MAX = 20
EMAIL_MAX = 254


@dataclass(frozen=True)
class SelfProfile:
    customer_id: int
    member_code: str
    full_name: str
    nickname: str | None
    email: str | None
    phone: str
    joined_at: datetime
    tier: str | None
    racket: str | None
    show_on_records: bool
    avatar_etag: str | None
    version: int


@dataclass(frozen=True)
class SelfUpdate:
    full_name: str
    nickname: str | None
    email: str | None
    tier: str | None
    racket: str | None
    show_on_records: bool
    version: int


@dataclass
class _Errors:
    items: list[dict] = field(default_factory=list)

    def add(self, name: str, code: str, message: str) -> None:
        self.items.append({"field": name, "code": code, "message": message})

    def raise_if_any(self) -> None:
        if self.items:
            first = self.items[0]
            raise AppError(first["code"], first["message"], 422, fields=self.items)


def not_member() -> AppError:
    return AppError("E-HV-8", "Bạn chưa là hội viên.", 403)


def stale() -> AppError:
    return AppError(
        "E-HV-12",
        "Hồ sơ của bạn vừa được cập nhật ở nơi khác. Tải lại để xem bản mới nhất.",
        409,
    )


def mask_email(email: str | None) -> str | None:
    """``minh@gmail.com`` -> ``m***@gmail.com`` (audit / log – T-016 SEC5)."""
    if not email or "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


async def member_id_by_phone(session: AsyncSession, phone: str) -> int | None:
    """Id hồ sơ **hội viên** có SĐT này (hồ sơ tạm -> None)."""
    return await session.scalar(
        select(Customer.id).where(Customer.phone == phone, Customer.kind == "member")
    )


async def _member(session: AsyncSession, customer_id: int, lock: bool = False) -> Customer | None:
    q = select(Customer).where(Customer.id == customer_id, Customer.kind == "member")
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(q)


async def _to_profile(session: AsyncSession, c: Customer) -> SelfProfile:
    etag = await session.scalar(
        select(CustomerAvatar.etag).where(CustomerAvatar.customer_id == c.id)
    )
    return SelfProfile(
        customer_id=c.id,
        member_code=c.member_code or "",
        full_name=c.full_name,
        nickname=c.nickname,
        email=c.email,
        phone=c.phone,
        joined_at=c.created_at,
        tier=c.tier,
        racket=c.racket,
        show_on_records=c.show_on_records,
        avatar_etag=etag,
        version=c.version,
    )


async def get_profile(session: AsyncSession, customer_id: int) -> SelfProfile | None:
    """Hồ sơ hội viên (kể cả Ngừng – OQ-9); không phải hội viên -> None."""
    c = await _member(session, customer_id)
    return await _to_profile(session, c) if c else None


async def _validate(
    session: AsyncSession, c: Customer, data: SelfUpdate
) -> tuple[str, str | None, str | None]:
    """Kiểm mọi ô một lần (422 ``fields``); không ghi gì (kể cả danh mục vợt) khi có lỗi."""
    errors = _Errors()
    full_name = data.full_name.strip()
    if not full_name:
        errors.add("full_name", "E-HV-1", "Vui lòng nhập Họ tên.")
    elif len(full_name) > NAME_MAX:
        errors.add("full_name", "E-HV-1", f"Họ tên tối đa {NAME_MAX} ký tự.")
    nickname = (data.nickname or "").strip() or None
    if nickname is not None and len(nickname) > NICKNAME_MAX:
        errors.add("nickname", "E-HV-1", f"Biệt danh tối đa {NICKNAME_MAX} ký tự.")
    if data.tier is None:
        if c.tier is not None:  # đang có hạng thì không bỏ trống được (BR-008)
            errors.add("tier", "E-HV-1", "Vui lòng chọn Trình độ.")
    elif data.tier not in TIERS:
        errors.add("tier", "E-HV-1", "Trình độ không hợp lệ.")
    email = (data.email or "").strip() or None
    if email is not None:
        try:
            if len(email) > EMAIL_MAX:
                raise EmailNotValidError
            validate_email(email, check_deliverability=False)
        except EmailNotValidError:
            errors.add("email", "E-HV-10", "Email không hợp lệ.")
        else:
            taken = await session.scalar(
                select(Customer.id).where(
                    func.lower(Customer.email) == email.lower(), Customer.id != c.id
                )
            )
            if taken is not None:
                errors.add("email", "E-HV-11", "Email đã được sử dụng.")
    if data.racket is not None and data.racket.strip():
        try:
            rackets.validate_name(data.racket)
        except AppError as e:
            errors.add("racket", e.code, e.detail["message"])
    errors.raise_if_any()
    return full_name, nickname, email


SELF_LABELS = {
    "full_name": "Họ tên",
    "nickname": "Biệt danh",
    "email": "Email",
    "tier": "Trình độ",
    "racket": "Vợt đang dùng",
    "show_on_records": "Hiện trên Video & kỷ lục",
}


def _shown(values: dict) -> dict:
    """Giá trị hiển thị: email che, công tắc Bật / Tắt."""
    return {
        **values,
        "email": mask_email(values["email"]),
        "show_on_records": "Bật" if values["show_on_records"] else "Tắt",
    }


async def update_profile(
    session: AsyncSession, customer_id: int, data: SelfUpdate, actor: AuditActor
) -> tuple[SelfProfile, bool]:
    """Kiểm mọi ô một lần (422 ``fields``), khóa lạc quan (409 E-HV-12). Trả (hồ sơ, đã đổi?).

    Không đổi gì -> không ghi, không tăng version, không nhật ký.
    """
    c = await _member(session, customer_id, lock=True)
    if c is None:
        raise not_member()
    if c.version != data.version:
        raise stale()
    full_name, nickname, email = await _validate(session, c, data)
    # Vợt: ô chữ tự nhập (T-033) – không ép / không thêm vào danh mục
    racket = rackets.clean_racket(data.racket)

    after = {
        "full_name": full_name,
        "nickname": nickname,
        "email": email,
        "tier": data.tier,
        "racket": racket,
        "show_on_records": data.show_on_records,
    }
    before = {name: getattr(c, name) for name in after}
    changed = [name for name, value in after.items() if before[name] != value]
    if not changed:
        return await _to_profile(session, c), False

    for name in changed:
        setattr(c, name, after[name])
    c.version += 1
    # Định dạng Lịch sử thao tác (PR #22): "Tên ô: trước → sau"; email luôn che (T-016)
    detail = audit_detail(
        c.member_code,
        c.full_name,
        audit_changes(SELF_LABELS, _shown(before), _shown(after)),
    )
    await session.flush()
    if "full_name" in changed:
        # Tên khách trên booking / vé (kể cả cũ) hiện tên mới của hồ sơ (T-016 AC13, BR-004);
        # số booking + vé đã đổi tên ghi cùng dòng nhật ký
        detail["renamed_items"] = await engine.rename_customer(session, booking_refs(c), full_name)
    audit(session, actor, "member.self_update", "customer", c.member_code, detail)
    return await _to_profile(session, c), True

"""Xác minh SĐT cho khách đã đăng nhập, gộp tài khoản Google (T-013 AC22; port PR #17).

- SĐT chưa ai dùng -> gắn vào tài khoản, ``phone_verified_at = now``.
- SĐT thuộc khách khác **và** tài khoản hiện tại là tài khoản Google chưa có SĐT -> gộp:
  xóa tài khoản Google, chuyển ``google_sub`` / ``google_email`` sang chủ SĐT, hủy mật khẩu
  của chủ SĐT (``password_cleared``), phát lại JWT cho chủ SĐT.
- Chủ SĐT là Admin / NV, bị khóa, đã có Google khác (hoặc tài khoản hiện tại không phải Google)
  -> ``E-AUTH-18``. Tài khoản đã có SĐT -> ``E-AUTH-17``.
Không kiểm "có booking" như PR: trên ``dev`` booking không gắn tài khoản.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import otp, sessions
from app.modules.auth.models import OtpPurpose, Role, User


@dataclass(frozen=True)
class CodeSent:
    resend_after: int
    test_otp: str | None


@dataclass(frozen=True)
class PhoneVerified:
    account: User  # tài khoản để phát JWT (chủ SĐT nếu gộp)
    merged: bool
    password_cleared: bool


def already_has_phone() -> AppError:
    return AppError("E-AUTH-17", "Tài khoản đã có số điện thoại.", 409)


def phone_unusable() -> AppError:
    return AppError("E-AUTH-18", "Số điện thoại không dùng được.", 409)


def _actor(user: User) -> AuditActor:
    return AuditActor(type="customer", id=user.id, label=user.full_name)


async def request_code(session: AsyncSession, user: User, phone: str, ip: str | None) -> CodeSent:
    """Gửi mã tới SĐT (chủ SĐT chỉ xét lúc nhập mã đúng – không lộ SĐT đã có chủ)."""
    if user.phone is not None:
        raise already_has_phone()
    if not settings.otp_channel_ready:
        raise otp.channel_unavailable()
    issued = await otp.issue(session, OtpPurpose.PHONE_VERIFY, phone, user.id, ip)
    await session.commit()
    await otp.deliver(issued, phone)
    return CodeSent(issued.resend_after, issued.otp if settings.OTP_TEST_MODE else None)


async def verify(session: AsyncSession, user_id: int, phone: str, code: str) -> PhoneVerified:
    """Mã đúng -> gắn SĐT hoặc gộp (commit)."""
    now = datetime.now(UTC)
    await otp.lock_phone(session, phone)  # gắn / gộp cùng SĐT chạy lần lượt
    await otp.verify(session, OtpPurpose.PHONE_VERIFY, phone, code, None, user_id=user_id)

    current = await session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or current.phone is not None:
        await session.commit()  # mã đã dùng
        raise already_has_phone()
    owner = await session.scalar(select(User).where(User.phone == phone).with_for_update())
    if owner is None:
        current.phone = phone
        current.phone_verified_at = now
        audit(session, _actor(current), "auth.phone_verified", "user", str(current.id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise phone_unusable() from None
        return PhoneVerified(current, merged=False, password_cleared=False)

    if (
        owner.role != Role.CUSTOMER
        or not owner.is_active
        or owner.google_sub is not None
        or current.google_sub is None
    ):
        await session.commit()
        raise phone_unusable()

    google_sub, google_email = current.google_sub, current.google_email
    merged_from = current.id
    # Xóa trước để giải phóng unique google_sub
    await session.delete(current)
    await session.flush()
    owner.google_sub = google_sub
    owner.google_email = google_email or owner.google_email
    owner.phone_verified_at = owner.phone_verified_at or now
    password_cleared = owner.hashed_password is not None
    await sessions.replace_password(session, owner, None)
    audit(
        session,
        _actor(owner),
        "auth.account_merged",
        "user",
        str(owner.id),
        {"merged_from_user_id": merged_from, "password_cleared": password_cleared},
    )
    await session.commit()
    await session.refresh(owner)
    return PhoneVerified(owner, merged=True, password_cleared=password_cleared)

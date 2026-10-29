"""Quên mật khẩu bằng OTP (T-013 AC14–AC18, AC29, AC30) – mọi vai.

Chống dò tài khoản: SĐT không có tài khoản vẫn nhận 202 y hệt và có dòng mã "mồi" đếm lượt
nhập sai như mã thật. Thiếu kênh gửi OTP (Zalo chưa cấu hình, không ở chế độ thử) -> 503
``E-AUTH-23``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import otp, sessions
from app.modules.auth.models import OtpPurpose, Role, User

SYSTEM = AuditActor(type="system", id=None, label="Hệ thống")


@dataclass(frozen=True)
class ResetRequested:
    resend_after: int
    test_otp: str | None


def unavailable() -> AppError:
    return AppError(
        "E-AUTH-23",
        "Chức năng quên mật khẩu đang tạm ngưng. Vui lòng liên hệ chủ sân.",
        503,
    )


async def request_reset(session: AsyncSession, phone: str, ip: str | None) -> ResetRequested:
    if not settings.otp_channel_ready:
        raise unavailable()
    user = await session.scalar(select(User).where(User.phone == phone, User.is_active))
    issued = await otp.issue(
        session, OtpPurpose.PASSWORD_RESET, phone, user.id if user else None, ip
    )
    if user is not None:
        audit(session, SYSTEM, "auth.password_reset_requested", "user", str(user.id))
    await session.commit()
    if user is None:
        return ResetRequested(issued.resend_after, None)
    is_staff = user.role in sessions.ADMIN_ROLES
    await otp.deliver(issued, phone, show_in_log=is_staff)
    # Chế độ thử: chỉ mã của KHÁCH trả trong response; Admin / NV chỉ ghi log server (AC29)
    test_otp = issued.otp if settings.OTP_TEST_MODE and user.role == Role.CUSTOMER else None
    return ResetRequested(issued.resend_after, test_otp)


async def verify_reset(session: AsyncSession, phone: str, code: str) -> str:
    """Mã đúng -> ``reset_token`` (hạn ``OTP_RESET_TOKEN_MINUTES``, dùng một lần)."""
    _, token = await otp.verify(
        session, OtpPurpose.PASSWORD_RESET, phone, code, settings.OTP_RESET_TOKEN_MINUTES
    )
    await session.commit()
    return token


def token_invalid() -> AppError:
    return AppError("E-AUTH-16", "Phiên đặt lại mật khẩu đã hết hạn. Vui lòng làm lại từ đầu.", 400)


async def confirm_reset(session: AsyncSession, reset_token: str, hashed_password: str) -> None:
    """Đổi mật khẩu, ``token_version += 1``, thu hồi mọi phiên quản trị, gỡ khóa."""
    row = await otp.redeem(session, OtpPurpose.PASSWORD_RESET, reset_token, consume=True)
    if row is None or row.user_id is None:
        await session.rollback()
        raise token_invalid()
    user = await session.scalar(
        select(User).where(User.id == row.user_id, User.is_active).with_for_update()
    )
    if user is None:
        await session.rollback()
        raise token_invalid()
    revoked = await sessions.replace_password(session, user, hashed_password)
    if user.phone == row.phone and user.phone_verified_at is None:
        user.phone_verified_at = datetime.now(UTC)  # vừa nhận mã ở SĐT này
    audit(
        session,
        AuditActor(type=str(user.role), id=user.id, label=sessions.actor_label(user)),
        "auth.password_reset_done",
        "user",
        str(user.id),
        {"revoked_sessions": revoked},
    )
    await session.commit()

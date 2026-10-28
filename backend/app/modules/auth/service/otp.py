"""Mã OTP Zalo (gửi, giới hạn, kiểm) và luồng quên mật khẩu."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal, NoReturn

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import queue
from app.core.config import settings
from app.core.security import hash_password
from app.modules.auth.models import (
    AuditAction,
    OtpPurpose,
    PasswordResetCode,
    PasswordResetRequest,
    User,
)
from app.modules.auth.service.common import (
    audit,
    hash_token,
    lock_phone,
    replace_password,
    seconds_until,
)

OtpErrorCode = Literal[
    "otp_rate_limited",
    "otp_invalid",
    "otp_expired",
    "reset_token_invalid",
    "phone_already_set",
    "phone_unusable",
    "merge_has_bookings",
]


class OtpError(Exception):
    def __init__(
        self,
        code: OtpErrorCode,
        *,
        retry_after: int | None = None,
        attempts_left: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code: OtpErrorCode = code
        self.retry_after = retry_after  # otp_rate_limited
        self.attempts_left = attempts_left  # otp_invalid


def _hash_otp(otp: str) -> str:
    """OTP chỉ 10^6 khả năng ⇒ HMAC với SECRET_KEY: lộ DB cũng không dò ngược được mã."""
    return hmac.new(settings.SECRET_KEY.encode(), otp.encode(), hashlib.sha256).hexdigest()


async def _otp_rate_limit_error(
    session: AsyncSession, phone: str, ip: str | None, now: datetime
) -> OtpError | None:
    """Giới hạn gửi mã chung: 60s/lần, N mã/giờ mỗi SĐT, N yêu cầu/giờ mỗi IP."""
    hour_ago = now - timedelta(hours=1)
    count, oldest, latest = (
        await session.execute(
            select(
                func.count(),
                func.min(PasswordResetRequest.created_at),
                func.max(PasswordResetRequest.created_at),
            ).where(PasswordResetRequest.phone == phone, PasswordResetRequest.created_at > hour_ago)
        )
    ).one()
    waits: list[datetime] = []
    if latest is not None:
        waits.append(latest + timedelta(seconds=settings.OTP_RESEND_SECONDS))
    if count >= settings.OTP_MAX_PER_HOUR:
        waits.append(oldest + timedelta(hours=1))
    if ip is not None:
        ip_count, ip_oldest = (
            await session.execute(
                select(func.count(), func.min(PasswordResetRequest.created_at)).where(
                    PasswordResetRequest.ip == ip, PasswordResetRequest.created_at > hour_ago
                )
            )
        ).one()
        if ip_count >= settings.OTP_IP_MAX_PER_HOUR:
            waits.append(ip_oldest + timedelta(hours=1))
    until = max((w for w in waits if w > now), default=None)
    if until is None:
        return None
    return OtpError("otp_rate_limited", retry_after=seconds_until(until, now))


async def start_otp_request(
    session: AsyncSession, phone: str, ip: str | None, now: datetime
) -> None:
    """Khóa SĐT, kiểm giới hạn gửi, ghi một lần yêu cầu (chưa commit)."""
    await lock_phone(session, phone)
    if error := await _otp_rate_limit_error(session, phone, ip, now):
        await session.rollback()
        raise error
    # dọn yêu cầu quá 1 giờ
    await session.execute(
        delete(PasswordResetRequest).where(
            PasswordResetRequest.created_at <= now - timedelta(hours=1)
        )
    )
    session.add(PasswordResetRequest(phone=phone, ip=ip, created_at=now))


async def issue_otp(
    session: AsyncSession,
    user_id: int,
    phone: str,
    purpose: OtpPurpose,
    ip: str | None,
    now: datetime,
) -> tuple[PasswordResetCode, str]:
    """Mã mới (chưa commit) hủy mã cùng mục đích trước đó của tài khoản."""
    otp = f"{secrets.randbelow(10**6):06d}"
    await session.execute(
        delete(PasswordResetCode).where(
            PasswordResetCode.user_id == user_id, PasswordResetCode.purpose == purpose
        )
    )
    code = PasswordResetCode(
        user_id=user_id,
        purpose=purpose,
        phone=phone,
        code_hash=_hash_otp(otp),
        expires_at=now + timedelta(minutes=settings.OTP_TTL_MINUTES),
        ip=ip,
    )
    session.add(code)
    await session.flush()
    return code, otp


async def check_otp(
    session: AsyncSession, code: PasswordResetCode | None, otp: str, now: datetime
) -> PasswordResetCode:
    """Mã còn hạn, còn lượt, đúng (so hằng thời gian); sai ⇒ trừ lượt (commit) rồi báo lỗi."""
    if code is None or code.expires_at <= now or code.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OtpError("otp_expired")
    if not hmac.compare_digest(code.code_hash, _hash_otp(otp)):
        code.attempts += 1
        await session.commit()
        raise OtpError("otp_invalid", attempts_left=settings.OTP_MAX_ATTEMPTS - code.attempts)
    return code


async def send_otp(code: PasswordResetCode, otp: str) -> None:
    """Sau commit (nghiệp vụ 6); job chỉ mang id mã – worker tra SĐT, bỏ qua mã đã bị thay."""
    await queue.enqueue("send_zalo_otp", code.id, queue.SecretArg(otp))


async def request_password_reset(session: AsyncSession, phone: str, ip: str | None) -> None:
    """Gửi OTP quên mật khẩu nếu SĐT có tài khoản; phản hồi như nhau (không lộ SĐT)."""
    now = datetime.now(UTC)
    await start_otp_request(session, phone, ip, now)
    user = await session.scalar(select(User).where(User.phone == phone, User.is_active))
    if user is None:
        await session.commit()
        return

    code, otp = await issue_otp(session, user.id, phone, OtpPurpose.PASSWORD_RESET, ip, now)
    audit(session, AuditAction.PASSWORD_RESET_REQUESTED, actor_id=user.id, target_user_id=user.id)
    await session.commit()
    await send_otp(code, otp)


async def _verify_decoy(session: AsyncSession, phone: str, now: datetime) -> NoReturn:
    """SĐT không có mã: trả lời như mã thật nhập sai (không dò được SĐT)."""
    request = await session.scalar(
        select(PasswordResetRequest)
        .where(
            PasswordResetRequest.phone == phone,
            PasswordResetRequest.created_at > now - timedelta(minutes=settings.OTP_TTL_MINUTES),
        )
        .order_by(PasswordResetRequest.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if request is None or request.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OtpError("otp_expired")
    request.attempts += 1
    await session.commit()
    raise OtpError("otp_invalid", attempts_left=settings.OTP_MAX_ATTEMPTS - request.attempts)


async def verify_password_reset(session: AsyncSession, phone: str, otp: str) -> str:
    """Mã đúng ⇒ reset token (dùng một lần, hạn OTP_RESET_TOKEN_MINUTES); sai N lần ⇒ hủy mã."""
    now = datetime.now(UTC)
    code = await session.scalar(
        select(PasswordResetCode)
        .join(User, User.id == PasswordResetCode.user_id)
        .where(
            User.phone == phone,
            User.is_active,
            PasswordResetCode.purpose == OtpPurpose.PASSWORD_RESET,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.reset_token_hash.is_(None),
        )
        .with_for_update(of=PasswordResetCode)
    )
    if code is None:
        await _verify_decoy(session, phone, now)
    code = await check_otp(session, code, otp, now)

    token = secrets.token_urlsafe(32)
    code.reset_token_hash = hash_token(token)
    code.reset_expires_at = now + timedelta(minutes=settings.OTP_RESET_TOKEN_MINUTES)
    await session.commit()
    return token


async def confirm_password_reset(session: AsyncSession, reset_token: str, password: str) -> None:
    """Đặt mật khẩu mới bằng reset token; JWT/phiên cũ hết hiệu lực."""
    now = datetime.now(UTC)
    hashed_password = hash_password(password)  # băm trước khi khóa dòng
    code = await session.scalar(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.reset_token_hash == hash_token(reset_token),
            PasswordResetCode.purpose == OtpPurpose.PASSWORD_RESET,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.reset_expires_at > now,
        )
        .with_for_update()
    )
    if code is None:
        raise OtpError("reset_token_invalid")
    # khóa dòng user như đăng nhập
    user = await session.scalar(
        select(User).where(User.id == code.user_id, User.is_active).with_for_update()
    )
    if user is None:
        raise OtpError("reset_token_invalid")

    code.used_at = now
    await replace_password(session, user, hashed_password, now)
    audit(session, AuditAction.PASSWORD_RESET_DONE, actor_id=user.id, target_user_id=user.id)
    await session.commit()

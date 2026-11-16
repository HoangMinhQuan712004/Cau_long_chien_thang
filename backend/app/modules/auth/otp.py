"""Mã OTP (T-013 AC14–AC17, AC22, AC25, AC29; port PR #17 sang hạ tầng dev).

- 6 số ngẫu nhiên, DB chỉ lưu ``HMAC-SHA256(SECRET_KEY, mã)``; hạn ``OTP_TTL_MINUTES``.
- Gửi lại sau ``OTP_RESEND_SECONDS``; ≤ ``OTP_MAX_PER_HOUR`` mã / giờ / SĐT;
  ≤ ``OTP_IP_MAX_PER_HOUR`` / giờ / IP -> 429 ``E-AUTH-13`` (``retry_after`` = chờ dài nhất).
  Đếm trên bảng ``otp_codes`` (mỗi yêu cầu một dòng, kể cả SĐT không có tài khoản); khóa SĐT
  (advisory lock) -> yêu cầu đồng thời chỉ phát một mã.
- Mã mới làm mã cũ cùng SĐT + mục đích hết hiệu lực. Sai ``OTP_MAX_ATTEMPTS`` lần -> mã chết.
- Đúng -> token dùng tiếp (DB lưu SHA-256): đặt lại mật khẩu / ``phone_token`` đặt online.
Hàm ở đây **commit** (lần nhập sai cũng phải được ghi).
"""

import hashlib
import hmac
import logging
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import queue
from app.core.config import settings
from app.core.errors import AppError
from app.core.privacy import mask_phone
from app.modules.auth.models import OtpCode, OtpPurpose
from app.modules.auth.sessions import hash_token

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedCode:
    code_id: int
    otp: str
    resend_after: int


def hash_otp(otp: str) -> str:
    """Mã chỉ có 10^6 khả năng -> HMAC với SECRET_KEY: lộ DB cũng không dò ngược được."""
    return hmac.new(settings.SECRET_KEY.encode(), otp.encode(), hashlib.sha256).hexdigest()


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


def rate_limited(retry_after: int) -> AppError:
    return AppError(
        "E-AUTH-13",
        "Bạn đã yêu cầu gửi mã quá nhiều lần. Vui lòng thử lại sau.",
        429,
        headers={"Retry-After": str(retry_after)},
        retry_after=retry_after,
    )


def code_dead() -> AppError:
    return AppError(
        "E-AUTH-15",
        "Mã xác minh đã hết hạn hoặc không còn hiệu lực. Vui lòng gửi lại mã.",
        400,
    )


def channel_unavailable() -> AppError:
    """Không có kênh gửi mã (Zalo chưa cấu hình, không ở chế độ thử) – xác minh SĐT tài khoản."""
    return AppError(
        "E-AUTH-24",
        "Chức năng xác minh số điện thoại đang tạm ngưng. Vui lòng liên hệ chủ sân.",
        503,
    )


async def lock_phone(session: AsyncSession, phone: str) -> None:
    """Khóa theo SĐT tới hết transaction (gửi mã, gắn SĐT, đăng ký)."""
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"otp:{phone}"))))


async def _check_limits(session: AsyncSession, phone: str, ip: str | None, now: datetime) -> None:
    hour_ago = now - timedelta(hours=1)
    count, oldest, latest = (
        await session.execute(
            select(func.count(), func.min(OtpCode.created_at), func.max(OtpCode.created_at)).where(
                OtpCode.phone == phone, OtpCode.created_at > hour_ago
            )
        )
    ).one()
    waits: list[datetime] = []
    if latest is not None:
        waits.append(latest + timedelta(seconds=settings.OTP_RESEND_SECONDS))
    if count >= settings.OTP_MAX_PER_HOUR:
        waits.append(oldest + timedelta(hours=1))
    if ip:
        ip_count, ip_oldest = (
            await session.execute(
                select(func.count(), func.min(OtpCode.created_at)).where(
                    OtpCode.ip == ip, OtpCode.created_at > hour_ago
                )
            )
        ).one()
        if ip_count >= settings.OTP_IP_MAX_PER_HOUR:
            waits.append(ip_oldest + timedelta(hours=1))
    until = max((w for w in waits if w > now), default=None)
    if until is not None:
        raise rate_limited(_seconds_until(until, now))


async def issue(
    session: AsyncSession,
    purpose: OtpPurpose,
    phone: str,
    user_id: int | None,
    ip: str | None,
) -> IssuedCode:
    """Kiểm giới hạn + phát mã mới (chưa commit). ``user_id`` None: SĐT không có tài khoản
    (quên mật khẩu – dòng "mồi" để trả lời y hệt) hoặc đặt online."""
    now = datetime.now(UTC)
    await lock_phone(session, phone)
    await _check_limits(session, phone, ip, now)
    # Mã mới -> mã cũ cùng SĐT + mục đích hết hiệu lực (giữ dòng để đếm giới hạn)
    await session.execute(
        update(OtpCode)
        .where(
            OtpCode.phone == phone,
            OtpCode.purpose == purpose,
            OtpCode.used_at.is_(None),
            OtpCode.token_hash.is_(None),
        )
        .values(used_at=now)
    )
    otp = f"{secrets.randbelow(10**6):06d}"
    row = OtpCode(
        purpose=purpose,
        phone=phone,
        user_id=user_id,
        code_hash=hash_otp(otp),
        expires_at=now + timedelta(minutes=settings.OTP_TTL_MINUTES),
        ip=ip,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return IssuedCode(row.id, otp, settings.OTP_RESEND_SECONDS)


async def deliver(issued: IssuedCode, phone: str, *, show_in_log: bool = False) -> None:
    """Sau commit: đẩy job gửi Zalo (tham số OTP được che). Chế độ thử + tài khoản quản trị:
    ghi mã ra log server (không trả về response – T-013 AC29)."""
    if settings.OTP_TEST_MODE and show_in_log:
        logger.warning(
            "OTP (chế độ thử) cho tài khoản quản trị %s: %s", mask_phone(phone), issued.otp
        )
    if settings.zalo_configured:
        await queue.enqueue("send_zalo_otp", issued.code_id, queue.SecretArg(issued.otp))


async def verify(
    session: AsyncSession,
    purpose: OtpPurpose,
    phone: str,
    otp: str,
    token_minutes: int | None,
    *,
    user_id: int | None = None,
) -> tuple[OtpCode, str | None]:
    """Kiểm mã mới nhất của SĐT + mục đích. Đúng -> (dòng, token nếu ``token_minutes``).

    ``user_id``: chỉ xét mã phát cho tài khoản đó (xác minh SĐT của khách đã đăng nhập).
    Sai -> trừ lượt (commit) + 400 ``E-AUTH-14`` (``attempts_left``); không có / hết hạn / hết
    lượt -> 400 ``E-AUTH-15``. Dòng "mồi" (không có tài khoản) luôn coi là sai -> y hệt mã thật.
    """
    now = datetime.now(UTC)
    conditions = [
        OtpCode.phone == phone,
        OtpCode.purpose == purpose,
        OtpCode.used_at.is_(None),
        OtpCode.token_hash.is_(None),
    ]
    if user_id is not None:
        conditions.append(OtpCode.user_id == user_id)
    row = await session.scalar(
        select(OtpCode)
        .where(*conditions)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if row is None or row.expires_at <= now or row.attempts >= settings.OTP_MAX_ATTEMPTS:
        await session.rollback()
        raise code_dead()
    decoy = purpose == OtpPurpose.PASSWORD_RESET and row.user_id is None
    if decoy or not hmac.compare_digest(row.code_hash, hash_otp(otp)):
        row.attempts += 1
        attempts_left = settings.OTP_MAX_ATTEMPTS - row.attempts
        await session.commit()
        raise AppError("E-AUTH-14", "Mã xác minh không đúng.", 400, attempts_left=attempts_left)
    token = None
    if token_minutes is not None:
        token = secrets.token_urlsafe(32)
        row.token_hash = hash_token(token)
        row.token_expires_at = now + timedelta(minutes=token_minutes)
    else:
        row.used_at = now
    return row, token


async def redeem(
    session: AsyncSession, purpose: OtpPurpose, token: str, *, consume: bool
) -> OtpCode | None:
    """Token còn hạn của mục đích -> dòng (khóa ``FOR UPDATE``); ``consume`` đánh dấu đã dùng."""
    if not token or len(token) > 128:
        return None
    now = datetime.now(UTC)
    row = await session.scalar(
        select(OtpCode)
        .where(
            OtpCode.token_hash == hash_token(token),
            OtpCode.purpose == purpose,
            OtpCode.used_at.is_(None),
            OtpCode.token_expires_at > now,
        )
        .with_for_update()
    )
    if row is not None and consume:
        row.used_at = now
    return row


async def purge_old(session: AsyncSession) -> int:
    """Job dọn mã quá 24 giờ (worker)."""
    result = await session.execute(
        delete(OtpCode).where(OtpCode.created_at < datetime.now(UTC) - timedelta(hours=24))
    )
    await session.commit()
    return result.rowcount or 0

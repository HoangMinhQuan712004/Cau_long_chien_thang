"""Xác minh SĐT cho khách chưa có SĐT (cần để đặt sân), gộp tài khoản khi SĐT đã có chủ."""

from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import (
    AuditAction,
    OtpPurpose,
    PasswordResetCode,
    Role,
    User,
)
from app.modules.auth.service.common import (
    audit,
    lock_phone,
    replace_password,
)
from app.modules.auth.service.otp import (
    OtpError,
    check_otp,
    issue_otp,
    send_otp,
    start_otp_request,
)
from app.modules.bookings.models import Booking


async def request_phone_verify(
    session: AsyncSession, user: User, phone: str, ip: str | None
) -> None:
    """Gửi OTP xác minh SĐT cho khách chưa có SĐT (chủ SĐT xét lúc nhập mã đúng)."""
    if user.phone is not None:
        raise OtpError("phone_already_set")
    now = datetime.now(UTC)
    await start_otp_request(session, phone, ip, now)
    code, otp = await issue_otp(session, user.id, phone, OtpPurpose.PHONE_VERIFY, ip, now)
    await session.commit()
    await send_otp(code, otp)


class PhoneVerifyResult(NamedTuple):
    account: User  # tài khoản để cấp JWT (tài khoản đích nếu gộp)
    merged: bool
    password_cleared: bool  # gộp vào tài khoản có mật khẩu ⇒ mật khẩu đó đã bị hủy


async def verify_phone(
    session: AsyncSession, user: User, phone: str, otp: str
) -> PhoneVerifyResult:
    """Mã đúng ⇒ gắn SĐT; SĐT của khách khác ⇒ gộp Google vào đó, hủy mật khẩu cũ của đích."""
    now = datetime.now(UTC)
    await lock_phone(session, phone)
    code = await session.scalar(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.purpose == OtpPurpose.PHONE_VERIFY,
            PasswordResetCode.phone == phone,
            PasswordResetCode.used_at.is_(None),
        )
        .with_for_update()
    )
    code = await check_otp(session, code, otp, now)
    code.used_at = now

    current = await session.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or current.phone is not None:
        await session.commit()
        raise OtpError("phone_already_set")
    owner = await session.scalar(select(User).where(User.phone == phone).with_for_update())
    if owner is None:
        current.phone = phone
        audit(
            session,
            AuditAction.PHONE_VERIFIED,
            actor_id=current.id,
            target_user_id=current.id,
            detail=phone,
        )
        try:
            await session.commit()
        except IntegrityError as e:
            # phòng hờ SĐT ghi bởi đường không khóa
            await session.rollback()
            raise OtpError("phone_unusable") from e
        return PhoneVerifyResult(current, merged=False, password_cleared=False)

    if (
        owner.role != Role.CUSTOMER
        or not owner.is_active
        or owner.google_sub is not None
        or current.google_sub is None
    ):
        await session.commit()
        raise OtpError("phone_unusable")
    # có đơn ⇒ không tự gộp
    if await session.scalar(select(Booking.id).where(Booking.customer_id == current.id).limit(1)):
        await session.commit()
        raise OtpError("merge_has_bookings")

    google_sub, google_email = current.google_sub, current.google_email
    # xóa trước để giải phóng unique google_sub
    await session.delete(current)
    await session.flush()
    owner.google_sub = google_sub
    owner.google_email = google_email or owner.google_email
    password_cleared = owner.hashed_password is not None
    await replace_password(session, owner, None, now)
    detail = f"Gắn Google từ tài khoản #{user.id}"
    audit(
        session,
        AuditAction.ACCOUNT_MERGED,
        actor_id=owner.id,
        target_user_id=owner.id,
        detail=detail + (", đã hủy mật khẩu cũ" if password_cleared else ""),
    )
    await session.commit()
    return PhoneVerifyResult(owner, merged=True, password_cleared=password_cleared)

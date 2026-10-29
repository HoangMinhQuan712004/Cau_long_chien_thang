"""Mặt tiền module Xác thực cho module khác (không truy vấn bảng ``users`` / ``otp_codes``)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.modules.auth import otp, service
from app.modules.auth.deps import AuthStateDep
from app.modules.auth.models import OtpPurpose, Role, User


async def check_password(session: AsyncSession, user_id: int, password: str) -> bool:
    """Mật khẩu đúng của tài khoản ``user_id`` (đang hoạt động)."""
    return await service.check_password(session, user_id, password)


# ------------------------------------------------------------------ SĐT khi đặt online (AC25–26)


def otp_channel_ready() -> bool:
    """Có kênh gửi OTP (Zalo đủ cấu hình hoặc chế độ thử) – điều kiện bật đặt online (AC27)."""
    return settings.otp_channel_ready


@dataclass(frozen=True)
class PhoneCodeSent:
    resend_after: int
    test_otp: str | None  # chỉ ở chế độ thử (link dev)


@dataclass(frozen=True)
class PhoneToken:
    token: str
    expires_at: datetime
    # Khách đang đăng nhập có SĐT trùng SĐT vừa xác minh -> tài khoản đã xác minh (AC40)
    account_verified: bool = False


async def send_booking_phone_code(
    session: AsyncSession, phone: str, ip: str | None
) -> PhoneCodeSent:
    """Gửi OTP xác minh SĐT trước khi đặt online (commit). 429 ``E-AUTH-13``."""
    issued = await otp.issue(session, OtpPurpose.BOOKING_PHONE, phone, None, ip)
    await session.commit()
    await otp.deliver(issued, phone)
    return PhoneCodeSent(issued.resend_after, issued.otp if settings.OTP_TEST_MODE else None)


async def verify_booking_phone(
    session: AsyncSession, phone: str, code: str, customer_id: int | None = None
) -> PhoneToken:
    """Mã đúng -> ``phone_token`` (hạn ``BOOKING_PHONE_TOKEN_MINUTES``, dùng nhiều lần trong hạn
    cho đúng SĐT này). 400 ``E-AUTH-14`` / ``E-AUTH-15``.

    ``customer_id`` (khách đang đăng nhập): SĐT tài khoản trùng SĐT vừa xác minh -> tài khoản coi
    là đã xác minh (``phone_verified_at``, AC40) – lần đặt sau bỏ qua OTP. Không gắn SĐT cho tài
    khoản chưa có SĐT, không gộp tài khoản (việc đó qua ``/auth/phone/*``).
    """
    row, token = await otp.verify(
        session, OtpPurpose.BOOKING_PHONE, phone, code, settings.BOOKING_PHONE_TOKEN_MINUTES
    )
    expires_at = row.token_expires_at
    account_verified = (
        await _mark_customer_phone_verified(session, customer_id, phone)
        if customer_id is not None
        else False
    )
    await session.commit()
    if token is None or expires_at is None:  # không xảy ra: đã truyền token_minutes
        raise RuntimeError("OTP verify did not issue a token")
    return PhoneToken(token, expires_at, account_verified)


async def _mark_customer_phone_verified(
    session: AsyncSession, customer_id: int, phone: str
) -> bool:
    """Chưa commit. Trả True nếu tài khoản (khách, đang hoạt động, SĐT trùng) đã xác minh."""
    user = await session.scalar(
        select(User)
        .where(User.id == customer_id, User.role == Role.CUSTOMER, User.is_active)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.phone != phone:
        return False
    if user.phone_verified_at is None:
        user.phone_verified_at = datetime.now(UTC)
        audit(
            session,
            AuditActor(type="customer", id=user.id, label=user.full_name),
            "auth.phone_verified",
            "user",
            str(user.id),
            {"source": "web_booking"},
        )
    return True


async def booking_phone_token_valid(session: AsyncSession, token: str | None, phone: str) -> bool:
    """``phone_token`` còn hạn và cấp cho đúng SĐT (đã chuẩn hóa) này."""
    if not token:
        return False
    row = await otp.redeem(session, OtpPurpose.BOOKING_PHONE, token, consume=False)
    return row is not None and row.phone == phone


async def _verified_customer_phone(state: AuthStateDep) -> str | None:
    user = state.user
    if (
        state.admin_session is not None
        or user is None
        or user.role != Role.CUSTOMER
        or user.phone_verified_at is None
    ):
        return None
    return user.phone


# Dependency: SĐT **đã xác minh** của khách đang đăng nhập (không đăng nhập / chưa xác minh -> None)
VerifiedCustomerPhone = Annotated[str | None, Depends(_verified_customer_phone)]


async def _signed_in_customer_id(state: AuthStateDep) -> int | None:
    user = state.user
    if state.admin_session is not None or user is None or user.role != Role.CUSTOMER:
        return None
    return user.id


# Dependency: id khách đang đăng nhập bằng JWT (không đăng nhập / phiên Admin, NV -> None)
SignedInCustomerId = Annotated[int | None, Depends(_signed_in_customer_id)]

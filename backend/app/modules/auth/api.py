"""Mặt tiền module Xác thực cho module khác (không truy vấn bảng ``users`` / ``otp_codes``)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import member_accounts, otp, service
from app.modules.auth.deps import AuthStateDep, CurrentCustomer
from app.modules.auth.models import OtpPurpose, Role


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


async def send_booking_phone_code(
    session: AsyncSession, phone: str, ip: str | None
) -> PhoneCodeSent:
    """Gửi OTP xác minh SĐT trước khi đặt online (commit). 429 ``E-AUTH-13``."""
    issued = await otp.issue(session, OtpPurpose.BOOKING_PHONE, phone, None, ip)
    await session.commit()
    await otp.deliver(issued, phone)
    return PhoneCodeSent(issued.resend_after, issued.otp if settings.OTP_TEST_MODE else None)


async def verify_booking_phone(session: AsyncSession, phone: str, code: str) -> PhoneToken:
    """Mã đúng -> ``phone_token`` (hạn ``BOOKING_PHONE_TOKEN_MINUTES``, dùng nhiều lần trong hạn
    cho đúng SĐT này). 400 ``E-AUTH-14`` / ``E-AUTH-15``."""
    row, token = await otp.verify(
        session, OtpPurpose.BOOKING_PHONE, phone, code, settings.BOOKING_PHONE_TOKEN_MINUTES
    )
    expires_at = row.token_expires_at
    await session.commit()
    if token is None or expires_at is None:  # không xảy ra: đã truyền token_minutes
        raise RuntimeError("OTP verify did not issue a token")
    return PhoneToken(token, expires_at)


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
        or user.role != Role.MEMBER
        or user.phone_verified_at is None
        or user.must_change_password
    ):
        return None
    return user.phone


# Dependency: SĐT **đã xác minh** của khách đang đăng nhập (không đăng nhập / chưa xác minh -> None)
VerifiedCustomerPhone = Annotated[str | None, Depends(_verified_customer_phone)]


# ------------------------------------------------------------------ tài khoản hội viên (T-015)


async def ensure_customer_account(
    session: AsyncSession, phone: str, full_name: str, active: bool = True
) -> bool:
    """Thêm / nâng hội viên: SĐT chưa có tài khoản -> tạo (MK = SĐT, bắt đổi). Chưa commit."""
    return await member_accounts.ensure_customer_account(session, phone, full_name, active)


async def set_customer_account_active(session: AsyncSession, phone: str, active: bool) -> None:
    """Hội viên Ngừng / Hoạt động -> khóa / mở tài khoản khách cùng SĐT. Không commit."""
    await member_accounts.set_customer_account_active(session, phone, active)


async def _member_card_phone(user: CurrentCustomer) -> str:
    if not user.phone or not member_accounts.can_view_member_card(user):
        raise AppError(
            "E-AUTH-29", "Vui lòng xác minh số điện thoại để xem thông tin hội viên.", 403
        )
    return user.phone


# Dependency: SĐT của khách được xem thẻ Hội viên (401 / 403 E-AUTH-25 / 403 E-AUTH-29)
MemberCardPhone = Annotated[str, Depends(_member_card_phone)]

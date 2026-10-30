"""Mặt tiền module Xác thực cho module khác (không truy vấn bảng ``users`` / ``otp_codes``)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import member_accounts, membership, otp, service
from app.modules.auth.deps import AuthStateDep, CurrentCustomer, SessionDep
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
        .where(User.id == customer_id, User.role == Role.MEMBER, User.is_active)
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


async def _signed_in_customer_id(state: AuthStateDep) -> int | None:
    user = state.user
    if state.admin_session is not None or user is None or user.role != Role.MEMBER:
        return None
    return user.id


# Dependency: id khách đang đăng nhập bằng JWT (không đăng nhập / phiên Admin, NV -> None)
SignedInCustomerId = Annotated[int | None, Depends(_signed_in_customer_id)]


# ------------------------------------------------------------------ khu hội viên (T-016, ADR-009)


@dataclass(frozen=True)
class LinkedMember:
    """Khách đang đăng nhập (JWT) có hồ sơ hội viên cùng SĐT."""

    user_id: int
    customer_id: int


async def _current_member(user: CurrentCustomer, session: SessionDep) -> LinkedMember:
    """401 E-AUTH-1 (chưa đăng nhập / phiên Admin, NV) · 403 E-AUTH-25 / E-AUTH-30 (mật khẩu ban
    đầu) · 403 E-HV-8 (chưa là hội viên hoặc SĐT chưa xác minh)."""
    customer_id = await membership.member_profile_id(session, user)
    if customer_id is None:
        raise AppError("E-HV-8", "Bạn chưa là hội viên.", 403)
    return LinkedMember(user.id, customer_id)


# Dependency: hồ sơ lấy **theo phiên**, không theo tham số URL (T-016 AC2, SEC1)
CurrentMember = Annotated[LinkedMember, Depends(_current_member)]


async def _optional_member(state: AuthStateDep, session: SessionDep) -> LinkedMember | None:
    user = state.user
    if (
        user is None
        or state.admin_session is not None
        or user.must_change_password
        or member_accounts.initial_password_expired(user)
    ):
        return None
    customer_id = await membership.member_profile_id(session, user)
    return LinkedMember(user.id, customer_id) if customer_id is not None else None


# Dependency: hội viên đang đăng nhập hoặc None (vd. đọc danh mục vợt)
OptionalMember = Annotated[LinkedMember | None, Depends(_optional_member)]


async def is_member(session: AsyncSession, user: User) -> bool:
    return await membership.member_profile_id(session, user) is not None


async def set_full_name(session: AsyncSession, user_id: int, full_name: str) -> None:
    """Đồng bộ ``users.full_name`` khi hội viên đổi Họ tên (ADR-009 §2). Không commit."""
    user = await session.get(User, user_id)
    if user is not None:
        user.full_name = full_name

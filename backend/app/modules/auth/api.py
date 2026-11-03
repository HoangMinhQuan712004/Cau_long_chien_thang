"""Mặt tiền module Xác thực cho module khác (không truy vấn bảng ``users`` / ``otp_codes``)."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import cookies, demo, enroll, member_accounts, membership, otp, service, utils
from app.modules.auth import phone as phone_flow
from app.modules.auth.deps import AuthStateDep, CurrentCustomer, SessionDep
from app.modules.auth.models import OtpPurpose, Role, User

if TYPE_CHECKING:
    from app.modules.members.api import MemberEnsured


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
    # T-021 AC5: vừa thành hội viên (tạo mới / nâng hồ sơ tạm) + Mã HV của tài khoản
    became_member: bool = False
    member_code: str | None = None
    # Tài khoản Google vừa được gộp vào chủ SĐT -> lớp gọi phát lại cookie cho ``account``
    merged: bool = False
    account: User | None = None
    # Khách đang đăng nhập nhưng tài khoản không được gắn / thành hội viên: mã lý do
    # (E-AUTH-17 tài khoản có SĐT khác, E-AUTH-18 SĐT không dùng được, E-AUTH-31 hội viên Ngừng)
    reason: str | None = None


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

    ``customer_id`` (khách đang đăng nhập, T-013 AC40 + T-021 AC5):
    - SĐT tài khoản trùng SĐT vừa xác minh -> tài khoản đã xác minh; lần đặt sau bỏ qua OTP.
    - Tài khoản chưa có SĐT (Google) -> gắn SĐT theo đúng luật ``/auth/phone/verify`` (SĐT của
      khách khác thì gộp). ``E-AUTH-17`` / ``E-AUTH-18`` -> **không gắn**, lượt đặt vẫn tiếp tục.
    - Sau đó R1: SĐT đã xác minh = hội viên. Hồ sơ đang Ngừng -> tài khoản bị khóa.
    Phần liên kết chạy trong savepoint: hỏng (hiếm) thì bỏ liên kết, vẫn cấp ``phone_token``.
    """
    if customer_id is not None:
        await otp.lock_phone(session, phone)  # gắn / gộp / đăng ký cùng SĐT chạy lần lượt
    row, token = await otp.verify(
        session, OtpPurpose.BOOKING_PHONE, phone, code, settings.BOOKING_PHONE_TOKEN_MINUTES
    )
    expires_at = row.token_expires_at
    if token is None or expires_at is None:  # không xảy ra: đã truyền token_minutes
        raise RuntimeError("OTP verify did not issue a token")
    linked, reason = None, None
    if customer_id is not None:
        try:
            async with session.begin_nested():
                linked = await _link_account(session, customer_id, phone)
        except AppError as e:
            reason = e.detail["code"]
        except IntegrityError:  # quầy vừa tạo tài khoản cùng SĐT (hiếm)
            reason = phone_flow.phone_unusable().detail["code"]
    await session.commit()
    if linked is None:
        return PhoneToken(token, expires_at, reason=reason)
    account, merged, ensured = linked
    active = account.is_active
    return PhoneToken(
        token,
        expires_at,
        account_verified=active,
        became_member=active and ensured is not None and ensured.became_member,
        member_code=ensured.member_code if ensured is not None and active else None,
        merged=merged and active,
        account=account if merged and active else None,
        reason=None if active else enroll.account_locked().detail["code"],
    )


async def _link_account(
    session: AsyncSession, customer_id: int, phone: str
) -> "tuple[User, bool, MemberEnsured | None] | None":
    """Chưa commit. (tài khoản, đã gộp?, hội viên) hoặc None nếu tài khoản không liên quan.
    ``E-AUTH-17`` / ``E-AUTH-18`` ném ra trước khi đổi dữ liệu."""
    user = await phone_flow.lock_user(session, customer_id)
    if user is None or user.role != Role.MEMBER or not user.is_active:
        return None
    if user.phone is not None and user.phone != phone:
        raise phone_flow.already_has_phone()  # SĐT khác: chỉ xác minh SĐT cho lượt đặt
    if user.phone == phone and user.phone_verified_at is not None:
        result = phone_flow.PhoneVerified(user, merged=False, password_cleared=False)
    else:
        result = await phone_flow.attach(session, user, phone, source="web_booking")
    account = result.account
    ensured = await enroll.enroll(session, account)
    await session.flush()
    return account, result.merged, ensured


def set_customer_cookies(response: Response, user: User) -> None:
    """Phát lại cookie JWT khách (vd. vừa gộp tài khoản Google vào chủ SĐT khi đặt online)."""
    cookies.set_auth_cookies(response, user)


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


async def create_member_account(
    session: AsyncSession, phone: str, full_name: str, active: bool = True
) -> datetime | None:
    """Như ``ensure_customer_account`` nhưng trả **hạn đổi mật khẩu ban đầu** khi vừa tạo tài
    khoản (MK = SĐT); SĐT đã có tài khoản -> None (giữ mật khẩu cũ). Chưa commit (T-026)."""
    return await member_accounts.create_customer_account(session, phone, full_name, active)


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


def normalize_phone(raw: str) -> str | None:
    """Chuẩn hóa SĐT như đăng nhập (T-013): ``+84 912.345-678`` -> ``0912345678``; sai -> None."""
    return utils.normalize_phone(raw)


async def linked_phones(session: AsyncSession, phones: set[str]) -> set[str]:
    """SĐT (trong ``phones``) đang có tài khoản khách hoạt động được xem thẻ hội viên – điều kiện
    "hội viên có tài khoản liên kết" của phòng chơi (T-017 AC2, AC9). Chỉ đọc."""
    if not phones:
        return set()
    users = await session.scalars(
        select(User).where(
            User.phone.in_(sorted(phones)), User.role == Role.MEMBER, User.is_active.is_(True)
        )
    )
    return {u.phone for u in users if u.phone and member_accounts.can_view_member_card(u)}


async def is_member(session: AsyncSession, user: User) -> bool:
    return await membership.member_profile_id(session, user) is not None


async def set_full_name(session: AsyncSession, user_id: int, full_name: str) -> None:
    """Đồng bộ ``users.full_name`` khi hội viên đổi Họ tên (ADR-009 §2). Không commit."""
    user = await session.get(User, user_id)
    if user is not None:
        user.full_name = full_name


# ------------------------------------------------------------------ dữ liệu mẫu dev (T-034)


async def demo_foreign_phones(session: AsyncSession) -> list[str]:
    """SĐT trong dải mẫu thuộc tài khoản thật – có thì script mẫu phải dừng."""
    return await demo.foreign_demo_phones(session)


async def create_demo_account(
    session: AsyncSession, phone: str, full_name: str, password: str | None
) -> None:
    """Tài khoản mẫu đã xác minh SĐT, không bắt đổi mật khẩu; ``password=None`` -> ngẫu nhiên."""
    await demo.create_account(session, phone, full_name, password)


async def purge_demo(session: AsyncSession) -> int:
    return await demo.purge_demo(session)

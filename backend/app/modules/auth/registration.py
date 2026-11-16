"""Đăng ký tài khoản 2 bước bằng OTP – đăng ký xong là hội viên (T-021 AC1–AC4, SEC1–SEC5).

1. ``request``: gửi mã tới SĐT, giữ họ tên + mật khẩu **đã băm** gắn với mã
   (``registration_requests``); **chưa** tạo tài khoản. Không tra SĐT đã có tài khoản hay chưa:
   mọi SĐT nhận cùng một trả lời, cùng một lượng việc (băm mật khẩu, phát mã) -> không dò được
   SĐT nào đã có tài khoản (SEC2).
2. ``verify``: mã đúng -> trong **một transaction**: tạo tài khoản (SĐT đã xác minh) + R1.
   - SĐT đã có tài khoản đã xác minh / do sân tạo / Admin, NV -> ``E-AUTH-22`` (chỉ báo sau khi
     nhập đúng mã – người dò phải giữ được SIM).
   - SĐT đang thuộc tài khoản **chưa xác minh** đời cũ (đăng ký không OTP) -> người xác minh
     thắng: tài khoản cũ bị gỡ SĐT; không còn tên đăng nhập / Google thì bị vô hiệu (AC3).
   Khóa advisory theo SĐT + mã dùng một lần -> hai lần verify đồng thời chỉ tạo 1 tài khoản và
   1 hội viên (SEC5).
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import SYSTEM_ACTOR, audit, audit_change, audit_detail
from app.core.config import settings
from app.core.errors import AppError
from app.core.privacy import mask_phone
from app.core.security import hash_password
from app.modules.auth import enroll, otp
from app.modules.auth.member_accounts import same_as_phone
from app.modules.auth.models import OtpPurpose, RegistrationRequest, Role, User


@dataclass(frozen=True)
class RegisterCodeSent:
    resend_after: int
    test_otp: str | None


@dataclass(frozen=True)
class Registered:
    account: User
    member_code: str
    upgraded_from_temp: bool


def unavailable() -> AppError:
    """Không có kênh gửi OTP (production chưa có Zalo, không ở chế độ thử) – AC4."""
    return AppError(
        "E-AUTH-23",
        "Đăng ký tài khoản đang tạm ngưng. Vui lòng liên hệ quầy.",
        503,
    )


def phone_taken(phone: str) -> AppError:
    """Một lỗi cho mọi loại tài khoản đang giữ SĐT (không dò được loại). ``phone`` để FE điền
    link Quên mật khẩu."""
    return AppError(
        "E-AUTH-22",
        "Số điện thoại đã có tài khoản. Vui lòng đăng nhập hoặc dùng Quên mật khẩu.",
        409,
        phone=phone,
    )


def closed() -> AppError:
    """``POST /auth/register`` cũ (không OTP) – đã đóng (SEC1)."""
    return AppError(
        "E-AUTH-32",
        "Đăng ký cần xác minh số điện thoại. Vui lòng tải lại trang và đăng ký lại.",
        410,
    )


async def request(
    session: AsyncSession, full_name: str, phone: str, password: str, ip: str | None
) -> RegisterCodeSent:
    """Bước 1 (commit). 429 E-SEC-5 (IP) / E-AUTH-13 (OTP) · 422 E-AUTH-26 · 503 E-AUTH-23."""
    if not settings.otp_channel_ready:
        raise unavailable()
    retry_after = await ratelimit.check(
        "auth.register", ip or "unknown", settings.REGISTER_IP_MAX_PER_HOUR, 3600
    )
    if retry_after is not None:
        raise ratelimit.too_many(retry_after)
    if password == phone:
        raise same_as_phone()
    hashed = hash_password(password)
    issued = await otp.issue(session, OtpPurpose.REGISTER, phone, None, ip)
    session.add(
        RegistrationRequest(
            otp_code_id=issued.code_id,
            full_name=" ".join(full_name.split()),
            hashed_password=hashed,
        )
    )
    await session.commit()
    await otp.deliver(issued, phone)
    return RegisterCodeSent(issued.resend_after, issued.otp if settings.OTP_TEST_MODE else None)


def _releasable(owner: User) -> bool:
    """Tài khoản khách tự đăng ký đời cũ, SĐT chưa xác minh, không do sân tạo (AC3)."""
    return (
        owner.role == Role.MEMBER
        and owner.phone_verified_at is None
        and owner.member_account_at is None
    )


def release_phone(session: AsyncSession, owner: User, reason: str) -> bool:
    """Gỡ SĐT khỏi tài khoản chưa xác minh (không commit); trả True nếu tài khoản bị vô hiệu
    vì không còn cách đăng nhập nào khác."""
    phone = owner.phone
    owner.phone = None
    disabled = owner.username is None and owner.google_sub is None
    if disabled:
        owner.is_active = False
    owner.token_version += 1  # phiên cũ (đăng nhập bằng SĐT) hết hiệu lực
    audit(
        session,
        SYSTEM_ACTOR,
        "auth.phone_released",
        "user",
        str(owner.id),
        audit_detail(
            str(owner.id),
            owner.full_name,
            [audit_change("SĐT", mask_phone(phone), None)]
            + ([audit_change("Trạng thái", "Hoạt động", "Vô hiệu")] if disabled else []),
            phone=mask_phone(phone),
            disabled=disabled,
            reason=reason,
        ),
    )
    return disabled


async def verify(session: AsyncSession, phone: str, code: str) -> Registered:
    """Bước 2 (commit). 400 E-AUTH-14 / E-AUTH-15 · 409 E-AUTH-22 · 403 E-AUTH-31."""
    now = datetime.now(UTC)
    await otp.lock_phone(session, phone)  # đăng ký / gắn SĐT cùng số chạy lần lượt
    row, _ = await otp.verify(session, OtpPurpose.REGISTER, phone, code, None)
    pending = await session.get(RegistrationRequest, row.id)
    if pending is None:  # không xảy ra: mã đăng ký luôn có dữ liệu chờ
        await session.commit()
        raise otp.code_dead()
    full_name, hashed = pending.full_name, pending.hashed_password
    await session.delete(pending)  # không giữ hash mật khẩu lâu hơn cần

    owner = await session.scalar(select(User).where(User.phone == phone).with_for_update())
    if owner is not None:
        if not _releasable(owner):
            await session.commit()  # mã đã dùng
            raise phone_taken(phone)
        release_phone(session, owner, "register")
        await session.flush()  # giải phóng UNIQUE(phone) trước khi chèn tài khoản mới

    user = User(
        phone=phone,
        full_name=full_name,
        hashed_password=hashed,
        role=Role.MEMBER,
        is_active=True,
        phone_verified_at=now,
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise phone_taken(phone) from None
    audit(
        session,
        enroll.actor_of(user),
        "auth.register",
        "user",
        str(user.id),
        audit_detail(str(user.id), full_name, phone=mask_phone(phone)),
    )
    ensured = await enroll.enroll(session, user)
    if ensured is None:  # không xảy ra: tài khoản khách có SĐT đã xác minh
        raise RuntimeError("register without member")
    await session.commit()
    if not user.is_active:  # hồ sơ hội viên cùng SĐT đang Ngừng
        raise enroll.account_locked()
    await session.refresh(user)
    return Registered(user, ensured.member_code, ensured.outcome == "upgraded")

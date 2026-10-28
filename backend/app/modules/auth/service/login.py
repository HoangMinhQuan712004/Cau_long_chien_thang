"""Đăng ký, đăng nhập chung, phiên quản trị, chủ JWT khách."""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict
from app.core.security import TokenClaims, hash_password, verify_password
from app.modules.auth.models import (
    AdminSession,
    AuditAction,
    RegisterRequest,
    Role,
    SessionEndReason,
    User,
)
from app.modules.auth.schemas import AdminAccountOut, RegisterIn
from app.modules.auth.service.common import (
    ADMIN_ROLES,
    LoginError,
    audit,
    dummy_hash,
    ensure_ip_allowed,
    hash_token,
    lock_phone,
    record_failure,
    seconds_until,
)
from app.modules.auth.utils import parse_login

SessionErrorCode = Literal["unauthenticated", "expired", "password_changed", "account_disabled"]


class SessionError(Exception):
    """Không có phiên quản trị còn hiệu lực."""

    def __init__(self, code: SessionErrorCode) -> None:
        super().__init__(code)
        self.code: SessionErrorCode = code


async def get_customer(session: AsyncSession, claims: TokenClaims) -> User | None:
    """Chủ JWT khách: khách đang hoạt động, đúng `token_version`; không thì None."""
    user = await session.get(User, int(claims.subject))
    if user is None or not user.is_active or user.role != Role.CUSTOMER:
        return None
    if claims.version != user.token_version:
        return None
    return user


class RegisterRateLimited(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("register_rate_limited")
        self.retry_after = retry_after


async def _count_register_request(session: AsyncSession, ip: str | None, now: datetime) -> None:
    """Đếm một lần gọi đăng ký của IP (commit ngay); quá giới hạn/giờ ⇒ RegisterRateLimited."""
    if ip is None:
        return
    hour_ago = now - timedelta(hours=1)
    # gọi song song không vượt giới hạn
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"register:{ip}"))))
    count, oldest = (
        await session.execute(
            select(func.count(), func.min(RegisterRequest.created_at)).where(
                RegisterRequest.ip == ip, RegisterRequest.created_at > hour_ago
            )
        )
    ).one()
    if count >= settings.REGISTER_IP_MAX_PER_HOUR:
        await session.rollback()
        raise RegisterRateLimited(seconds_until(oldest + timedelta(hours=1), now))
    await session.execute(delete(RegisterRequest).where(RegisterRequest.created_at <= hour_ago))
    session.add(RegisterRequest(ip=ip, created_at=now))
    await session.commit()


async def create_user(session: AsyncSession, data: RegisterIn, ip: str | None) -> User:
    await _count_register_request(session, ip, datetime.now(UTC))
    # băm trước khi khóa
    hashed_password = hash_password(data.password)
    # cùng khóa với xác minh SĐT
    await lock_phone(session, data.phone)
    if await session.scalar(select(User.id).where(User.phone == data.phone)):
        raise Conflict("Số điện thoại đã được sử dụng")
    user = User(
        phone=data.phone,
        full_name=data.full_name,
        hashed_password=hashed_password,
        role=Role.CUSTOMER,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _locked_error(locked_until: datetime, now: datetime) -> LoginError:
    return LoginError("E-002", retry_after=seconds_until(locked_until, now))


async def check_credentials(
    session: AsyncSession,
    raw_login: str,
    password: str,
    ip: str | None,
) -> User:
    """Kiểm đăng nhập (IP chặn ⇒ đang khóa ⇒ sai); lần sai commit ngay, lần đúng caller commit."""
    now = datetime.now(UTC)
    await ensure_ip_allowed(session, ip, now)

    kind, value = parse_login(raw_login)
    column = User.phone if kind == "phone" else User.username
    user = await session.scalar(select(User).where(column == value).with_for_update())
    # tài khoản lạ / bị khóa: E-001, không đếm
    if user is None or not user.is_active:
        verify_password(password, dummy_hash())
        await record_failure(session, ip, now)
        await session.commit()
        raise LoginError("E-001")

    if user.locked_until is not None:
        if user.locked_until > now:
            # đang khóa: không cộng, vẫn tính cho IP
            await record_failure(session, ip, now)
            await session.commit()
            raise _locked_error(user.locked_until, now)
        user.locked_until = None
        user.failed_login_count = 0

    # không mật khẩu (Google): so hash giả, luôn sai
    hashed = user.hashed_password
    if not verify_password(password, hashed or dummy_hash()) or hashed is None:
        await record_failure(session, ip, now)
        user.failed_login_count += 1
        if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
            user.failed_login_count = 0
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            local_until = user.locked_until.astimezone(settings.tz)
            audit(
                session,
                AuditAction.LOGIN_LOCKED,
                target_user_id=user.id,
                detail=f"Khóa đến {local_until:%H:%M}",
            )
            await session.commit()
            raise _locked_error(user.locked_until, now)
        await session.commit()
        raise LoginError("E-001")
    return user


async def sign_in(
    session: AsyncSession,
    raw_login: str,
    password: str,
    user_agent: str | None,
    ip: str | None,
) -> tuple[User, tuple[AdminSession, str] | None]:
    """Đăng nhập chung: khách ⇒ (user, None); Admin/nhân viên ⇒ (user, (phiên, token cookie))."""
    user = await check_credentials(session, raw_login, password, ip)
    user.failed_login_count = 0
    if user.role not in ADMIN_ROLES:
        await session.commit()
        return user, None

    token = secrets.token_urlsafe(32)
    admin_session = AdminSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.ADMIN_SESSION_HOURS),
        user_agent=(user_agent or "")[:255] or None,
        ip=ip,
    )
    session.add(admin_session)
    audit(session, AuditAction.LOGIN_SUCCESS, actor_id=user.id)
    await session.commit()
    return user, (admin_session, token)


async def resolve_admin_session(
    session: AsyncSession, token: str | None
) -> tuple[AdminSession, User]:
    """Phiên + tài khoản còn hiệu lực, ngược lại `SessionError` nêu lý do (báo E-006/E-007)."""
    if not token:
        raise SessionError("unauthenticated")
    row = (
        await session.execute(
            select(AdminSession, User)
            .join(User, User.id == AdminSession.user_id)
            .where(AdminSession.token_hash == hash_token(token))
        )
    ).one_or_none()
    if row is None:
        raise SessionError("unauthenticated")
    admin_session, user = row
    if admin_session.revoked_reason == SessionEndReason.PASSWORD_CHANGED:
        raise SessionError("password_changed")
    if admin_session.revoked_reason == SessionEndReason.ACCOUNT_DISABLED or not user.is_active:
        raise SessionError("account_disabled")
    if admin_session.revoked_at is not None:
        raise SessionError("unauthenticated")
    if admin_session.expires_at <= datetime.now(UTC):
        raise SessionError("expired")
    if user.role not in ADMIN_ROLES:
        raise SessionError("unauthenticated")
    return admin_session, user


async def admin_logout(session: AsyncSession, token: str | None) -> None:
    """Kết thúc phiên trên máy này ngay, không ảnh hưởng phiên Admin ở máy khác (BR-011)."""
    try:
        admin_session, user = await resolve_admin_session(session, token)
    except SessionError:
        return
    admin_session.revoked_at = datetime.now(UTC)
    admin_session.revoked_reason = SessionEndReason.LOGOUT
    audit(session, AuditAction.LOGOUT, actor_id=user.id)
    await session.commit()


def to_account(user: User) -> AdminAccountOut:
    """Thẻ tài khoản (SRS mục II.5); nhân viên hiện họ tên."""
    if user.role == Role.ADMIN:
        return AdminAccountOut(kind="admin", display_name="Admin", role_label="Chủ sân")
    return AdminAccountOut(kind="counter", display_name=user.full_name, role_label="Nhân viên")

"""Đăng nhập chung (T-013 AC1–AC4; port PR #17 sang hạ tầng dev).

- Theo IP: ≥ ``LOGIN_IP_MAX_ATTEMPTS`` lần sai / cửa sổ -> 429 ``E-AUTH-12`` (đếm Redis).
- Theo tài khoản: sai ``LOGIN_MAX_ATTEMPTS`` lần liên tiếp -> khóa ``LOGIN_LOCK_MINUTES`` phút,
  423 ``E-AUTH-11`` (cột ``users``, khóa dòng ``FOR UPDATE`` -> sai đồng thời vẫn khóa đúng).
- Không phân biệt "không có tài khoản" với "sai mật khẩu" (``E-AUTH-10``, so hash giả).
"""

import math
import secrets
from datetime import UTC, datetime, timedelta
from functools import cache

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import AuditActor, audit, audit_change
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth import member_accounts, sessions
from app.modules.auth.models import AdminSession, User
from app.modules.auth.utils import parse_login

IP_SCOPE = "login.ip"
SYSTEM = AuditActor(type="system", id=None, label="Hệ thống")


@cache
def dummy_hash() -> str:
    """Hash giả: tài khoản không tồn tại cũng tốn thời gian như so mật khẩu thật."""
    return hash_password(secrets.token_urlsafe(16))


def _ip_window() -> int:
    return settings.LOGIN_IP_WINDOW_MINUTES * 60


def bad_credentials() -> AppError:
    return AppError("E-AUTH-10", "Số điện thoại, tên đăng nhập hoặc mật khẩu không đúng.", 401)


def locked_error(retry_after: int) -> AppError:
    return AppError(
        "E-AUTH-11",
        f"Bạn đã nhập sai {settings.LOGIN_MAX_ATTEMPTS} lần. "
        f"Vui lòng thử lại sau {settings.LOGIN_LOCK_MINUTES} phút.",
        423,
        headers={"Retry-After": str(retry_after)},
        retry_after=retry_after,
    )


async def ensure_ip_allowed(ip: str | None) -> None:
    retry_after = await ratelimit.failures_exceeded(
        IP_SCOPE, ip or "unknown", settings.LOGIN_IP_MAX_ATTEMPTS, _ip_window()
    )
    if retry_after is not None:
        raise AppError(
            "E-AUTH-12",
            "Có quá nhiều lần đăng nhập sai từ mạng này. "
            f"Vui lòng thử lại sau {settings.LOGIN_IP_WINDOW_MINUTES} phút.",
            429,
            headers={"Retry-After": str(retry_after)},
            retry_after=retry_after,
        )


async def record_ip_failure(ip: str | None) -> None:
    await ratelimit.record_failure(IP_SCOPE, ip or "unknown", _ip_window())


def _seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


async def check_credentials(
    session: AsyncSession, raw_login: str, password: str, ip: str | None
) -> User:
    """Kiểm đăng nhập; lần sai được commit ngay (đếm, khóa), lần đúng caller commit."""
    await ensure_ip_allowed(ip)
    now = datetime.now(UTC)
    kind, value = parse_login(raw_login)
    column = User.phone if kind == "phone" else User.username
    user = await session.scalar(select(User).where(column == value).with_for_update())

    if user is None or not user.is_active:
        verify_password(password, dummy_hash())
        await session.rollback()
        await record_ip_failure(ip)
        raise bad_credentials()

    if user.locked_until is not None:
        if user.locked_until > now:
            # Tính trước khi rollback (rollback làm hết hạn thuộc tính ORM)
            retry_after = _seconds_until(user.locked_until, now)
            await session.rollback()
            await record_ip_failure(ip)
            raise locked_error(retry_after)
        user.locked_until = None
        user.failed_login_count = 0

    hashed = user.hashed_password
    # Tài khoản chỉ Google (không mật khẩu): so hash giả, luôn sai
    if not verify_password(password, hashed or dummy_hash()) or hashed is None:
        user.failed_login_count += 1
        error = bad_credentials()
        if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
            user.failed_login_count = 0
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            local_until = user.locked_until.astimezone(settings.tz)
            audit(
                session,
                SYSTEM,
                "auth.login_locked",
                "user",
                str(user.id),
                sessions.account_detail(
                    user,
                    [audit_change("Đăng nhập", None, f"Khóa đến {local_until:%H:%M}")],
                    locked_until=f"{local_until:%H:%M %d/%m/%Y}",
                ),
            )
            error = locked_error(_seconds_until(user.locked_until, now))
        await session.commit()
        await record_ip_failure(ip)
        raise error
    if member_accounts.initial_password_expired(user, now):
        # Chỉ báo SAU khi mật khẩu đúng (sai thì vẫn là E-AUTH-10 + đếm lần sai)
        await session.rollback()
        raise member_accounts.expired_error()
    user.failed_login_count = 0
    return user


async def sign_in(
    session: AsyncSession, raw_login: str, password: str, user_agent: str | None, ip: str | None
) -> tuple[User, tuple[AdminSession, str] | None]:
    """Khách -> (user, None); Admin / NV -> (user, (phiên, token cookie)). Commit tại đây."""
    user = await check_credentials(session, raw_login, password, ip)
    if user.role not in sessions.ADMIN_ROLES:
        await session.commit()
        return user, None
    admin_session, token = await sessions.create_session(session, user, user_agent, ip)
    audit(
        session,
        AuditActor(
            type=sessions.actor_type_of(user.role), id=user.id, label=sessions.actor_label(user)
        ),
        "auth.login_success",
        "user",
        str(user.id),
        sessions.account_detail(user, session_id=admin_session.id),
    )
    await session.commit()
    return user, (admin_session, token)

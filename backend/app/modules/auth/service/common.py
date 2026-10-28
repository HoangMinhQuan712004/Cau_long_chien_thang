"""Dùng chung giữa các luồng auth: lỗi đăng nhập, giới hạn IP, audit, khóa SĐT, đổi mật khẩu."""

import hashlib
import math
import secrets
from datetime import datetime, timedelta
from functools import cache
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.config import settings
from app.core.security import hash_password
from app.modules.auth.models import (
    AdminSession,
    AuditAction,
    AuditLog,
    LoginFailure,
    Role,
    SessionEndReason,
    User,
)

LoginErrorCode = Literal["E-001", "E-002", "E-008"]
ADMIN_ROLES = {Role.ADMIN, Role.STAFF}


@cache
def dummy_hash() -> str:
    """Hash giả: tên không tồn tại cũng tốn thời gian như so mật khẩu thật (chống dò tài khoản)."""
    return hash_password(secrets.token_urlsafe(16))


class LoginError(Exception):
    """Đăng nhập bị từ chối; `code` là mã thông báo của SRS (Phụ lục A)."""

    def __init__(self, code: LoginErrorCode, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code: LoginErrorCode = code
        # số giây còn khóa
        self.retry_after = retry_after


def seconds_until(moment: datetime, now: datetime) -> int:
    return max(1, math.ceil((moment - now).total_seconds()))


async def ensure_ip_allowed(session: AsyncSession, ip: str | None, now: datetime) -> None:
    """IP sai quá `LOGIN_IP_MAX_ATTEMPTS` lần trong cửa sổ ⇒ E-008; mở khi lần sai cũ nhất hết."""
    if ip is None:
        return
    window = timedelta(minutes=settings.LOGIN_IP_WINDOW_MINUTES)
    count, oldest = (
        await session.execute(
            select(func.count(), func.min(LoginFailure.created_at)).where(
                LoginFailure.ip == ip, LoginFailure.created_at > now - window
            )
        )
    ).one()
    if count >= settings.LOGIN_IP_MAX_ATTEMPTS:
        raise LoginError("E-008", retry_after=seconds_until(oldest + window, now))


async def record_failure(session: AsyncSession, ip: str | None, now: datetime) -> None:
    """Ghi một lần sai của IP (chưa commit); dọn bản ghi đã ra khỏi cửa sổ để bảng không phình."""
    if ip is None:
        return
    window = timedelta(minutes=settings.LOGIN_IP_WINDOW_MINUTES)
    await session.execute(delete(LoginFailure).where(LoginFailure.created_at <= now - window))
    session.add(LoginFailure(ip=ip))


def audit(
    session: AsyncSession,
    action: AuditAction,
    *,
    actor_id: int | None = None,
    target_user_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Ghi lịch sử thao tác (chưa commit, cùng transaction với thao tác). Actor None = Hệ thống."""
    session.add(
        AuditLog(actor_id=actor_id, action=action, target_user_id=target_user_id, detail=detail)
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def active_session_filter(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (AdminSession.revoked_at.is_(None), AdminSession.expires_at > now)


async def revoke_sessions(
    session: AsyncSession, user_id: int, reason: SessionEndReason, now: datetime
) -> None:
    await session.execute(
        update(AdminSession)
        .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )


async def replace_password(
    session: AsyncSession, user: User, hashed_password: str | None, now: datetime
) -> None:
    """Thay/hủy mật khẩu: gỡ khóa, thu hồi phiên quản trị, tăng `token_version` (chưa commit)."""
    user.hashed_password = hashed_password
    user.token_version += 1
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_sessions(session, user.id, SessionEndReason.PASSWORD_CHANGED, now)


async def lock_phone(session: AsyncSession, phone: str) -> None:
    """Khóa theo SĐT tới hết transaction (gửi mã, gắn SĐT, đăng ký)."""
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"otp:{phone}"))))

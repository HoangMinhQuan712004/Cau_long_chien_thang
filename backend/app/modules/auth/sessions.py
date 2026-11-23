"""Phiên khu quản trị phía server (ADR-008 §3): cookie ``admin_session``, thu hồi được.

T-077: hạn **trượt** ``ADMIN_SESSION_IDLE_DAYS`` ngày – đang dùng thì tự gia hạn (ghi DB tối đa
một lần mỗi giờ mỗi phiên), không có hạn tuyệt đối.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.audit import SYSTEM_ACTOR, Value, audit, audit_change, audit_detail
from app.core.config import settings
from app.modules.auth.models import AdminSession, Role, SessionEndReason, User, UserAvatar
from app.modules.auth.schemas import AdminAccountOut

ADMIN_ROLES = {Role.ADMIN, Role.STAFF}
SessionErrorReason = Literal["unauthenticated", "expired", "password_changed", "account_disabled"]


class SessionError(Exception):
    """Không có phiên quản trị còn hiệu lực; ``reason`` cho FE giải thích (T-013 AC5)."""

    def __init__(self, reason: SessionErrorReason) -> None:
        super().__init__(reason)
        self.reason: SessionErrorReason = reason


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def actor_type_of(role: Role | str) -> str:
    """Loại người thao tác lưu ở ``audit_log.actor_type`` / ``*_by_type``: vai ``member`` vẫn ghi
    ``customer`` (T-015 đổi tên vai, giữ dữ liệu nhật ký cũ + CHECK + ``Principal.key``)."""
    return "customer" if str(role) == Role.MEMBER else str(role)


def actor_label(user: User) -> str:
    """Nhãn người thao tác: "Admin" / "NV007 · Nguyễn Văn An" (ADR-008 §2)."""
    if user.role == Role.ADMIN:
        return "Admin"
    if user.role == Role.STAFF:
        return f"{user.staff_code} · {user.full_name}" if user.staff_code else user.full_name
    return "Khách"


def avatar_url(user_id: int, etag: str | None) -> str | None:
    """Link ảnh đại diện tài khoản quản trị, gồm ``?v={etag}`` để phá cache; chưa có ảnh -> None."""
    if etag is None:
        return None
    return f"{settings.API_PREFIX}/admin/auth/avatars/{user_id}?v={etag}"


async def my_avatar_url(session: AsyncSession, user_id: int) -> str | None:
    etag = await session.scalar(select(UserAvatar.etag).where(UserAvatar.user_id == user_id))
    return avatar_url(user_id, etag)


def to_account(user: User) -> AdminAccountOut:
    if user.role == Role.ADMIN:
        return AdminAccountOut(kind="admin", display_name=user.full_name, role_label="Admin")
    return AdminAccountOut(
        kind="staff",
        display_name=user.full_name,
        role_label="Nhân viên",
        staff_code=user.staff_code,
    )


async def create_session(
    session: AsyncSession, user: User, user_agent: str | None, ip: str | None
) -> tuple[AdminSession, str]:
    """Phiên mới (chưa commit) + token cho cookie (chỉ trả một lần, DB lưu hash)."""
    token = secrets.token_urlsafe(32)
    row = AdminSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + idle_lifetime(),
        user_agent=(user_agent or "")[:255] or None,
        ip=ip,
    )
    session.add(row)
    await session.flush()
    return row, token


RENEW_EVERY = timedelta(hours=1)


def idle_lifetime() -> timedelta:
    return timedelta(days=settings.ADMIN_SESSION_IDLE_DAYS)


async def renew_if_due(
    session: AsyncSession, admin_session: AdminSession, now: datetime | None = None
) -> bool:
    """Gia hạn phiên đang dùng: lần gia hạn trước (suy từ ``expires_at − hạn``) đã hơn 1 giờ ->
    ``expires_at = now + hạn``.

    T-77-1: **một** câu UPDATE có điều kiện trên chính session của request rồi commit ngay (lúc
    này transaction chỉ mới có các câu đọc xác thực) – không mở session thứ hai, nên nhiều request
    song song không cạn pool. Request đến cùng lúc: một câu chạm dòng, các câu khác không làm gì
    (AC7). Trả True khi chính request này đã gia hạn (-> gửi lại cookie)."""
    now = now or datetime.now(UTC)
    if admin_session.expires_at - idle_lifetime() + RENEW_EVERY > now:
        return False
    new = now + idle_lifetime()
    result = await session.execute(
        update(AdminSession)
        .where(
            AdminSession.id == admin_session.id,
            AdminSession.expires_at < new - RENEW_EVERY,
            AdminSession.revoked_at.is_(None),
        )
        .values(expires_at=new)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    if not result.rowcount:
        return False  # request khác vừa gia hạn / phiên vừa bị thu hồi
    # Giá trị mới đã ở DB: chỉ cập nhật bản trong bộ nhớ, không đánh dấu "bẩn" – gán thường
    # khiến lần commit của request phát thêm một câu UPDATE thừa (T-77-2)
    set_committed_value(admin_session, "expires_at", new)
    return True


async def resolve(session: AsyncSession, token: str | None) -> tuple[AdminSession, User]:
    """Phiên + tài khoản còn hiệu lực; ngược lại ``SessionError`` nêu lý do."""
    if not token or len(token) > 200:
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


def account_detail(
    user: User, changes: list[dict[str, Value]] | None = None, **extra: Any
) -> dict[str, Any]:
    """Lịch sử thao tác: đối tượng là tài khoản (mã NV + tên; Admin; khách theo tên)."""
    code = user.staff_code if user.role == Role.STAFF else None
    name = actor_label(user) if user.role == Role.ADMIN else user.full_name
    return audit_detail(code, name, changes, **extra)


def active_filter(now: datetime):
    return (AdminSession.revoked_at.is_(None), AdminSession.expires_at > now)


async def revoke_all(
    session: AsyncSession,
    user_id: int,
    reason: SessionEndReason,
    now: datetime | None = None,
    keep_id: int | None = None,
) -> int:
    """Thu hồi mọi phiên đang mở của tài khoản, trừ phiên ``keep_id`` nếu có (chưa commit)."""
    query = update(AdminSession).where(
        AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None)
    )
    if keep_id is not None:
        query = query.where(AdminSession.id != keep_id)
    result = await session.execute(
        query.values(revoked_at=now or func.now(), revoked_reason=reason)
    )
    return result.rowcount or 0


async def replace_password(
    session: AsyncSession, user: User, hashed: str | None, keep_session_id: int | None = None
) -> int:
    """Thay / hủy mật khẩu: gỡ khóa, thu hồi phiên quản trị, tăng ``token_version``.

    ``keep_session_id``: giữ phiên đang dùng (tự đổi mật khẩu). Chưa commit; trả số phiên vừa
    thu hồi.
    """
    user.hashed_password = hashed
    user.token_version += 1
    user.failed_login_count = 0
    user.locked_until = None
    revoked = await revoke_all(
        session, user.id, SessionEndReason.PASSWORD_CHANGED, keep_id=keep_session_id
    )
    if revoked:
        # Hệ thống đăng xuất các phiên đang mở (SRS Lịch sử thao tác, nhóm Đăng nhập, đăng xuất)
        change = audit_change("Phiên", "Đang mở", "Đã đăng xuất do đổi mật khẩu")
        audit(
            session,
            SYSTEM_ACTOR,
            "auth.logout_password_changed",
            "user",
            str(user.id),
            account_detail(user, [change], revoked=revoked),
        )
    return revoked

"""Hồ sơ của tôi (khu quản trị): xem, Admin tự sửa họ tên, Admin / NV tự đổi mật khẩu,
xem / đăng xuất các nơi đang đăng nhập.

Hàm ghi ở đây **commit** (thao tác đơn lẻ của trang quản trị).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth import sessions
from app.modules.auth.models import AdminSession, Role, SessionEndReason, User
from app.modules.auth.schemas import AdminProfileOut, MySessionOut
from app.modules.auth.utils import parse_user_agent


def profile(admin_session: AdminSession, user: User) -> AdminProfileOut:
    """Hồ sơ của chính người đang đăng nhập khu quản trị."""
    account = sessions.to_account(user)
    return AdminProfileOut(
        kind=account.kind,
        full_name=user.full_name,
        role_label=account.role_label,
        staff_code=user.staff_code,
        username=user.username,
        phone=user.phone,
        created_at=user.created_at,
        session_expires_at=admin_session.expires_at,
    )


def _self_actor(user: User) -> AuditActor:
    return AuditActor(
        type=sessions.actor_type_of(user.role), id=user.id, label=sessions.actor_label(user)
    )


async def _lock_self(session: AsyncSession, user_id: int) -> User:
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise AppError("E-AUTH-1", "Chưa đăng nhập", 401, reason="unauthenticated")
    return user


async def rename(session: AsyncSession, user_id: int, full_name: str) -> User:
    """Admin tự sửa họ tên (NV không được: họ tên NV do Admin quản lý).

    ``full_name`` đã được ``AdminProfileIn`` gộp khoảng trắng và kiểm độ dài.
    """
    user = await _lock_self(session, user_id)
    if user.role != Role.ADMIN:
        raise AppError("E-AUTH-2", "Không có quyền thực hiện thao tác này", 403)
    if full_name != user.full_name:
        change = audit_change("Họ tên", user.full_name, full_name)
        user.full_name = full_name
        audit(
            session,
            _self_actor(user),
            "account.update",
            "user",
            str(user.id),
            sessions.account_detail(user, [change]),
        )
    await session.commit()
    return user


async def change_password(
    session: AsyncSession, user_id: int, session_id: int, current: str, new_password: str
) -> None:
    """Admin / NV tự đổi mật khẩu: thu hồi mọi phiên khác, giữ phiên đang dùng.

    Mật khẩu hiện tại sai -> 400 E-AUTH-28 (cùng mã phía khách).
    """
    hashed = hash_password(new_password)  # băm trước khi khóa dòng
    user = await _lock_self(session, user_id)
    if not (user.hashed_password and verify_password(current, user.hashed_password)):
        raise AppError("E-AUTH-28", "Mật khẩu hiện tại không đúng.", 400)
    revoked = await sessions.replace_password(session, user, hashed, keep_session_id=session_id)
    audit(
        session,
        _self_actor(user),
        "account.password_changed",
        "user",
        str(user.id),
        sessions.account_detail(user, revoked=revoked),
    )
    await session.commit()


async def list_sessions(session: AsyncSession, current: AdminSession) -> list[MySessionOut]:
    """Phiên đang mở của chính mình: phiên hiện tại đầu, còn lại mới nhất trước."""
    rows = await session.scalars(
        select(AdminSession)
        .where(
            AdminSession.user_id == current.user_id,
            *sessions.active_filter(datetime.now(UTC)),
        )
        .order_by((AdminSession.id == current.id).desc(), AdminSession.created_at.desc())
    )
    result = []
    for row in rows:
        device, os_name, browser = parse_user_agent(row.user_agent)
        result.append(
            MySessionOut(
                id=row.id,
                device_type=device,
                os=os_name,
                browser=browser,
                created_at=row.created_at,
                expires_at=row.expires_at,
                is_current=row.id == current.id,
            )
        )
    return result


def _audit_logout(session: AsyncSession, user: User, **extra: int) -> None:
    """Tự đăng xuất phiên khác (từ Hồ sơ của tôi): cùng loại "Đăng xuất" với nút Đăng xuất."""
    audit(
        session,
        _self_actor(user),
        "auth.logout",
        "user",
        str(user.id),
        sessions.account_detail(user, **extra),
    )


async def revoke_session(
    session: AsyncSession, user: User, current: AdminSession, session_id: int
) -> None:
    """Đăng xuất một phiên khác của chính mình. Phiên hiện tại -> 400; không thấy -> 404."""
    if session_id == current.id:
        raise AppError(
            "E-AUTH-33", "Đây là phiên đang dùng. Hãy dùng Đăng xuất để thoát máy này.", 400
        )
    now = datetime.now(UTC)
    target = await session.scalar(
        select(AdminSession)
        .where(
            AdminSession.id == session_id,
            AdminSession.user_id == user.id,
            *sessions.active_filter(now),
        )
        .with_for_update()
    )
    if target is None:
        raise AppError("E-STAFF-2", "Không tìm thấy phiên đăng nhập.", 404)
    target.revoked_at = now
    target.revoked_reason = SessionEndReason.LOGOUT
    _audit_logout(session, user, session_id=session_id)
    await session.commit()


async def revoke_other_sessions(session: AsyncSession, user: User, current: AdminSession) -> int:
    """Đăng xuất mọi phiên khác của chính mình; trả số phiên vừa thu hồi."""
    revoked = await sessions.revoke_all(
        session, user.id, SessionEndReason.LOGOUT, keep_id=current.id
    )
    if revoked:
        _audit_logout(session, user, revoked=revoked)
    await session.commit()
    return revoked

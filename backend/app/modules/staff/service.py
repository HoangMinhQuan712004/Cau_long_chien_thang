"""Admin quản lý nhân viên: tạo (mã + tên đăng nhập tự sinh), sửa, khóa, đặt lại MK, phiên."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.core.security import hash_password
from app.modules.auth.models import (
    STAFF_CODE_SEQ,
    AdminSession,
    AuditAction,
    Role,
    SessionEndReason,
    User,
)
from app.modules.auth.service.common import (
    active_session_filter,
    audit,
    replace_password,
    revoke_sessions,
)
from app.modules.auth.utils import staff_code, staff_username
from app.modules.staff.schemas import StaffCreateIn, StaffOut, StaffUpdateIn

_STAFF_CODE_TRIES = 5


async def _get_staff(session: AsyncSession, staff_id: int, *, lock: bool = False) -> User:
    """`lock`: khóa dòng user như đăng nhập ⇒ phiên vừa tạo song song cũng bị thu hồi."""
    query = select(User).where(User.id == staff_id, User.role == Role.STAFF)
    user = await session.scalar(query.with_for_update() if lock else query)
    if user is None:
        raise NotFound("Không tìm thấy nhân viên")
    return user


async def _staff_out(session: AsyncSession, user: User) -> StaffOut:
    return (await list_staff(session, staff_id=user.id))[0]


async def list_staff(session: AsyncSession, staff_id: int | None = None) -> list[StaffOut]:
    now = datetime.now(UTC)
    last_login = (
        select(func.max(AdminSession.created_at))
        .where(AdminSession.user_id == User.id)
        .scalar_subquery()
    )
    active = (
        select(func.count())
        .where(AdminSession.user_id == User.id, *active_session_filter(now))
        .scalar_subquery()
    )
    query = select(User, last_login, active).where(User.role == Role.STAFF).order_by(User.id)
    if staff_id is not None:
        query = query.where(User.id == staff_id)
    rows = (await session.execute(query)).all()
    return [
        StaffOut(
            id=user.id,
            full_name=user.full_name,
            staff_code=user.staff_code or "",
            username=user.username or "",
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=last_login_at,
            active_sessions=active_sessions,
        )
        for user, last_login_at, active_sessions in rows
    ]


async def create_staff(session: AsyncSession, admin: User, data: StaffCreateIn) -> StaffOut:
    """Mã `NV…` lấy từ sequence (tạo song song không trùng), tên đăng nhập sinh từ họ tên + mã."""
    hashed_password = hash_password(data.password)
    for _ in range(_STAFF_CODE_TRIES):
        code = staff_code(await session.scalar(STAFF_CODE_SEQ.next_value()))
        user = User(
            username=staff_username(data.full_name, code),
            staff_code=code,
            full_name=data.full_name,
            hashed_password=hashed_password,
            role=Role.STAFF,
        )
        try:
            async with session.begin_nested():
                session.add(user)
        except IntegrityError:
            # trùng tên đặt tay cũ ⇒ lấy mã kế tiếp
            continue
        break
    else:
        raise RuntimeError("Không sinh được tên đăng nhập nhân viên")
    audit(
        session,
        AuditAction.STAFF_CREATED,
        actor_id=admin.id,
        target_user_id=user.id,
        detail=f"{user.staff_code} · {user.username}",
    )
    await session.commit()
    return await _staff_out(session, user)


async def update_staff(
    session: AsyncSession, admin: User, staff_id: int, data: StaffUpdateIn
) -> StaffOut:
    user = await _get_staff(session, staff_id, lock=True)
    now = datetime.now(UTC)
    if data.full_name is not None and data.full_name != user.full_name:
        user.full_name = data.full_name
        audit(
            session,
            AuditAction.STAFF_UPDATED,
            actor_id=admin.id,
            target_user_id=user.id,
            detail=data.full_name,
        )
    if data.is_active is not None and data.is_active != user.is_active:
        user.is_active = data.is_active
        if data.is_active:
            action = AuditAction.STAFF_ENABLED
        else:
            action = AuditAction.STAFF_DISABLED
            await revoke_sessions(session, user.id, SessionEndReason.ACCOUNT_DISABLED, now)
        audit(session, action, actor_id=admin.id, target_user_id=user.id)
    await session.commit()
    return await _staff_out(session, user)


async def reset_staff_password(
    session: AsyncSession, admin: User, staff_id: int, password: str
) -> None:
    """Đặt lại mật khẩu ⇒ mọi phiên kết thúc (E-006) và gỡ khóa đăng nhập (BR-012)."""
    hashed_password = hash_password(password)  # băm trước khi khóa dòng
    user = await _get_staff(session, staff_id, lock=True)
    await replace_password(session, user, hashed_password, datetime.now(UTC))
    audit(session, AuditAction.STAFF_PASSWORD_RESET, actor_id=admin.id, target_user_id=user.id)
    await session.commit()


async def list_staff_sessions(session: AsyncSession, staff_id: int) -> list[AdminSession]:
    await _get_staff(session, staff_id)
    result = await session.scalars(
        select(AdminSession)
        .where(AdminSession.user_id == staff_id, *active_session_filter(datetime.now(UTC)))
        .order_by(AdminSession.created_at.desc())
    )
    return list(result.all())


async def revoke_staff_session(
    session: AsyncSession, admin: User, staff_id: int, session_id: int
) -> None:
    """Đăng xuất từ xa một phiên đang mở của nhân viên."""
    now = datetime.now(UTC)
    # sai nhân viên hay sai phiên đều 404
    admin_session = await session.scalar(
        select(AdminSession)
        .join(User, User.id == AdminSession.user_id)
        .where(
            AdminSession.id == session_id,
            AdminSession.user_id == staff_id,
            User.role == Role.STAFF,
            *active_session_filter(now),
        )
    )
    if admin_session is None:
        raise NotFound("Không tìm thấy phiên đăng nhập")
    admin_session.revoked_at = now
    admin_session.revoked_reason = SessionEndReason.REVOKED_BY_ADMIN
    audit(
        session,
        AuditAction.SESSION_REVOKED,
        actor_id=admin.id,
        target_user_id=staff_id,
        detail=f"Phiên #{session_id}",
    )
    await session.commit()

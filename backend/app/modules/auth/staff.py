"""Admin quản lý nhân viên (T-013 AC9–AC13; port PR #17): tạo, sửa, khóa, đặt lại MK, phiên.

Nằm trong module ``auth`` vì đọc / ghi bảng ``users`` + ``admin_sessions`` của module này.
Hàm ở đây **commit** (thao tác đơn lẻ của trang quản trị, không cần Idempotency-Key).
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.core.privacy import mask_ip
from app.core.security import hash_password
from app.modules.auth import sessions
from app.modules.auth.models import STAFF_CODE_SEQ, AdminSession, Role, SessionEndReason, User
from app.modules.auth.schemas import NewPassword
from app.modules.auth.utils import staff_code, staff_username

CODE_TRIES = 5


class StaffCreateIn(BaseModel):
    """Chỉ họ tên + mật khẩu; mã ``NV…`` và tên đăng nhập do hệ thống sinh."""

    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=255)
    password: NewPassword


class StaffUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class StaffPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: NewPassword


class StaffOut(BaseModel):
    id: int
    staff_code: str
    full_name: str
    username: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    active_sessions: int


class StaffSessionOut(BaseModel):
    id: int
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_masked: str | None


def _not_found() -> AppError:
    return AppError("E-STAFF-1", "Không tìm thấy nhân viên.", 404)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise AppError("E-001", "Vui lòng nhập Họ tên.", 422)
    return cleaned


async def _get_staff(session: AsyncSession, staff_id: int, lock: bool = False) -> User:
    """``lock``: khóa dòng như lúc đăng nhập -> phiên vừa tạo song song cũng bị thu hồi."""
    query = select(User).where(User.id == staff_id, User.role == Role.STAFF)
    user = await session.scalar(query.with_for_update() if lock else query)
    if user is None:
        raise _not_found()
    return user


async def list_staff(session: AsyncSession, staff_id: int | None = None) -> list[StaffOut]:
    now = datetime.now(UTC)
    last_login = (
        select(func.max(AdminSession.created_at))
        .where(AdminSession.user_id == User.id)
        .scalar_subquery()
    )
    active = (
        select(func.count())
        .where(AdminSession.user_id == User.id, *sessions.active_filter(now))
        .scalar_subquery()
    )
    query = select(User, last_login, active).where(User.role == Role.STAFF).order_by(User.id)
    if staff_id is not None:
        query = query.where(User.id == staff_id)
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
        for user, last_login_at, active_sessions in (await session.execute(query)).all()
    ]


async def _one(session: AsyncSession, user: User) -> StaffOut:
    return (await list_staff(session, staff_id=user.id))[0]


async def create_staff(session: AsyncSession, actor: AuditActor, data: StaffCreateIn) -> StaffOut:
    """Mã ``NV…`` từ sequence (tạo song song không trùng, không dùng lại); tên trùng -> mã kế."""
    full_name = _clean_name(data.full_name)
    hashed = hash_password(data.password)
    for _ in range(CODE_TRIES):
        code = staff_code(await session.scalar(STAFF_CODE_SEQ.next_value()))
        user = User(
            username=staff_username(full_name, code),
            staff_code=code,
            full_name=full_name,
            hashed_password=hashed,
            role=Role.STAFF,
            is_active=True,
        )
        try:
            async with session.begin_nested():
                session.add(user)
                await session.flush()
        except IntegrityError:
            continue  # tên đăng nhập trùng tài khoản cũ đặt tay -> lấy mã kế tiếp
        break
    else:
        raise RuntimeError("Không sinh được tên đăng nhập nhân viên")
    audit(
        session,
        actor,
        "staff.create",
        "user",
        user.staff_code,
        {"username": user.username, "full_name": user.full_name},
    )
    await session.commit()
    return await _one(session, user)


async def update_staff(
    session: AsyncSession, actor: AuditActor, staff_id: int, data: StaffUpdateIn
) -> StaffOut:
    user = await _get_staff(session, staff_id, lock=True)
    if data.full_name is not None:
        name = _clean_name(data.full_name)
        if name != user.full_name:
            audit(
                session,
                actor,
                "staff.update",
                "user",
                user.staff_code,
                {"full_name": {"from": user.full_name, "to": name}},
            )
            user.full_name = name
    if data.is_active is not None and data.is_active != user.is_active:
        user.is_active = data.is_active
        if data.is_active:
            audit(session, actor, "staff.enable", "user", user.staff_code)
        else:
            revoked = await sessions.revoke_all(session, user.id, SessionEndReason.ACCOUNT_DISABLED)
            audit(session, actor, "staff.disable", "user", user.staff_code, {"revoked": revoked})
    await session.commit()
    return await _one(session, user)


async def reset_staff_password(
    session: AsyncSession, actor: AuditActor, staff_id: int, password: str
) -> None:
    hashed = hash_password(password)  # băm trước khi khóa dòng
    user = await _get_staff(session, staff_id, lock=True)
    revoked = await sessions.replace_password(session, user, hashed)
    audit(session, actor, "staff.password_reset", "user", user.staff_code, {"revoked": revoked})
    await session.commit()


async def list_staff_sessions(session: AsyncSession, staff_id: int) -> list[StaffSessionOut]:
    await _get_staff(session, staff_id)
    rows = await session.scalars(
        select(AdminSession)
        .where(AdminSession.user_id == staff_id, *sessions.active_filter(datetime.now(UTC)))
        .order_by(AdminSession.created_at.desc())
    )
    return [
        StaffSessionOut(
            id=s.id,
            created_at=s.created_at,
            expires_at=s.expires_at,
            user_agent=s.user_agent,
            ip_masked=mask_ip(s.ip),
        )
        for s in rows
    ]


async def revoke_staff_session(
    session: AsyncSession, actor: AuditActor, staff_id: int, session_id: int
) -> None:
    """Đăng xuất từ xa một phiên đang mở của nhân viên."""
    await _get_staff(session, staff_id)
    now = datetime.now(UTC)
    admin_session = await session.scalar(
        select(AdminSession)
        .where(
            AdminSession.id == session_id,
            AdminSession.user_id == staff_id,
            *sessions.active_filter(now),
        )
        .with_for_update()
    )
    if admin_session is None:
        raise AppError("E-STAFF-2", "Không tìm thấy phiên đăng nhập.", 404)
    admin_session.revoked_at = now
    admin_session.revoked_reason = SessionEndReason.REVOKED_BY_ADMIN
    staff = await session.get(User, staff_id)
    audit(
        session,
        actor,
        "auth.session_revoked",
        "user",
        staff.staff_code if staff else str(staff_id),
        {"session_id": session_id},
    )
    await session.commit()

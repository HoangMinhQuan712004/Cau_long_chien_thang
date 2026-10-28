"""Đăng nhập / phiên (T-013 AC1–AC8, AC19). Ghi cần Origin; Idempotency-Key không bắt buộc."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import ratelimit
from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.context import client_ip
from app.core.errors import AppError
from app.core.middleware import require_origin
from app.core.permissions import Perm, Principal, require
from app.core.security import decode_token, hash_password
from app.modules.auth import cookies, login, service, sessions, staff
from app.modules.auth.deps import (
    REFRESH_COOKIE,
    AuthStateDep,
    CurrentCustomer,
    SessionDep,
    unauthenticated,
)
from app.modules.auth.models import AdminSession, Role, SessionEndReason, User
from app.modules.auth.schemas import (
    AdminSessionOut,
    AdminSignInOut,
    CustomerSignInOut,
    RegisterIn,
    SignInIn,
    SignInOut,
    UserOut,
    user_out,
)

# Mọi lệnh ghi của auth: Origin bắt buộc kể cả chưa có cookie (T-013 SEC9)
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_origin)])


def phone_taken() -> AppError:
    return AppError("E-AUTH-22", "Số điện thoại đã được sử dụng.", 409)


@router.post("/sign-in", response_model=SignInOut)
async def sign_in(data: SignInIn, request: Request, response: Response, session: SessionDep):
    """Một ô "SĐT hoặc tên đăng nhập" + mật khẩu.

    Khách -> JWT (cookie); Admin / NV -> phiên quản trị (cookie ``admin_session``, 12 giờ cứng).
    Lỗi: 401 E-AUTH-10 · 423 E-AUTH-11 (khóa 15 phút, ``retry_after``) · 429 E-AUTH-12 (theo IP).
    """
    user, admin = await login.sign_in(
        session, data.login, data.password, request.headers.get("user-agent"), client_ip()
    )
    if admin is None:
        cookies.set_auth_cookies(response, user)
        return CustomerSignInOut(account=user_out(user))
    admin_session, token = admin
    cookies.set_admin_cookie(response, token)
    return AdminSignInOut(account=sessions.to_account(user), expires_at=admin_session.expires_at)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, response: Response, session: SessionDep):
    """Đăng ký khách bằng SĐT (chưa xác minh – cần OTP mới coi là đã xác minh).

    Lỗi: 409 E-AUTH-22 (SĐT đã có chủ) · 429 E-SEC-5 (> 10 lần / giờ / IP).
    """
    retry_after = await ratelimit.check(
        "auth.register", client_ip() or "unknown", settings.REGISTER_IP_MAX_PER_HOUR, 3600
    )
    if retry_after is not None:
        raise ratelimit.too_many(retry_after)
    hashed = hash_password(data.password)
    if await session.scalar(select(User.id).where(User.phone == data.phone)):
        raise phone_taken()
    user = User(
        phone=data.phone,
        full_name=" ".join(data.full_name.split()),
        hashed_password=hashed,
        role=Role.CUSTOMER,
        is_active=True,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise phone_taken() from None
    await session.refresh(user)
    cookies.set_auth_cookies(response, user)
    return user_out(user)


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, session: SessionDep):
    token = request.cookies.get(REFRESH_COOKIE)
    claims = decode_token(token, "refresh") if token else None
    user = (
        await service.get_customer(session, int(claims.subject), claims.version) if claims else None
    )
    if user is None:
        raise unauthenticated("expired")
    cookies.set_auth_cookies(response, user)
    return user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    cookies.delete_auth_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentCustomer):
    return user_out(user)


# ---------------------------------------------------------------- phiên quản trị

admin_router = APIRouter(prefix="/admin/auth", tags=["admin: auth"])


async def current_admin(state: AuthStateDep) -> tuple[AdminSession, User]:
    if state.admin_session is None or state.user is None:
        raise unauthenticated(state.reason)
    return state.admin_session, state.user


AdminSessionDep = Annotated[tuple[AdminSession, User], Depends(current_admin)]


@admin_router.get("/me", response_model=AdminSessionOut)
async def admin_me(current: AdminSessionDep):
    admin_session, user = current
    return AdminSessionOut(account=sessions.to_account(user), expires_at=admin_session.expires_at)


@admin_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(response: Response, state: AuthStateDep, session: SessionDep):
    """Kết thúc phiên trên máy này (không ảnh hưởng phiên ở máy khác)."""
    cookies.delete_admin_cookie(response)
    if state.admin_session is None or state.user is None:
        return
    admin_session = await session.get(AdminSession, state.admin_session.id)
    if admin_session is None or admin_session.revoked_at is not None:
        return
    admin_session.revoked_at = datetime.now(UTC)
    admin_session.revoked_reason = SessionEndReason.LOGOUT
    user = state.user
    audit(
        session,
        AuditActor(type=str(user.role), id=user.id, label=sessions.actor_label(user)),
        "auth.logout",
        "user",
        str(user.id),
        {"session_id": admin_session.id},
    )
    await session.commit()


# ---------------------------------------------------------------- nhân viên (chỉ Admin)

staff_router = APIRouter(prefix="/admin/staff", tags=["admin: staff"])

StaffManager = Annotated[Principal, Depends(require(Perm.STAFF_MANAGE))]


def _actor(p: Principal) -> AuditActor:
    return AuditActor(type=p.actor_type, id=p.actor_id, label=p.label)


@staff_router.get("", response_model=list[staff.StaffOut])
async def list_staff(_: StaffManager, session: SessionDep):
    """Mã, họ tên, tên đăng nhập, trạng thái, lần đăng nhập gần nhất, số phiên đang mở."""
    return await staff.list_staff(session)


@staff_router.post("", response_model=staff.StaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(data: staff.StaffCreateIn, principal: StaffManager, session: SessionDep):
    """Chỉ họ tên + mật khẩu; mã ``NV…`` + tên đăng nhập tự sinh."""
    return await staff.create_staff(session, _actor(principal), data)


@staff_router.patch("/{staff_id}", response_model=staff.StaffOut)
async def update_staff(
    staff_id: int, data: staff.StaffUpdateIn, principal: StaffManager, session: SessionDep
):
    """Sửa họ tên; khóa (thu hồi mọi phiên – ``account_disabled``) / mở khóa. 404 E-STAFF-1."""
    return await staff.update_staff(session, _actor(principal), staff_id, data)


@staff_router.post("/{staff_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_staff_password(
    staff_id: int, data: staff.StaffPasswordIn, principal: StaffManager, session: SessionDep
):
    """Đặt lại mật khẩu: thu hồi mọi phiên (``password_changed``), gỡ khóa do nhập sai."""
    await staff.reset_staff_password(session, _actor(principal), staff_id, data.password)


@staff_router.get("/{staff_id}/sessions", response_model=list[staff.StaffSessionOut])
async def list_staff_sessions(staff_id: int, _: StaffManager, session: SessionDep):
    """Phiên đang mở (IP đã che)."""
    return await staff.list_staff_sessions(session, staff_id)


@staff_router.delete("/{staff_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_staff_session(
    staff_id: int, session_id: int, principal: StaffManager, session: SessionDep
):
    """Đăng xuất từ xa một phiên (``revoked_by_admin``). 404 E-STAFF-1 / E-STAFF-2."""
    await staff.revoke_staff_session(session, _actor(principal), staff_id, session_id)

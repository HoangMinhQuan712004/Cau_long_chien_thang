"""Tự quản lý tài khoản: khách đổi mật khẩu (T-015 – bắt buộc lần đầu với tài khoản hội viên);
Admin / NV xem Hồ sơ của tôi, tự đổi mật khẩu, quản lý nơi đăng nhập (``/admin/account``)."""

from fastapi import APIRouter, Depends, Response, status

from app.core.middleware import require_origin
from app.core.permissions import OptionalPrincipal
from app.core.ratelimit import rate_limit
from app.modules.auth import admin_account, cookies, member_accounts, membership, menu, sessions
from app.modules.auth.deps import CustomerAnyState, SessionDep
from app.modules.auth.router import AdminSessionDep
from app.modules.auth.schemas import (
    AdminPasswordChangeIn,
    AdminProfileIn,
    AdminProfileOut,
    AdminSessionOut,
    MySessionOut,
    PasswordChangeIn,
    RevokedOut,
    UserOut,
    user_out,
)

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_origin)])


@router.post("/password/change", response_model=UserOut)
async def change_password(
    data: PasswordChangeIn, user: CustomerAnyState, response: Response, session: SessionDep
):
    """Đổi mật khẩu; đang bắt đổi lần đầu thì không cần ``current_password``.

    Xong: bỏ cờ, JWT cũ hết hiệu lực, cấp cookie mới ngay. Lỗi: 400 E-AUTH-28 (mật khẩu hiện tại
    sai) · 422 ``weak_password`` / E-AUTH-26 (trùng SĐT).
    """
    updated = await member_accounts.change_password(
        session, user.id, data.current_password, data.new_password
    )
    cookies.set_auth_cookies(response, updated)
    out = user_out(updated)
    out.is_member = await membership.member_profile_id(session, updated) is not None
    return out


# ---------------------------------------------------------------- Admin / NV (phiên quản trị)

admin_account_router = APIRouter(prefix="/admin/account", tags=["admin: account"])


@admin_account_router.get("", response_model=AdminProfileOut)
async def admin_profile(current: AdminSessionDep):
    """Hồ sơ của tôi: chỉ cần phiên quản trị (Admin hoặc NV), không cần quyền riêng."""
    admin_session, user = current
    return admin_account.profile(admin_session, user)


@admin_account_router.patch(
    "", response_model=AdminProfileOut, dependencies=[Depends(require_origin)]
)
async def admin_rename(data: AdminProfileIn, current: AdminSessionDep, session: SessionDep):
    """Chỉ Admin tự sửa họ tên (NV -> 403 E-AUTH-2). Tên rỗng / quá 50 ký tự -> 422."""
    admin_session, user = current
    updated = await admin_account.rename(session, user.id, data.full_name)
    return admin_account.profile(admin_session, updated)


@admin_account_router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_origin),
        Depends(rate_limit("admin.password_change", 5, window_s=600, key="user")),
    ],
)
async def admin_change_password(
    data: AdminPasswordChangeIn, current: AdminSessionDep, session: SessionDep
):
    """Tự đổi mật khẩu: thu hồi mọi phiên quản trị khác (``password_changed``), giữ phiên này.

    Lỗi: 400 E-AUTH-28 (mật khẩu hiện tại sai) · 422 ``weak_password`` · 429 E-SEC-5.
    """
    admin_session, user = current
    await admin_account.change_password(
        session, user.id, admin_session.id, data.current_password, data.new_password
    )


@admin_account_router.get("/sessions", response_model=list[MySessionOut])
async def my_sessions(current: AdminSessionDep, session: SessionDep):
    """Nơi đang đăng nhập: thiết bị, hệ điều hành, trình duyệt, giờ đăng nhập (không trả IP)."""
    admin_session, _ = current
    return await admin_account.list_sessions(session, admin_session)


@admin_account_router.post(
    "/sessions/revoke-others", response_model=RevokedOut, dependencies=[Depends(require_origin)]
)
async def revoke_other_sessions(current: AdminSessionDep, session: SessionDep):
    """Đăng xuất mọi phiên khác của chính mình, giữ phiên này."""
    admin_session, user = current
    return RevokedOut(
        revoked=await admin_account.revoke_other_sessions(session, user, admin_session)
    )


@admin_account_router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_origin)],
)
async def revoke_my_session(session_id: int, current: AdminSessionDep, session: SessionDep):
    """Đăng xuất một phiên khác. 400 E-AUTH-33 (phiên đang dùng) · 404 E-STAFF-2."""
    admin_session, user = current
    await admin_account.revoke_session(session, user, admin_session, session_id)


# ---------------------------------------------------------------- /admin/auth/me

admin_me_router = APIRouter(prefix="/admin/auth", tags=["admin: auth"])


@admin_me_router.get("/me", response_model=AdminSessionOut)
async def admin_me(current: AdminSessionDep, principal: OptionalPrincipal, session: SessionDep):
    """Thẻ tài khoản + quyền (đọc từ bảng Phân quyền ở mỗi request)."""
    admin_session, user = current
    return AdminSessionOut(
        account=sessions.to_account(user),
        expires_at=admin_session.expires_at,
        perms=sorted(principal.perms) if principal else [],
        menu_order=await menu.menu_order(session),
    )

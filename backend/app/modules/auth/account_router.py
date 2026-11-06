"""Tự quản lý tài khoản: khách đổi mật khẩu (T-015 – bắt buộc lần đầu với tài khoản hội viên);
Admin / NV xem Hồ sơ của tôi, tự đổi mật khẩu, quản lý nơi đăng nhập (``/admin/account``),
tự đổi / xóa ảnh đại diện (``/admin/auth/me/avatar``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Path, Response, UploadFile, status

from app.core import images
from app.core.config import settings
from app.core.middleware import require_origin
from app.core.permissions import OptionalPrincipal
from app.core.ratelimit import rate_limit
from app.modules.auth import admin_account, cookies, member_accounts, membership, menu, sessions
from app.modules.auth.deps import CustomerAnyState, SessionDep
from app.modules.auth.router import AdminSessionDep
from app.modules.auth.schemas import (
    AdminAvatarOut,
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
async def admin_profile(current: AdminSessionDep, session: SessionDep):
    """Hồ sơ của tôi: chỉ cần phiên quản trị (Admin hoặc NV), không cần quyền riêng."""
    admin_session, user = current
    return await admin_account.profile(session, admin_session, user)


@admin_account_router.patch(
    "", response_model=AdminProfileOut, dependencies=[Depends(require_origin)]
)
async def admin_rename(data: AdminProfileIn, current: AdminSessionDep, session: SessionDep):
    """Chỉ Admin tự sửa họ tên (NV -> 403 E-AUTH-2). Tên rỗng / quá 50 ký tự -> 422."""
    admin_session, user = current
    updated = await admin_account.rename(session, user.id, data.full_name)
    return await admin_account.profile(session, admin_session, updated)


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
        avatar_url=await sessions.my_avatar_url(session, user.id),
    )


# Ảnh chỉ phiên quản trị xem được -> ``private``: proxy dùng chung không được lưu; ``?v=`` phá cache
ADMIN_AVATAR_CACHE = "private, max-age=31536000, immutable"


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@admin_me_router.put(
    "/me/avatar",
    response_model=AdminAvatarOut,
    dependencies=[
        Depends(require_origin),
        Depends(_no_store),
        Depends(rate_limit("admin.avatar", 20, key="user")),
    ],
)
async def upload_my_avatar(
    current: AdminSessionDep,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="JPG / PNG / WebP ≤ 5 MB")],
    crop_x: Annotated[int, Form(ge=0)],
    crop_y: Annotated[int, Form(ge=0)],
    crop_size: Annotated[int, Form(ge=1)],
):
    """Tự đổi ảnh đại diện: cắt vuông theo khung (pixel ảnh gốc, sau khi xoay theo EXIF), lưu ngay.

    422 / 413 E-HV-13 (định dạng / dung lượng / vùng cắt) · 429 E-SEC-5.
    """
    _, user = current
    data = await file.read(settings.AVATAR_MAX_BYTES + 1)
    crop = images.Crop(crop_x, crop_y, crop_size)
    etag = await admin_account.save_avatar(session, user.id, data, crop)
    return {"avatar_url": sessions.avatar_url(user.id, etag)}


@admin_me_router.delete(
    "/me/avatar",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(require_origin),
        Depends(rate_limit("admin.avatar", 20, key="user")),
    ],
)
async def delete_my_avatar(current: AdminSessionDep, session: SessionDep):
    """Tự xóa ảnh -> về chữ cái. Chưa có ảnh -> vẫn 204."""
    _, user = current
    await admin_account.delete_avatar(session, user.id)


@admin_me_router.get(
    "/avatars/{user_id}",
    response_class=Response,
    responses={200: {"content": {"image/webp": {}}}, 304: {}, 404: {}},
)
async def admin_avatar(
    user_id: Annotated[int, Path(ge=1)],
    _: AdminSessionDep,
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
    v: str | None = None,
):
    """Ảnh đại diện tài khoản quản trị – chỉ phiên quản trị xem được. ``v`` = etag để phá cache."""
    stored = await admin_account.load_avatar(session, user_id)
    return images.image_response(stored, if_none_match, ADMIN_AVATAR_CACHE)

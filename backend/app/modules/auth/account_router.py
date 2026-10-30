"""Tài khoản khách tự quản lý: đổi mật khẩu (T-015 – bắt buộc lần đầu với tài khoản hội viên)."""

from fastapi import APIRouter, Depends, Response

from app.core.middleware import require_origin
from app.modules.auth import cookies, member_accounts, membership
from app.modules.auth.deps import CustomerAnyState, SessionDep
from app.modules.auth.schemas import PasswordChangeIn, UserOut, user_out

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

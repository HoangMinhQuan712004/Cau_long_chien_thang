"""Ai đang gọi API: phiên quản trị (cookie ``admin_session``) hoặc JWT khách (ADR-008 §3).

Mỗi trình duyệt chỉ giữ một loại phiên. Có cookie ``admin_session`` -> chỉ dùng nguồn đó (hỏng ->
không đăng nhập, kèm lý do). Không có -> JWT khách (cookie ``access_token`` hoặc Bearer), chỉ chấp
nhận tài khoản **khách** đúng ``token_version``.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import decode_token
from app.modules.auth import service, sessions
from app.modules.auth.models import AdminSession, User

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
ADMIN_SESSION_COOKIE = "admin_session"

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthState:
    user: User | None
    admin_session: AdminSession | None
    # Lý do không đăng nhập (E-AUTH-1 ``reason``): unauthenticated / expired / …
    reason: str = "unauthenticated"


async def get_auth_state(
    request: Request,
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthState:
    admin_token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if admin_token:
        try:
            admin_session, user = await sessions.resolve(session, admin_token)
        except sessions.SessionError as e:
            return AuthState(None, None, e.reason)
        return AuthState(user, admin_session)

    token = request.cookies.get(ACCESS_COOKIE) or (creds.credentials if creds else None)
    claims = decode_token(token, "access") if token else None
    if claims is None:
        return AuthState(None, None)
    user = await service.get_customer(session, int(claims.subject), claims.version)
    return AuthState(user, None)


AuthStateDep = Annotated[AuthState, Depends(get_auth_state)]


def unauthenticated(reason: str = "unauthenticated") -> AppError:
    messages = {
        "expired": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
        "password_changed": "Mật khẩu đã được đổi. Vui lòng đăng nhập lại.",
        "account_disabled": "Tài khoản đã bị khóa.",
    }
    return AppError("E-AUTH-1", messages.get(reason, "Chưa đăng nhập"), 401, reason=reason)


async def get_current_customer(state: AuthStateDep) -> User:
    """Khách đã đăng nhập (JWT); phiên quản trị không dùng làm khách (T-013 SEC5)."""
    if state.user is None or state.admin_session is not None:
        raise unauthenticated(state.reason)
    return state.user


CurrentCustomer = Annotated[User, Depends(get_current_customer)]

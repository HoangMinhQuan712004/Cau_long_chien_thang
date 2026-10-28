"""API đăng nhập/đăng ký/phiên: cổng khách (JWT) và khu quản trị (phiên DB)."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.errors import NotFound, Unauthorized, coded_error
from app.core.security import decode_token
from app.modules.auth import service
from app.modules.auth.cookies import (
    delete_admin_cookie,
    delete_auth_cookies,
    set_auth_cookies,
    set_cookie,
)
from app.modules.auth.deps import (
    ADMIN_SESSION_COOKIE,
    REFRESH_COOKIE,
    AdminContext,
    ClientIP,
    CurrentUser,
    SessionDep,
)
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    AdminSessionOut,
    AdminSignInOut,
    CustomerSignInOut,
    GoogleSignInIn,
    LoginIn,
    RegisterIn,
    SignInOut,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])
admin_auth_router = APIRouter(prefix="/admin/auth", tags=["admin: auth"])


# Câu báo theo SRS (Phụ lục A)
_LOGIN_ERRORS: dict[service.LoginErrorCode, tuple[int, str]] = {
    "E-001": (
        status.HTTP_401_UNAUTHORIZED,
        "Số điện thoại, tên đăng nhập hoặc mật khẩu không đúng.",
    ),
    "E-002": (
        status.HTTP_423_LOCKED,
        f"Bạn đã nhập sai {settings.LOGIN_MAX_ATTEMPTS} lần. "
        f"Vui lòng thử lại sau {settings.LOGIN_LOCK_MINUTES} phút.",
    ),
    # giới hạn theo IP
    "E-008": (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Có quá nhiều lần đăng nhập sai từ mạng này. "
        f"Vui lòng thử lại sau {settings.LOGIN_IP_WINDOW_MINUTES} phút.",
    ),
}


def _login_http_error(error: service.LoginError) -> HTTPException:
    return coded_error(error.code, *_LOGIN_ERRORS[error.code], retry_after=error.retry_after)


def _customer_signed_in(response: Response, user: User) -> CustomerSignInOut:
    # mỗi trình duyệt một loại phiên
    delete_admin_cookie(response)
    set_auth_cookies(response, user)
    return CustomerSignInOut(account=UserOut.model_validate(user))


@router.post(
    "/sign-in",
    response_model=SignInOut,
    responses={
        401: {"description": "E-001"},
        423: {"description": "E-002"},
        429: {"description": "E-008 (IP)"},
    },
)
async def sign_in(
    data: LoginIn,
    response: Response,
    session: SessionDep,
    ip: ClientIP,
    user_agent: Annotated[str | None, Header()] = None,
):
    """Một màn đăng nhập cho khách, Admin và nhân viên; `kind` cho biết đi tới khu nào."""
    try:
        user, admin_login = await service.sign_in(
            session, data.login, data.password, user_agent, ip
        )
    except service.LoginError as e:
        raise _login_http_error(e) from e
    if admin_login is None:
        return _customer_signed_in(response, user)
    admin_session, token = admin_login
    delete_auth_cookies(response)
    set_cookie(response, ADMIN_SESSION_COOKIE, token, settings.ADMIN_SESSION_HOURS * 3600)
    return AdminSignInOut(account=service.to_account(user), expires_at=admin_session.expires_at)


_GOOGLE_ERRORS: dict[service.GoogleErrorCode, tuple[int, str]] = {
    "google_invalid": (
        status.HTTP_401_UNAUTHORIZED,
        "Không đăng nhập được bằng Google. Vui lòng thử lại.",
    ),
    "google_unavailable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Chưa kết nối được Google. Vui lòng thử lại sau.",
    ),
}


@router.post(
    "/google",
    response_model=CustomerSignInOut,
    responses={
        401: {"description": "code: google_invalid"},
        404: {"description": "code: google_disabled (chưa đặt GOOGLE_CLIENT_ID)"},
        429: {"description": "E-008 (IP)"},
        503: {"description": "code: google_unavailable (không tải được khóa Google)"},
    },
)
async def google_sign_in(
    data: GoogleSignInIn, response: Response, session: SessionDep, ip: ClientIP
):
    """Đăng nhập khách bằng ID token của Google Identity Services; lần đầu tạo tài khoản."""
    if not settings.GOOGLE_CLIENT_ID:
        raise NotFound({"code": "google_disabled", "message": "Chưa bật đăng nhập bằng Google."})
    try:
        user = await service.google_sign_in(session, data.credential, ip)
    except service.LoginError as e:
        raise _login_http_error(e) from e
    except service.GoogleSignInError as e:
        raise coded_error(e.code, *_GOOGLE_ERRORS[e.code]) from e
    return _customer_signed_in(response, user)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={429: {"description": "code: register_rate_limited (+ retry_after)"}},
)
async def register(data: RegisterIn, response: Response, session: SessionDep, ip: ClientIP):
    try:
        user = await service.create_user(session, data, ip)
    except service.RegisterRateLimited as e:
        raise coded_error(
            "register_rate_limited",
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Có quá nhiều lần đăng ký từ mạng này. Vui lòng thử lại sau.",
            retry_after=e.retry_after,
        ) from e
    set_auth_cookies(response, user)
    return user


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, session: SessionDep):
    token = request.cookies.get(REFRESH_COOKIE)
    claims = decode_token(token, "refresh") if token else None
    user = await service.get_customer(session, claims) if claims else None
    if user is None:
        raise Unauthorized("Phiên đăng nhập đã hết hạn")
    set_auth_cookies(response, user)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    delete_auth_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@admin_auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def admin_logout(request: Request, response: Response, session: SessionDep):
    await service.admin_logout(session, request.cookies.get(ADMIN_SESSION_COOKIE))
    delete_admin_cookie(response)


@admin_auth_router.get(
    "/me",
    response_model=AdminSessionOut,
    responses={
        401: {
            "description": "code: unauthenticated | expired | password_changed | account_disabled"
        }
    },
)
async def admin_me(context: AdminContext):
    admin_session, user = context
    return AdminSessionOut(account=service.to_account(user), expires_at=admin_session.expires_at)

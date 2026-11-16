"""Đặt / xóa cookie phiên: JWT khách (``access_token`` + ``refresh_token``) và ``admin_session``."""

from fastapi import Response

from app.core.config import settings
from app.core.security import create_token
from app.modules.auth.deps import ACCESS_COOKIE, ADMIN_SESSION_COOKIE, REFRESH_COOKIE
from app.modules.auth.models import User

# T-077: refresh token path "/" để proxy của Next (render phía server) đọc được và tự làm mới;
# trước đây chỉ gửi kèm API auth -> xóa cookie cũ cùng tên ở path này
REFRESH_PATH = "/"
LEGACY_REFRESH_PATH = f"{settings.API_PREFIX}/auth"


def _common() -> dict:
    return {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
        "domain": settings.COOKIE_DOMAIN,
    }


def set_auth_cookies(response: Response, user: User) -> None:
    """JWT khách mang ``ver`` = ``token_version``; xóa phiên quản trị nếu có (một loại phiên)."""
    version = user.token_version
    response.set_cookie(
        ACCESS_COOKIE,
        create_token(str(user.id), "access", version),
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        path="/",
        **_common(),
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(str(user.id), "refresh", version),
        max_age=settings.REFRESH_TOKEN_DAYS * 86400,
        path=REFRESH_PATH,
        **_common(),
    )
    response.delete_cookie(REFRESH_COOKIE, path=LEGACY_REFRESH_PATH, **_common())
    delete_admin_cookie(response)


def delete_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", **_common())
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH, **_common())
    response.delete_cookie(REFRESH_COOKIE, path=LEGACY_REFRESH_PATH, **_common())


def set_admin_cookie(response: Response, token: str) -> None:
    """Cookie phiên quản trị (hạn = hạn trượt của phiên); xóa JWT khách nếu có."""
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=settings.ADMIN_SESSION_IDLE_DAYS * 86400,
        path="/",
        **_common(),
    )
    delete_auth_cookies(response)


def admin_cookie_header(token: str) -> bytes:
    """Giá trị ``Set-Cookie`` gia hạn cookie ``admin_session`` (middleware gắn vào response)."""
    probe = Response()
    probe.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=settings.ADMIN_SESSION_IDLE_DAYS * 86400,
        path="/",
        **_common(),
    )
    return probe.headers["set-cookie"].encode("latin-1")


def delete_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/", **_common())

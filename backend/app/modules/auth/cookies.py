"""Đặt/xóa cookie phiên: JWT khách và `admin_session`."""

from functools import partial

from fastapi import Response

from app.core.config import settings
from app.core.security import create_token
from app.modules.auth.deps import ACCESS_COOKIE, ADMIN_SESSION_COOKIE, REFRESH_COOKIE
from app.modules.auth.models import User

_COOKIE_COMMON = {
    "httponly": True,
    "secure": settings.COOKIE_SECURE,
    "samesite": "lax",
    "domain": settings.COOKIE_DOMAIN,
}


_REFRESH_PATH = f"{settings.API_PREFIX}/auth"  # refresh token chỉ gửi kèm API auth


def set_cookie(response: Response, name: str, value: str, max_age: int, path: str = "/") -> None:
    response.set_cookie(name, value, max_age=max_age, path=path, **_COOKIE_COMMON)


def delete_cookie(response: Response, name: str, path: str = "/") -> None:
    # cùng thuộc tính lúc đặt để ghi đè được
    response.delete_cookie(name, path=path, **_COOKIE_COMMON)


def set_auth_cookies(response: Response, user: User) -> None:
    token = partial(create_token, str(user.id), version=user.token_version)
    set_cookie(response, ACCESS_COOKIE, token("access"), settings.ACCESS_TOKEN_MINUTES * 60)
    set_cookie(
        response,
        REFRESH_COOKIE,
        token("refresh"),
        settings.REFRESH_TOKEN_DAYS * 86400,
        _REFRESH_PATH,
    )


def delete_auth_cookies(response: Response) -> None:
    delete_cookie(response, ACCESS_COOKIE)
    delete_cookie(response, REFRESH_COOKIE, _REFRESH_PATH)


def delete_admin_cookie(response: Response) -> None:
    delete_cookie(response, ADMIN_SESSION_COOKIE)

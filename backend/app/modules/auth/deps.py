from ipaddress import ip_address
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import parse_networks, settings
from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.modules.auth.models import AdminSession, Role, User
from app.modules.auth.service import SessionError, get_customer, resolve_admin_session

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
# Cookie phiên khu quản trị
ADMIN_SESSION_COOKIE = "admin_session"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _from_trusted_proxy(request: Request) -> bool:
    """Kết nối đến từ proxy trong `TRUSTED_PROXIES` (Next rewrite, Caddy…)."""
    host = request.client.host if request.client else None
    try:
        address = ip_address(host or "")
    except ValueError:
        return False
    return any(address in network for network in parse_networks(settings.TRUSTED_PROXIES))


def client_ip(request: Request) -> str | None:
    """IP khách: giá trị cuối của XFF nếu đến từ proxy tin cậy, ngược lại IP kết nối."""
    direct = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _from_trusted_proxy(request):
        return forwarded.split(",")[-1].strip()[:45] or direct
    return direct


ClientIP = Annotated[str | None, Depends(client_ip)]

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SESSION_COOKIES = (ACCESS_COOKIE, REFRESH_COOKIE, ADMIN_SESSION_COOKIE)


def _request_host(request: Request) -> str | None:
    """Host trình duyệt đã gọi (X-Forwarded-Host qua proxy tin cậy, ngược lại Host)."""
    if _from_trusted_proxy(request) and (forwarded := request.headers.get("x-forwarded-host")):
        return forwarded.split(",")[0].strip()
    return request.headers.get("host")


def check_origin(request: Request) -> None:
    """Chống CSRF: request đổi trạng thái kèm cookie phiên từ Origin lạ ⇒ 403."""
    origin = request.headers.get("origin")
    if origin is None or request.method not in _UNSAFE_METHODS:
        return
    if not any(name in request.cookies for name in _SESSION_COOKIES):
        return
    if origin in settings.CORS_ORIGINS or urlsplit(origin).netloc == _request_host(request):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        {"code": "origin_forbidden", "message": "Yêu cầu không đến từ trang của sân."},
    )


_bearer = HTTPBearer(auto_error=False)


async def get_optional_user(
    request: Request,
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    # Cookie (web) trước, Bearer (mobile/tool) sau
    token = request.cookies.get(ACCESS_COOKIE) or (creds.credentials if creds else None)
    if not token:
        return None
    claims = decode_token(token, "access")
    if claims is None:
        return None
    return await get_customer(session, claims)


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    if not user:
        raise Unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_admin_context(request: Request, session: SessionDep) -> tuple[AdminSession, User]:
    """Khu quản trị chỉ nhận phiên `admin_session`; 401 kèm `code` để frontend báo đúng lý do."""
    try:
        return await resolve_admin_session(session, request.cookies.get(ADMIN_SESSION_COOKIE))
    except SessionError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": e.code}) from e


# Tra phiên một lần mỗi request
AdminContext = Annotated[tuple[AdminSession, User], Depends(get_admin_context)]


async def get_staff_user(context: AdminContext) -> User:
    return context[1]


StaffUser = Annotated[User, Depends(get_staff_user)]


async def get_admin_user(user: StaffUser) -> User:
    if user.role != Role.ADMIN:
        raise Forbidden()
    return user


AdminUser = Annotated[User, Depends(get_admin_user)]

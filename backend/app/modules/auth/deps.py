from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.modules.auth.models import Role, User
from app.modules.auth.service import get_user

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


async def get_optional_user(
    request: Request,
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User | None:
    # Ưu tiên httpOnly cookie (web), fallback Bearer header (mobile/tool)
    token = request.cookies.get(ACCESS_COOKIE) or (creds.credentials if creds else None)
    if not token:
        return None
    sub = decode_token(token, "access")
    if not sub:
        return None
    user = await get_user(session, int(sub))
    if not user or not user.is_active:
        return None
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    if not user:
        raise Unauthorized()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_roles(*roles: Role):
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise Forbidden()
        return user

    return checker


StaffUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.STAFF))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.privacy import mask_phone
from app.core.security import create_token, decode_token
from app.modules.auth import service
from app.modules.auth.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    AdminUser,
    CurrentUser,
    SessionDep,
)
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginIn, RegisterIn, StaffCreateIn, UserListItem, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, user_id: int) -> None:
    common = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": "lax",
        "domain": settings.COOKIE_DOMAIN,
    }
    response.set_cookie(
        ACCESS_COOKIE,
        create_token(str(user_id), "access"),
        max_age=settings.ACCESS_TOKEN_MINUTES * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        create_token(str(user_id), "refresh"),
        max_age=settings.REFRESH_TOKEN_DAYS * 86400,
        path=f"{settings.API_PREFIX}/auth",
        **common,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, response: Response, session: SessionDep):
    user = await service.create_user(session, data)
    _set_auth_cookies(response, user.id)
    return user


@router.post("/login", response_model=UserOut)
async def login(data: LoginIn, response: Response, session: SessionDep):
    user = await service.authenticate(session, data.email, data.password)
    _set_auth_cookies(response, user.id)
    return user


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, session: SessionDep):
    token = request.cookies.get(REFRESH_COOKIE)
    sub = decode_token(token, "refresh") if token else None
    user = await service.get_user(session, int(sub)) if sub else None
    if not user or not user.is_active:
        raise Unauthorized("Phiên đăng nhập đã hết hạn")
    _set_auth_cookies(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=settings.COOKIE_DOMAIN)
    response.delete_cookie(
        REFRESH_COOKIE, path=f"{settings.API_PREFIX}/auth", domain=settings.COOKIE_DOMAIN
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


# --- Quản lý tài khoản (chỉ chủ sân) ---
admin_router = APIRouter(prefix="/admin/users", tags=["admin: users"])


@admin_router.get("", response_model=list[UserListItem])
async def list_users(_: AdminUser, session: SessionDep):
    result = await session.scalars(select(User).order_by(User.id.desc()).limit(200))
    return [
        UserListItem(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            phone_masked=mask_phone(u.phone),
            role=u.role,
            is_active=u.is_active,
        )
        for u in result
    ]


@admin_router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_staff(data: StaffCreateIn, _: AdminUser, session: SessionDep):
    return await service.create_user(session, data, role=data.role)

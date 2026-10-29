"""Đăng nhập khách bằng Google (T-013 AC20, SEC7; port PR #17).

- Kiểm ID token của Google Identity Services: RS256, ``aud`` = ``GOOGLE_CLIENT_ID``, ``iss``,
  ``exp``; khóa công khai (JWKS) cache 1 giờ, ``kid`` lạ thì tải lại.
- Tìm theo ``google_sub``; chưa có -> tạo khách (không mật khẩu, không SĐT).
  **Không bao giờ nối tài khoản theo email.** Tạo đồng thời -> một tài khoản.
- Token sai tính vào giới hạn đăng nhập sai theo IP (AC3).
"""

import asyncio
from dataclasses import dataclass
from functools import cache

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import login
from app.modules.auth.models import Role, User

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]
DEFAULT_NAME = "Khách Google"


class GoogleTokenError(Exception):
    """ID token không hợp lệ."""


class GoogleUnavailable(Exception):
    """Không tải được khóa công khai của Google."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    name: str | None
    email: str | None  # chỉ khi ``email_verified``


def disabled() -> AppError:
    return AppError("E-AUTH-19", "Chưa bật đăng nhập bằng Google.", 404)


def invalid() -> AppError:
    return AppError("E-AUTH-20", "Không đăng nhập được bằng Google. Vui lòng thử lại.", 401)


def unavailable() -> AppError:
    return AppError("E-AUTH-21", "Chưa kết nối được Google. Vui lòng thử lại sau.", 503)


@cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_jwk_set=True, lifespan=3600, timeout=5)


def _signing_key(credential: str):
    """Khóa ký theo ``kid`` của token (chặn I/O – gọi trong thread). Test thay hàm này."""
    return _jwks_client().get_signing_key_from_jwt(credential).key


async def verify_id_token(credential: str) -> GoogleIdentity:
    try:
        key = await asyncio.to_thread(_signing_key, credential)
    except jwt.PyJWKClientConnectionError as e:
        raise GoogleUnavailable from e
    except jwt.PyJWTError as e:
        raise GoogleTokenError from e
    try:
        payload = jwt.decode(
            credential,
            key,
            algorithms=["RS256"],  # cố định: token HS256 / "none" bị từ chối
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise GoogleTokenError from e
    sub = payload["sub"]
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        raise GoogleTokenError
    name = payload.get("name")
    email = payload.get("email") if payload.get("email_verified") is True else None
    return GoogleIdentity(
        sub=sub,
        name=" ".join(name.split())[:255] if isinstance(name, str) and name.strip() else None,
        email=email[:255] if isinstance(email, str) else None,
    )


async def sign_in(session: AsyncSession, credential: str, ip: str | None) -> User:
    """ID token hợp lệ -> tài khoản khách (commit). Lỗi: E-AUTH-12 / 19 / 20 / 21."""
    if not settings.GOOGLE_CLIENT_ID:
        raise disabled()
    await login.ensure_ip_allowed(ip)
    try:
        identity = await verify_id_token(credential)
    except GoogleUnavailable as e:
        raise unavailable() from e
    except GoogleTokenError as e:
        await login.record_ip_failure(ip)
        raise invalid() from e

    query = select(User).where(User.google_sub == identity.sub).with_for_update()
    user = await session.scalar(query)
    if user is None:
        try:
            async with session.begin_nested():
                user = User(
                    google_sub=identity.sub,
                    google_email=identity.email,
                    full_name=identity.name or DEFAULT_NAME,
                    role=Role.MEMBER,
                    is_active=True,
                )
                session.add(user)
        except IntegrityError:
            # Lần đăng nhập song song vừa tạo -> dùng lại tài khoản đó
            user = await session.scalar(query)
            if user is None:
                raise
    # google_sub chỉ thuộc về khách còn hoạt động
    if user.role != Role.MEMBER or not user.is_active:
        await session.rollback()
        raise invalid()
    if identity.email is not None:
        user.google_email = identity.email
    await session.commit()
    await session.refresh(user)
    return user

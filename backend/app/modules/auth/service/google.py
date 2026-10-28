"""Đăng nhập khách bằng Google."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import utils
from app.modules.auth.models import (
    Role,
    User,
)
from app.modules.auth.service.common import (
    ensure_ip_allowed,
    record_failure,
)

GoogleErrorCode = Literal["google_invalid", "google_unavailable"]


class GoogleSignInError(Exception):
    def __init__(self, code: GoogleErrorCode) -> None:
        super().__init__(code)
        self.code: GoogleErrorCode = code


async def google_sign_in(session: AsyncSession, credential: str, ip: str | None) -> User:
    """Đăng nhập khách bằng ID token Google; lần đầu tạo tài khoản; token sai tính vào IP."""
    now = datetime.now(UTC)
    await ensure_ip_allowed(session, ip, now)
    try:
        identity = await utils.verify_google_id_token(credential)
    except utils.GoogleUnavailable as e:
        raise GoogleSignInError("google_unavailable") from e
    except utils.GoogleTokenError as e:
        await record_failure(session, ip, now)
        await session.commit()
        raise GoogleSignInError("google_invalid") from e

    query = select(User).where(User.google_sub == identity.sub).with_for_update()
    user = await session.scalar(query)
    if user is None:
        user = User(
            google_sub=identity.sub,
            google_email=identity.email,
            full_name=identity.name or "Khách Google",
            role=Role.CUSTOMER,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # lần đăng nhập song song đã tạo ⇒ dùng lại
            await session.rollback()
            user = await session.scalar(query)
            if user is None:
                raise
    # google_sub chỉ của khách
    if user.role != Role.CUSTOMER or not user.is_active:
        await session.rollback()
        raise GoogleSignInError("google_invalid")
    if identity.email is not None:
        user.google_email = identity.email
    await session.commit()
    await session.refresh(user)
    return user

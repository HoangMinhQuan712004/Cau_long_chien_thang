"""Tra tài khoản – dùng chung trong module auth (không import hạ tầng HTTP để tránh vòng import)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.modules.auth.models import Role, User


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_customer(session: AsyncSession, user_id: int, version: int) -> User | None:
    """Chủ JWT khách: khách đang hoạt động, đúng ``token_version``; không thì None."""
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.role != Role.MEMBER:
        return None
    if version != user.token_version:
        return None
    return user


async def check_password(session: AsyncSession, user_id: int, password: str) -> bool:
    """Xác nhận lại mật khẩu của người đang đăng nhập (thao tác nhạy cảm, T-012)."""
    user = await get_user(session, user_id)
    return bool(
        user
        and user.is_active
        and user.hashed_password
        and password
        and verify_password(password, user.hashed_password)
    )

"""Mặt tiền module Xác thực cho module khác (không truy vấn bảng ``users`` trực tiếp)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import service


async def check_password(session: AsyncSession, user_id: int, password: str) -> bool:
    """Mật khẩu đúng của tài khoản ``user_id`` (đang hoạt động)."""
    return await service.check_password(session, user_id, password)

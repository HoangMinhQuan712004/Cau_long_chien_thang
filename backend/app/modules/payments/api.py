"""Mặt tiền của module Thanh toán – module khác (web_booking) chỉ gọi các hàm ở đây."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments import service
from app.modules.payments.schemas import BankInfo

__all__ = ["BankInfo", "bank_info", "online_enabled"]


async def online_enabled(session: AsyncSession) -> bool:
    """Công tắc Nhận đặt online bật và đủ cấu hình (DB, hoặc .env khi chưa cài trên trang)."""
    return await service.online_enabled(session)


async def bank_info(session: AsyncSession, amount: int, pay_ref: str) -> BankInfo | None:
    """Thông tin chuyển khoản + URL ảnh QR (``None`` khi chưa đủ cấu hình)."""
    return await service.bank_info(session, amount, pay_ref)

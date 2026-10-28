"""Mặt tiền của module Thanh toán – module khác (web_booking) chỉ gọi các hàm ở đây."""

from app.modules.payments import service
from app.modules.payments.schemas import BankInfo

__all__ = ["BankInfo", "bank_info", "online_enabled"]


def online_enabled() -> bool:
    """Đủ cấu hình SePay (5 biến) -> nhận đặt online."""
    return service.online_enabled()


def bank_info(amount: int, pay_ref: str) -> BankInfo | None:
    """Thông tin chuyển khoản + URL ảnh QR (``None`` khi chưa cấu hình)."""
    return service.bank_info(amount, pay_ref)

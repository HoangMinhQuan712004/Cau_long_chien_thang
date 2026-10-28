"""Gửi OTP qua Zalo ZNS (chạy trong worker). Kết nối thật làm sau – TODO(zalo-zns)."""

import logging

from app.core.config import settings
from app.core.privacy import mask_phone

logger = logging.getLogger(__name__)


async def send_otp(phone: str, otp: str) -> bool:
    """Gửi mã; trả False khi chưa gửi được. **Không bao giờ ghi OTP ra log** ở đây."""
    if not settings.zalo_configured:
        logger.warning("Chưa cấu hình Zalo ZNS – không gửi được OTP tới %s", mask_phone(phone))
        return False
    # TODO(zalo-zns): gọi ZNS template API (ZALO_TEMPLATE_OTP) – cần access token từ
    # ZALO_REFRESH_TOKEN; làm khi người dùng có tài khoản Zalo OA.
    logger.error("Gửi Zalo ZNS chưa được cài đặt – chưa gửi OTP tới %s", mask_phone(phone))
    return False

"""Gửi Zalo ZNS (chạy trong worker); chưa có khóa ⇒ dev ghi OTP ra log."""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return all(
        (
            settings.ZALO_APP_ID,
            settings.ZALO_SECRET_KEY,
            settings.ZALO_REFRESH_TOKEN,
            settings.ZALO_TEMPLATE_OTP,
        )
    )


def mask_phone(phone: str) -> str:
    """`0912345678` ⇒ `09•••••678`."""
    return phone[:2] + "•" * (len(phone) - 5) + phone[-3:]


async def send_otp(phone: str, otp: str) -> None:
    if not is_configured():
        # chỉ in mã khi ENV=development
        if settings.ENV == "development":
            logger.info("OTP cho %s: %s", phone, otp)
        else:
            logger.warning("Chưa cấu hình Zalo ZNS – không gửi được OTP tới %s", mask_phone(phone))
        return
    # TODO(zalo-zns): gọi ZNS template API theo .claude/plans/thiet-ke-sepay-zalo.md
    # (cần httpx ở dependencies chính – hỏi người dùng trước)
    logger.error("Gửi Zalo ZNS chưa được cài đặt – không gửi OTP tới %s", mask_phone(phone))

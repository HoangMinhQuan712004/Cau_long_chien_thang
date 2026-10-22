"""Lắng nghe sự kiện và gửi thông báo.

Hiện chỉ ghi log. Thay bằng email (SMTP/Resend), Zalo ZNS hoặc SMS khi cần.
Việc gửi chậm nên đẩy sang worker (ARQ) thay vì chạy trong request.
"""

import logging

from app.core import events

logger = logging.getLogger(__name__)


@events.subscribe(events.BOOKING_CREATED)
async def on_booking_created(payload: dict) -> None:
    logger.info("Booking created: %s", payload)


@events.subscribe(events.BOOKING_CONFIRMED)
async def on_booking_confirmed(payload: dict) -> None:
    logger.info("Booking confirmed, gửi xác nhận cho khách: %s", payload)


@events.subscribe(events.BOOKING_CANCELLED)
async def on_booking_cancelled(payload: dict) -> None:
    logger.info("Booking cancelled: %s", payload)

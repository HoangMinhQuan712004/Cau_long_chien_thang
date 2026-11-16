"""Event bus nội bộ (in-process).

Module phát sự kiện thay vì gọi trực tiếp module khác (vd: bookings -> notifications).
Khi cần tách service, thay phần publish bằng message broker mà không đổi nơi gọi.
Chỉ publish SAU khi transaction đã commit.
"""

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[None]]
_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        _handlers[event].append(fn)
        return fn

    return decorator


async def publish(event: str, payload: dict[str, Any]) -> None:
    for handler in _handlers[event]:
        try:
            await handler(payload)
        except Exception:
            # Lỗi ở handler phụ (gửi mail...) không được làm hỏng luồng chính
            logger.exception("Event handler failed: %s", event)


# Tên sự kiện dùng chung
BOOKING_CREATED = "booking.created"
BOOKING_CONFIRMED = "booking.confirmed"
BOOKING_CANCELLED = "booking.cancelled"
BOOKING_MOVED = "booking.moved"

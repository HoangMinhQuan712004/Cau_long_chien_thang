"""Chỗ nối Zalo ZNS cho thông báo hội viên (T-017 AC23) – hiện chỉ ghi log (không SĐT)."""

import logging

from app.core import events
from app.modules.member_inbox.service import CREATED

logger = logging.getLogger(__name__)


@events.subscribe(CREATED)
async def send_zalo_stub(payload: dict) -> None:
    # Khi có Zalo ZNS: tra SĐT theo customer_id qua members.api rồi đẩy job gửi
    logger.info(
        "Member notification %s (%s): Zalo not configured", payload.get("id"), payload.get("kind")
    )

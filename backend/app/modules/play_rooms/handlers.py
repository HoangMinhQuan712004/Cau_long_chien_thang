"""Phản ứng với sự kiện booking engine (outbox, chạy trong worker) – tạo phòng chơi (T-017 AC1)."""

import logging

from app.core import events
from app.core.db import SessionLocal
from app.modules.play_rooms import lifecycle

logger = logging.getLogger(__name__)


@events.subscribe(events.BOOKING_CREATED)
async def create_room(payload: dict) -> None:
    """Khối booking mới (quầy tạo / tiền online về) -> phòng; đã có thì bỏ qua (job bù nếu lỡ)."""
    code = payload.get("code")
    if not code:
        return
    async with SessionLocal() as session:
        created = await lifecycle.ensure_for_codes(session, [code])
        await session.commit()
    if created:
        logger.info("Play room created for booking %s", code)

"""Phản ứng với sự kiện booking engine (outbox, chạy trong worker) – tạo phòng chơi (T-017 AC1)."""

import logging
from datetime import UTC, datetime

from app.core import events
from app.core.db import SessionLocal
from app.modules.member_inbox import api as inbox
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


@events.subscribe(events.BOOKING_CANCELLED)
async def close_cancelled_room(payload: dict) -> None:
    """Booking bị hủy -> đóng phòng, báo người liên quan (T-051). Vé không có phòng."""
    code = payload.get("code")
    if not code or payload.get("kind") != "booking":
        return
    async with SessionLocal() as session:
        closed = await lifecycle.close_cancelled(session, [code], datetime.now(UTC))
        await session.commit()
        await inbox.publish_created(session)
    if closed:
        logger.info("Play room closed for cancelled booking %s", code)

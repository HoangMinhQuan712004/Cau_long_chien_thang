"""Phản ứng với sự kiện của booking engine (outbox, chạy trong worker)."""

import logging

from app.core import events
from app.core.db import SessionLocal
from app.modules.payments import service

logger = logging.getLogger(__name__)


@events.subscribe("checkout.expired")
async def flag_partial_payments(payload: dict) -> None:
    """Lượt thanh toán hết hạn khi mới trả một phần -> các giao dịch đó cần hoàn (ADR-007 §5)."""
    pay_ref = payload.get("pay_ref")
    if not pay_ref:
        return
    async with SessionLocal() as session:
        count = await service.mark_expired_partials(session, pay_ref)
        await session.commit()
    if count:
        logger.info("Marked %s partial transactions of %s as refund_needed", count, pay_ref)

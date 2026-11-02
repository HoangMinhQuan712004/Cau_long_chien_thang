"""Phản ứng với sự kiện của booking engine (outbox, chạy trong worker)."""

import logging

from app.core import events
from app.core.db import SessionLocal
from app.modules.members import service

logger = logging.getLogger(__name__)


@events.subscribe("booking.online_paid")
@events.subscribe("ticket.online_paid")  # T-023 AC19: vé mua online gắn khách như booking online
async def create_temp_profile(payload: dict) -> None:
    """Tiền về cho booking / vé online -> tạo hồ sơ tạm theo SĐT nếu chưa có (ADR-007 §7,
    T-008 AC24).

    Đã có hồ sơ (hội viên hoặc hồ sơ tạm) -> giữ nguyên, kể cả tên. Lỗi ở đây không ảnh hưởng
    booking (đã commit trước khi phát sự kiện).
    """
    if payload.get("customer_kind") != "temp":
        return
    phone, name = payload.get("phone"), payload.get("full_name")
    if not phone or not name or not service.PHONE_RE.match(phone):
        return
    async with SessionLocal() as session:
        await service.upsert_temp(session, name[: service.NAME_MAX], phone)
        await session.commit()
    logger.info("Ensured temp profile for online booking %s", payload.get("codes"))

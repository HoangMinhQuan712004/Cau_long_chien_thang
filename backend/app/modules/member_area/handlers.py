"""Phản ứng với sự kiện booking engine (outbox, chạy trong worker) – thông báo khu hội viên."""

import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members

logger = logging.getLogger(__name__)

PHONE_REF = "phone:"


async def _member_with_account(session: AsyncSession, ref: str | None) -> int | None:
    """Hồ sơ **hội viên** có tài khoản web của ``customer_ref``; khách không tài khoản -> None."""
    if ref is None:
        return None
    if ref.startswith(PHONE_REF):  # đặt online trước khi có hồ sơ
        customer_id = await members.member_id_by_phone(session, ref.removeprefix(PHONE_REF))
    else:
        customer_id = await members.customer_id_of_ref(session, ref)
    if customer_id is None:
        return None
    person = (await members.room_people(session, {customer_id})).get(customer_id)
    if person is None or person.member_code is None:
        return None
    return (
        customer_id if person.phone in await auth.linked_phones(session, {person.phone}) else None
    )


def _hm(moment: dt.datetime) -> str:
    return f"{moment.hour}h" if moment.minute == 0 else f"{moment.hour}h{moment.minute:02d}"


def cancelled_text(payload: dict) -> str:
    """Không có lý do hủy (T-051: hội viên không thấy lý do)."""
    start = dt.datetime.fromisoformat(payload["start_at"]).astimezone(settings.tz)
    end = dt.datetime.fromisoformat(payload["end_at"]).astimezone(settings.tz)
    code = payload.get("order_code") or payload["code"]
    text = (
        f"Buổi {payload['resource_name']} {_hm(start)}–{_hm(end)} {start:%d/%m} ({code}) "
        "đã bị sân hủy."
    )
    if payload.get("was_paid"):
        amount = f"{payload.get('refund_amount', 0):,}".replace(",", ".")
        text += f" Sân ghi nhận hoàn {amount} đ."
    return text


@events.subscribe(events.BOOKING_CANCELLED)
async def notify_owner(payload: dict) -> None:
    code = payload.get("code")
    if not code:
        return
    async with SessionLocal() as session:
        ref = await engine.item_customer_ref(session, code)
        customer_id = await _member_with_account(session, ref)
        if customer_id is None:
            return
        await inbox.notify_once(
            session, customer_id, "booking.cancelled", code, cancelled_text(payload)
        )
        await session.commit()
        await inbox.publish_created(session)
    logger.info("Notified member about cancelled item %s", code)

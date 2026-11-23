"""Phản ứng với sự kiện booking engine (outbox, chạy trong worker) – thông báo khu hội viên.

T-076: thông báo trong hộp cũng là nguồn câu chữ cho push (``web_push`` nghe
``member.notification_created``). Câu không có SĐT / họ tên.
"""

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
HISTORY_LINK = "/hoi-vien/lich-su-choi"  # Lịch sử đặt sân / chơi của hội viên
METHOD_TEXT = {"cash": "tiền mặt", "transfer": "chuyển khoản"}


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


def _local(raw: str | dt.datetime) -> dt.datetime:
    moment = dt.datetime.fromisoformat(raw) if isinstance(raw, str) else raw
    return moment.astimezone(settings.tz)


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + " đ"


def _slot(start: dt.datetime, end: dt.datetime) -> str:
    """``18h–19h 16/11``."""
    return f"{_hm(start)}–{_hm(end)} {start:%d/%m}"


def _order_of(code: str) -> str:
    """Mã đơn của mã khối ``BK-…-NNN-NN``."""
    return code.rsplit("-", 1)[0]


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
            session,
            customer_id,
            "booking.cancelled",
            code,
            cancelled_text(payload),
            link=HISTORY_LINK,
        )
        await session.commit()
        await inbox.publish_created(session)
    logger.info("Notified member about cancelled item %s", code)


async def _notify_item_owner(item_code: str, kind: str, key: str, text: str, log_what: str) -> None:
    """Hội viên có tài khoản của khối / vé ``item_code`` -> một thông báo (``key`` chống trùng)."""
    async with SessionLocal() as session:
        ref = await engine.item_customer_ref(session, item_code)
        customer_id = await _member_with_account(session, ref)
        if customer_id is None:
            return
        created = await inbox.notify_once(session, customer_id, kind, key, text, link=HISTORY_LINK)
        await session.commit()
        await inbox.publish_created(session)
    if created is not None:
        logger.info("Notified member: %s %s", log_what, key)


def moved_text(payload: dict) -> str:
    """``BK-… : Sân 1 18h–19h 16/11 → Sân 3 18h–19h 16/11``."""
    before = _slot(_local(payload["from_start_at"]), _local(payload["from_end_at"]))
    after = _slot(_local(payload["start_at"]), _local(payload["end_at"]))
    return (
        f"{_order_of(payload['code'])} : {payload['from_resource_name']} {before} → "
        f"{payload['resource_name']} {after}"
    )


@events.subscribe(events.BOOKING_MOVED)
async def notify_moved(payload: dict) -> None:
    """Admin đổi sân / giờ một khối (T-076 AC12): mỗi lần đổi một thông báo; outbox giao lại cùng
    event -> cùng khóa ``{mã khối}@{event_id}``, không trùng."""
    code, event_id = payload.get("code"), payload.get("event_id")
    if not code or event_id is None or "from_start_at" not in payload:
        return
    await _notify_item_owner(
        code, "booking.moved", f"{code}@{event_id}", moved_text(payload), "booking moved"
    )


def paid_text(order_code: str, amount: int, method: str) -> str:
    """``BK-… · 400.000 đ · tiền mặt``."""
    return f"{order_code} · {_vnd(amount)} · {METHOD_TEXT.get(method, 'chuyển khoản')}"


@events.subscribe("payment.order_collected")
async def notify_collected(payload: dict) -> None:
    """Thu tại quầy (tiền mặt / QR): một thông báo cho cả lần thu của một đơn (T-076 AC14)."""
    codes, order_code, batch = (
        payload.get("codes"),
        payload.get("order_code"),
        payload.get("batch_id"),
    )
    if not codes or not order_code or not batch:
        return
    text = paid_text(order_code, int(payload.get("amount") or 0), str(payload.get("method")))
    await _notify_item_owner(
        codes[0], "booking.paid", f"{order_code}@{batch}", text, "payment collected"
    )


@events.subscribe("booking.online_paid")
@events.subscribe("ticket.online_paid")
async def notify_online_paid(payload: dict) -> None:
    """Tiền online về (đã theo đơn): khóa = mã đơn."""
    codes, order_code = payload.get("codes"), payload.get("order_code")
    if not codes or not order_code or payload.get("amount") is None:
        return
    text = paid_text(order_code, int(payload["amount"]), "transfer")
    await _notify_item_owner(codes[0], "booking.paid", order_code, text, "online paid")


# ------------------------------------------------------------------ nhắc giờ chơi (T-076)


def reminder_text(item: engine.DueReminder, now: dt.datetime) -> str:
    """``Sân 1 · 18h–19h hôm nay · BK-20261116-003`` (vé: tên sự kiện + mã vé)."""
    start, end = _local(item.start_at), _local(item.end_at)
    day = "hôm nay" if start.date() == _local(now).date() else f"{start:%d/%m}"
    return f"{item.label} · {_hm(start)}–{_hm(end)} {day} · {item.display_code}"


async def send_reminders(now: dt.datetime | None = None) -> int:
    """Cron 5 phút: nhắc 60' trước giờ chơi cho hội viên có tài khoản (AC8–AC11). Mỗi khối / vé
    một lần (``notify_once`` theo mã) kể cả khi cron chạy lại / chạy trùng."""
    now = now or dt.datetime.now(dt.UTC)
    sent = 0
    async with SessionLocal() as session:
        for item in await engine.due_reminders(session, now):
            customer_id = await _member_with_account(session, item.customer_ref)
            if customer_id is None:
                continue
            created = await inbox.notify_once(
                session,
                customer_id,
                "booking.reminder",
                item.code,
                reminder_text(item, now),
                link=HISTORY_LINK,
            )
            sent += created is not None
        await session.commit()
        await inbox.publish_created(session)
    if sent:
        logger.info("Sent %s play reminders", sent)
    return sent

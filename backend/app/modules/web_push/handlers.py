"""Nghe sự kiện -> đẩy job gửi push (T-076, ADR-015). Handler chỉ xếp job, không gửi trực tiếp:
gửi chậm / lỗi không làm chậm outbox hay request. ``job_id`` chống gửi trùng khi outbox giao lại.
"""

from app.core import events, queue
from app.core.permissions import Perm
from app.modules.member_inbox.api import CREATED
from app.modules.web_push import messages as m


@events.subscribe(CREATED)
async def push_member(payload: dict) -> None:
    """Thông báo hộp hội viên có kind được phép -> job gửi (câu chữ đọc lại từ hộp)."""
    if payload.get("kind") in m.PUSH_KINDS and payload.get("id") is not None:
        notification_id = int(payload["id"])
        await queue.enqueue(
            "push_member_notification", notification_id, job_id=f"push:member:{notification_id}"
        )


async def _staff(kind: str, perm: Perm, body: str, url: str, key: str) -> None:
    await queue.enqueue(
        "push_staff", kind, perm.value, body, url, f"{kind}:{key}", job_id=f"push:{kind}:{key}"
    )


@events.subscribe("booking.online_paid")
@events.subscribe("ticket.online_paid")
async def push_online_booking(payload: dict) -> None:
    """AC17: tiền đặt online về đủ -> ai xem được lịch đặt sân."""
    order_code = payload.get("order_code")
    if not order_code or payload.get("amount") is None:
        return
    await _staff(
        m.STAFF_ONLINE_BOOKING,
        Perm.BOOKING_CALENDAR_VIEW,
        m.online_booking_body(payload),
        m.calendar_url(payload.get("play_date")),
        order_code,
    )


@events.subscribe("payment.order_collected")
async def push_qr_received(payload: dict) -> None:
    """AC18: tiền QR tại quầy về -> ai thu tiền được. Tiền mặt: không gửi (người thu đã biết)."""
    order_code, batch = payload.get("order_code"), payload.get("batch_id")
    if payload.get("method") != "transfer" or not order_code or not batch:
        return
    await _staff(
        m.STAFF_QR_RECEIVED,
        Perm.BOOKING_COLLECT,
        f"{order_code} · {m.vnd(int(payload.get('amount') or 0))}",
        m.calendar_url(payload.get("play_date")),
        f"{order_code}@{batch}",
    )


@events.subscribe("payment.review_needed")
async def push_money_review(payload: dict) -> None:
    """AC19: tiền về lệch / không khớp mã / cần hoàn -> ai xem được giao dịch."""
    outcome, txn_id = payload.get("outcome"), payload.get("transaction_id")
    if outcome not in m.REVIEW_LABELS or txn_id is None:
        return
    await _staff(
        m.STAFF_MONEY_REVIEW,
        Perm.BOOKING_TRANSACTIONS_VIEW,
        f"{m.vnd(int(payload.get('amount') or 0))} · {m.REVIEW_LABELS[outcome]}",
        m.MONEY_REVIEW_URL,
        f"{txn_id}:{outcome}",
    )

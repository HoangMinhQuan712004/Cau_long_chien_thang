"""Thu cả đơn quầy bằng QR chuyển khoản (T-058).

Nội dung chuyển khoản = mã đơn bỏ gạch (``BK-20261106-001`` -> ``BK20261106001``), cùng dạng
``pay_ref`` của lượt online (chung dãy số nên không trùng). Tiền về khớp mã đơn (không phải lượt
online) -> **đúng bằng** tổng các khối Chưa thanh toán lúc tiền về thì thu cả đơn (chuyển khoản,
người thu Hệ thống, một dòng sổ ``counter_qr``); lệch số / không còn khối chưa thu -> cần hoàn,
đơn giữ nguyên. Khóa dòng booking như thu tiền mặt -> tiền về và bấm tiền mặt cùng lúc chỉ một bên
thu. Hàm ở đây **không commit**.

QR từng buổi (T-065): nội dung = **mã con** bỏ gạch (``BK-20261106-001-02`` -> ``BK2026110600102``,
bắt đầu bằng mã đơn chung). Tiền về khớp mã con, khối còn Chưa thanh toán và đúng số -> chỉ khối đó
Đã thanh toán; lệch số / khối đã xử lý -> cần hoàn, không đụng khối khác.
"""

import re
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SYSTEM_ACTOR, audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import ledger, outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import normalize_code
from app.modules.booking_engine.dto import CollectQrInfo, OnlinePaymentIn, OnlinePaymentResult
from app.modules.booking_engine.models import (
    Booking,
    BookingOrder,
    PaymentEntry,
    PaymentEntryItem,
    Ticket,
)
from app.modules.booking_engine.orders import order_blocks, order_not_found

# ``{tiền tố}{YYYYMMDD}{NNN}`` -> ``{tiền tố}-{YYYYMMDD}-{NNN}``
_PAY_REF = re.compile(r"([A-Z]+)(\d{8})(\d{3})", re.ASCII)
# Mã con (T-065): ``{tiền tố}{YYYYMMDD}{NNN}{NN}`` -> ``{tiền tố}-{YYYYMMDD}-{NNN}-{NN}``
_ITEM_REF = re.compile(r"([A-Z]+)(\d{8})(\d{3})(\d{2})", re.ASCII)
# Mã vé (T-068): ``{tiền tố}{YYYYMMDD}{NNN}V{NN}`` -> ``{tiền tố}-{YYYYMMDD}-{NNN}-V{NN}``
_TICKET_REF = re.compile(r"([A-Z]+)(\d{8})(\d{3})V(\d{2})", re.ASCII)


def pay_ref_of(order_code: str) -> str:
    return order_code.replace("-", "")


def order_code_of(pay_ref: str) -> str | None:
    found = _PAY_REF.fullmatch(pay_ref.strip().upper())
    return "-".join(found.groups()) if found else None


def ticket_code_of(pay_ref: str) -> str | None:
    found = _TICKET_REF.fullmatch(pay_ref.strip().upper())
    if not found:
        return None
    prefix, day, seq, seat = found.groups()
    return f"{prefix}-{day}-{seq}-V{seat}"


def item_code_of(pay_ref: str) -> str | None:
    found = _ITEM_REF.fullmatch(pay_ref.strip().upper())
    return "-".join(found.groups()) if found else None


def qr_status(statuses: list[str]) -> str:
    """Trạng thái QR (T-065 "Thêm 10/11"): ``paid`` chỉ khi tiền thật đã về cho mọi khối còn
    hiệu lực; đơn xong vì Không thu được / hủy hết -> ``closed`` (popup không báo nhận tiền)."""
    if "unpaid" in statuses:
        return "unpaid"
    if "uncollectible" in statuses or "paid" not in statuses:
        return "closed"
    return "paid"


async def _order(session: AsyncSession, tenant_id: int, code: str) -> BookingOrder | None:
    return await session.scalar(
        select(BookingOrder).where(BookingOrder.tenant_id == tenant_id, BookingOrder.code == code)
    )


def parse_since(raw: str | None) -> datetime | None:
    """Mốc lúc mở popup QR (T-072): ISO 8601 **có múi giờ**; sai / thiếu múi giờ -> 422 E-001."""
    if raw is None or raw == "":
        return None
    try:
        since = datetime.fromisoformat(raw)
    except ValueError:
        since = None
    if since is None or since.tzinfo is None:
        raise AppError(
            "E-001",
            "Mốc thời gian không hợp lệ (ISO 8601 có múi giờ, vd 2026-11-12T10:00:00Z).",
            422,
        )
    return since


def _qr_entry_since(since: datetime, tenant_id: int):
    """Dòng sổ tiền QR quầy (``counter_qr``) từ ``since`` – lọc tiếp theo phạm vi QR."""
    return (
        select(PaymentEntry.id)
        .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
        .where(
            PaymentEntry.tenant_id == tenant_id,
            PaymentEntry.kind == "in",
            PaymentEntry.source == "counter_qr",
            PaymentEntry.occurred_at >= since,
        )
    )


async def collect_qr_info(
    session: AsyncSession, tenant_id: int, raw_code: str, since: datetime | None = None
) -> CollectQrInfo:
    """Số tiền QR = tổng khối Chưa thanh toán (cùng tập khối với Thu cả đơn tiền mặt). Chỉ đọc.

    Hết khối chưa thu -> ``amount = 0``, ``status`` theo ``qr_status`` (``paid`` / ``closed``) –
    popup đang hỏi lại biết tiền đã về hay đơn đã xử lý ở máy khác. Không có đơn -> 404
    ``E-BOOK-3``.
    """
    order = await _order(session, tenant_id, normalize_code(raw_code))
    if order is None:
        raise order_not_found()
    blocks = await order_blocks(session, order.id)
    unpaid = [b for b in blocks if b.payment_status == "unpaid"]
    # qr_paid (T-072): hết khối chưa thu **và** có tiền QR về cho khối của đơn từ lúc mở popup.
    # Đòi hết khối chưa thu: tiền QR của một buổi lẻ không làm popup cả đơn báo "Đã nhận tiền".
    qr_paid = False
    if since is not None and not unpaid and blocks:
        qr_paid = bool(
            await session.scalar(
                select(
                    exists(
                        _qr_entry_since(since, tenant_id).where(
                            PaymentEntryItem.booking_id.in_([b.id for b in blocks])
                        )
                    )
                )
            )
        )
    return CollectQrInfo(
        order_code=order.code,
        pay_ref=pay_ref_of(order.code),
        amount=sum(b.amount for b in unpaid),
        status=qr_status([b.payment_status for b in blocks]),
        blocks=len(unpaid),
        qr_paid=qr_paid,
    )


async def _counter_booking(session: AsyncSession, tenant_id: int, code: str, *, lock: bool):
    stmt = select(Booking).where(Booking.tenant_id == tenant_id, Booking.code == code)
    return await session.scalar(stmt.with_for_update() if lock else stmt)


async def _counter_ticket(session: AsyncSession, tenant_id: int, code: str, *, lock: bool):
    stmt = select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.code == code)
    return await session.scalar(stmt.with_for_update() if lock else stmt)


async def item_collect_qr_info(
    session: AsyncSession, tenant_id: int, raw_code: str, since: datetime | None = None
) -> CollectQrInfo:
    """QR một buổi (T-065): số tiền = tiền của khối, nội dung = mã con bỏ gạch. Chỉ đọc.

    Đã thu (QR / tiền mặt) -> ``status = paid``; đã hủy / Không thu được -> ``closed``; cả hai
    ``amount = 0`` (popup đang hỏi lại thấy ngay). Vé quầy (T-068) như khối. Booking / vé online
    -> 422 ``E-PAY-1``. Không có -> 404 ``E-BOOK-3``.
    """
    code = normalize_code(raw_code)
    item: Booking | Ticket | None = await _counter_booking(session, tenant_id, code, lock=False)
    if item is None:
        item = await _counter_ticket(session, tenant_id, code, lock=False)
    if item is None:
        raise order_not_found()
    if item.source != "counter":
        what = "Vé" if isinstance(item, Ticket) else "Booking"
        raise AppError("E-PAY-1", f"{what} đặt online đã trả trước, không cần thu tiền.", 422)
    unpaid = item.payment_status == "unpaid"
    qr_paid = False
    if since is not None and item.payment_status == "paid":
        target = (
            PaymentEntryItem.ticket_id if isinstance(item, Ticket) else PaymentEntryItem.booking_id
        )
        qr_paid = bool(
            await session.scalar(
                select(exists(_qr_entry_since(since, tenant_id).where(target == item.id)))
            )
        )
    return CollectQrInfo(
        order_code=item.code,
        pay_ref=pay_ref_of(item.code),
        amount=item.amount if unpaid else 0,
        status=qr_status([item.payment_status]),
        blocks=1 if unpaid else 0,
        qr_paid=qr_paid,
    )


async def apply_counter_payment(
    session: AsyncSession, tenant_id: int, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Tiền về không khớp lượt online: mã vé (T-068), mã con (QR từng buổi), rồi mã đơn (QR cả
    đơn). Mã sự kiện không khớp đơn nào -> ``unmatched`` như cũ (không tự áp cho vé nào)."""
    if ticket_code_of(data.pay_ref):
        return await apply_ticket_payment(session, tenant_id, data)
    if item_code_of(data.pay_ref):
        return await apply_item_payment(session, tenant_id, data)
    return await apply_order_payment(session, tenant_id, data)


async def apply_ticket_payment(
    session: AsyncSession, tenant_id: int, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Tiền về cho mã vé quầy: đúng số + còn Chưa thanh toán -> chỉ vé đó Đã thanh toán."""
    code = ticket_code_of(data.pay_ref)
    t = await _counter_ticket(session, tenant_id, code, lock=True) if code else None
    if t is None or t.source != "counter":
        return OnlinePaymentResult(outcome="unmatched")
    if t.payment_status != "unpaid" or data.amount != t.amount:
        return OnlinePaymentResult(outcome="refund_needed", refund_amount=data.amount)
    return await _paid_one(session, tenant_id, t, data)


async def apply_item_payment(
    session: AsyncSession, tenant_id: int, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Tiền về cho mã con quầy: đúng số + còn Chưa thanh toán -> chỉ khối đó Đã thanh toán."""
    code = item_code_of(data.pay_ref)
    b = await _counter_booking(session, tenant_id, code, lock=True) if code else None
    if b is None or b.source != "counter":
        return OnlinePaymentResult(outcome="unmatched")
    if b.payment_status != "unpaid" or data.amount != b.amount:
        return OnlinePaymentResult(outcome="refund_needed", refund_amount=data.amount)
    return await _paid_one(session, tenant_id, b, data)


async def _paid_one(
    session: AsyncSession, tenant_id: int, item: Booking | Ticket, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Một khối / vé đã khóa dòng -> Đã thanh toán qua QR: sổ ``counter_qr`` + nhật ký Hệ thống."""
    _mark_paid_by_transfer(session, tenant_id, item, data)
    await ledger.record_in(
        session,
        tenant_id,
        [item],
        method="transfer",
        source="counter_qr",
        occurred_at=data.transaction_at,
        actor=ledger.GATEWAY_ACTOR,
        reference=data.reference,
    )
    audit(
        session,
        SYSTEM_ACTOR,
        "booking.counter_qr.paid",
        "ticket" if isinstance(item, Ticket) else "booking",
        item.code,
        audit_detail(
            item.code,
            item.customer_name,
            paid_changes("QR"),
            codes=[item.code],
            amount=item.amount,
            reference=data.reference,
        ),
    )
    await session.flush()
    return OnlinePaymentResult(outcome="applied", booking_codes=[item.code])


async def apply_order_payment(
    session: AsyncSession, tenant_id: int, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Tiền về cho mã đơn quầy (webhook, sau khi không thấy lượt online cùng ``pay_ref``)."""
    code = order_code_of(data.pay_ref)
    order = await _order(session, tenant_id, code) if code else None
    if order is None:
        return OnlinePaymentResult(outcome="unmatched")
    blocks = await order_blocks(session, order.id, lock=True)
    unpaid = [b for b in blocks if b.payment_status == "unpaid"]
    total = sum(b.amount for b in unpaid)
    # Chỉ nhận đúng số (ARCHITECT chốt): không có đơn "thu dở"; thừa / thiếu / đã thu -> hoàn đủ
    if not unpaid or data.amount != total:
        return OnlinePaymentResult(outcome="refund_needed", refund_amount=data.amount)
    actor = ledger.GATEWAY_ACTOR
    for b in unpaid:
        _mark_paid_by_transfer(session, tenant_id, b, data)
    await ledger.record_in(
        session,
        tenant_id,
        unpaid,
        method="transfer",
        source="counter_qr",
        occurred_at=data.transaction_at,
        actor=actor,
        reference=data.reference,
    )
    # Thu tiền QR (như T-008): bên thứ 3 xác nhận -> người làm là Hệ thống; một dòng cho cả đơn
    audit(
        session,
        SYSTEM_ACTOR,
        "booking.counter_qr.paid",
        "booking_order",
        order.code,
        audit_detail(
            order.code,
            unpaid[0].customer_name,
            paid_changes("QR"),
            order_code=order.code,
            codes=[b.code for b in unpaid],
            amount=total,
            reference=data.reference,
        ),
    )
    await session.flush()
    return OnlinePaymentResult(outcome="applied", booking_codes=[b.code for b in unpaid])


def _mark_paid_by_transfer(
    session: AsyncSession, tenant_id: int, b: Booking | Ticket, data: OnlinePaymentIn
) -> None:
    actor = ledger.GATEWAY_ACTOR
    b.payment_status = "paid"
    b.payment_method = "transfer"
    b.paid_at = data.transaction_at
    b.collected_by_type, b.collected_by_id, b.collected_by_label = actor.type, None, actor.label
    b.version += 1
    outbox.add_event(
        session,
        tenant_id,
        "payment.collected",
        {
            "code": b.code,
            "kind": "ticket" if isinstance(b, Ticket) else "booking",
            "method": "transfer",
            "amount": b.amount,
        },
    )

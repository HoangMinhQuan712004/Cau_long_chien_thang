"""Thu cả đơn quầy bằng QR chuyển khoản (T-058).

Nội dung chuyển khoản = mã đơn bỏ gạch (``BK-20261106-001`` -> ``BK20261106001``), cùng dạng
``pay_ref`` của lượt online (chung dãy số nên không trùng). Tiền về khớp mã đơn (không phải lượt
online) -> **đúng bằng** tổng các khối Chưa thanh toán lúc tiền về thì thu cả đơn (chuyển khoản,
người thu Hệ thống, một dòng sổ ``counter_qr``); lệch số / không còn khối chưa thu -> cần hoàn,
đơn giữ nguyên. Khóa dòng booking như thu tiền mặt -> tiền về và bấm tiền mặt cùng lúc chỉ một bên
thu. Hàm ở đây **không commit**.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SYSTEM_ACTOR, audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import ledger, outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import normalize_code
from app.modules.booking_engine.dto import CollectQrInfo, OnlinePaymentIn, OnlinePaymentResult
from app.modules.booking_engine.models import Booking, BookingOrder
from app.modules.booking_engine.orders import order_blocks, order_not_found

# ``{tiền tố}{YYYYMMDD}{NNN}`` -> ``{tiền tố}-{YYYYMMDD}-{NNN}``
_PAY_REF = re.compile(r"([A-Z]+)(\d{8})(\d{3})", re.ASCII)


def pay_ref_of(order_code: str) -> str:
    return order_code.replace("-", "")


def order_code_of(pay_ref: str) -> str | None:
    found = _PAY_REF.fullmatch(pay_ref.strip().upper())
    return "-".join(found.groups()) if found else None


def nothing_to_collect() -> AppError:
    """Cùng mã + thông điệp với "Thu cả đơn" tiền mặt (T-019)."""
    return AppError("E-BOOK-4", "Đơn không còn khối nào chưa thanh toán.", 409)


async def _order(session: AsyncSession, tenant_id: int, code: str) -> BookingOrder | None:
    return await session.scalar(
        select(BookingOrder).where(BookingOrder.tenant_id == tenant_id, BookingOrder.code == code)
    )


async def collect_qr_info(session: AsyncSession, tenant_id: int, raw_code: str) -> CollectQrInfo:
    """Số tiền QR = tổng khối Chưa thanh toán (cùng tập khối với Thu cả đơn tiền mặt). Chỉ đọc.

    Đã thu hết (còn khối Đã thanh toán) -> ``status = paid``, ``amount = 0`` – popup đang hỏi lại
    biết tiền đã về. Không còn khối chưa thu cũng không có khối đã thu (đã hủy / Không thu được)
    -> 409 ``E-BOOK-4``. Không có đơn -> 404 ``E-BOOK-3``.
    """
    order = await _order(session, tenant_id, normalize_code(raw_code))
    if order is None:
        raise order_not_found()
    blocks = await order_blocks(session, order.id)
    unpaid = [b for b in blocks if b.payment_status == "unpaid"]
    if not unpaid and not any(b.payment_status == "paid" for b in blocks):
        raise nothing_to_collect()
    return CollectQrInfo(
        order_code=order.code,
        pay_ref=pay_ref_of(order.code),
        amount=sum(b.amount for b in unpaid),
        status="unpaid" if unpaid else "paid",
        blocks=len(unpaid),
    )


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
    session: AsyncSession, tenant_id: int, b: Booking, data: OnlinePaymentIn
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
        {"code": b.code, "kind": "booking", "method": "transfer", "amount": b.amount},
    )

"""Hủy booking / vé (T-051, T-052, ADR-013): khoản đã thu hủy được mọi lúc; chưa thu chỉ trước
giờ bắt đầu (sau đó dùng Không thu được). Hủy cả đơn vẫn chỉ gồm buổi chưa bắt đầu, chưa có trận.

Khoản đã thu ghi ``refund_amount`` = toàn bộ ``amount`` theo xác nhận của Admin (hệ thống không tự
hoàn); ``paid_at`` / ``payment_method`` giữ nguyên. Booking nhả chỗ bằng
``allocation.active = false``
cùng transaction – exclusion constraint không đổi. Vé không có allocation riêng: chỗ trống lại nhờ
``session_counts`` loại vé hủy.

Engine không biết phòng chơi (ADR-003): khi hủy cả đơn, lớp gọi (``front_desk``) truyền ``played``
= mã các khối đã có trận trong phòng. Hàm ở đây **không commit**.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_change, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import ledger, outbox
from app.modules.booking_engine.booking_service import normalize_code, session_resources
from app.modules.booking_engine.common import STALE_ITEM, Ctx, audit_actor, context
from app.modules.booking_engine.dto import (
    Actor,
    CancelIn,
    CancelPreview,
    CancelPreviewItem,
    CancelSkipped,
    CancelSkipReason,
    ItemOut,
    OrderCancelIn,
    OrderCancelOut,
)
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    EventSession,
    Resource,
    Ticket,
)
from app.modules.booking_engine.orders import order_blocks, order_codes, order_not_found
from app.modules.booking_engine.payment_service import (
    clean_reason,
    entity_of,
    lock_item,
    not_cancellable,
    view_of,
)

STATUS_LABELS = {"unpaid": "Chưa thanh toán", "paid": "Đã thanh toán"}


def _started_unpaid() -> AppError:
    return AppError("E-PAY-5", "Buổi đã bắt đầu và chưa thu tiền, hãy dùng Không thu được.", 422)


def _refund_unconfirmed() -> AppError:
    return AppError("E-PAY-7", "Vui lòng xác nhận việc hoàn tiền cho khách.", 422)


def _skip_reason(
    item: Booking | Ticket, start_at: datetime, now: datetime, played: set[str]
) -> CancelSkipReason | None:
    """Vì sao khối không vào "Hủy cả đơn" (hủy từng mục dùng quy tắc riêng ở ``cancel_item``)."""
    if item.payment_status == "cancelled":
        return "cancelled"
    if item.payment_status == "uncollectible":
        return "uncollectible"
    if now >= start_at:
        return "started"
    if item.code in played:
        return "played"
    return None


@dataclass(frozen=True)
class _Slot:
    play_date: date
    start_at: datetime
    end_at: datetime
    resource_name: str
    order_code: str | None


async def _slot(session: AsyncSession, tenant_id: int, item: Booking | Ticket) -> _Slot:
    if isinstance(item, Booking):
        resource = await session.get(Resource, item.resource_id)
        orders = await order_codes(session, {item.order_id})
        return _Slot(
            item.play_date, item.start_at, item.end_at, resource.name, orders.get(item.order_id)
        )
    ev = await session.get(EventSession, item.session_id)
    courts = (await session_resources(session, tenant_id, [ev.id])).get(ev.id, [])
    names = ", ".join(r.name for r in courts)
    return _Slot(ev.play_date, ev.start_at, ev.end_at, names, None)


async def _apply(
    session: AsyncSession, ctx: Ctx, actor: Actor, item: Booking | Ticket, reason: str
) -> None:
    """Item đã khóa dòng và đã kiểm tra: ghi hủy, nhả chỗ, nhật ký, sự kiện."""
    was_paid = item.payment_status == "paid"
    before = STATUS_LABELS[item.payment_status]
    item.payment_status = "cancelled"
    item.cancel_reason = reason
    item.cancelled_at = ctx.now
    item.cancelled_by_type, item.cancelled_by_id = actor.type, actor.id
    item.cancelled_by_label = actor.label
    item.refund_amount = item.amount if was_paid else 0
    item.version += 1
    if isinstance(item, Booking):
        await session.execute(
            update(Allocation).where(Allocation.booking_id == item.id).values(active=False)
        )
    changes = [
        audit_change("Thanh toán", before, "Đã hủy"),
        audit_change("Lý do", None, reason),
    ]
    if was_paid:
        changes.append(audit_change("Số hoàn", None, f"{item.refund_amount} đ"))
    audit(
        session,
        audit_actor(actor),
        "payment.cancelled",
        entity_of(item),
        item.code,
        audit_detail(
            item.code,
            item.customer_name,
            changes,
            amount=item.amount,
            refund_amount=item.refund_amount,
        ),
    )
    slot = await _slot(session, ctx.tenant.id, item)
    # Không mang customer_ref / SĐT vì payload được ghi log; handler lấy qua ``item_customer_ref``
    outbox.add_event(
        session,
        ctx.tenant.id,
        "booking.cancelled",
        {
            "code": item.code,
            "order_code": slot.order_code,
            "kind": entity_of(item),
            "play_date": slot.play_date.isoformat(),
            "start_at": slot.start_at.isoformat(),
            "end_at": slot.end_at.isoformat(),
            "resource_name": slot.resource_name,
            "was_paid": was_paid,
            "refund_amount": item.refund_amount,
            # Buổi đã qua: phòng chơi không đóng, không báo thành viên (T-052)
            "past": slot.end_at <= ctx.now,
        },
    )


async def cancel_item(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    code: str,
    data: CancelIn,
) -> ItemOut:
    """Hủy một booking hoặc vé. Khóa dòng nên hủy và thu tiền cùng lúc chỉ một bên thắng."""
    reason = clean_reason(data.reason)
    ctx = await context(session, tenant_id)
    item, start_at = await lock_item(session, tenant_id, code)
    if item.payment_status in ("cancelled", "uncollectible"):
        raise not_cancellable()
    if item.version != data.version:
        raise AppError("E-012", STALE_ITEM, 409)
    if item.payment_status == "unpaid" and ctx.now >= start_at:
        raise _started_unpaid()
    if item.payment_status == "paid" and not data.refund_confirmed:
        raise _refund_unconfirmed()
    await _apply(session, ctx, actor, item, reason)
    await ledger.record_refunds(session, tenant_id, [item], occurred_at=ctx.now, actor=actor)
    return await view_of(session, ctx, item)


async def _order(session: AsyncSession, tenant_id: int, raw_code: str) -> BookingOrder:
    order = await session.scalar(
        select(BookingOrder).where(
            BookingOrder.tenant_id == tenant_id, BookingOrder.code == normalize_code(raw_code)
        )
    )
    if order is None:
        raise order_not_found()
    return order


async def order_block_codes(session: AsyncSession, tenant_id: int, raw_code: str) -> list[str]:
    """Mã con các khối của đơn – để lớp gọi tra trận trong phòng. Không có đơn -> E-BOOK-3."""
    order = await _order(session, tenant_id, raw_code)
    return [b.code for b in await order_blocks(session, order.id)]


async def preview_order(
    session: AsyncSession, tenant_id: int, raw_code: str, played: set[str]
) -> CancelPreview:
    """Khối sẽ hủy / bỏ qua nếu hủy cả đơn lúc này, kèm tổng tiền. Chỉ đọc."""
    ctx = await context(session, tenant_id)
    order = await _order(session, tenant_id, raw_code)
    blocks = await order_blocks(session, order.id)
    names = {
        r.id: r.name
        for r in await session.scalars(
            select(Resource).where(Resource.id.in_({b.resource_id for b in blocks}))
        )
    }
    cancellable, skipped = [], []
    for b in blocks:
        reason = _skip_reason(b, b.start_at, ctx.now, played)
        if reason is not None:
            skipped.append(CancelSkipped(code=b.code, reason=reason))
            continue
        cancellable.append(
            CancelPreviewItem(
                code=b.code,
                play_date=b.play_date,
                start_at=b.start_at,
                resource_name=names[b.resource_id],
                amount=b.amount,
                payment_status=b.payment_status,
            )
        )
    return CancelPreview(
        cancellable=cancellable,
        skipped=skipped,
        refund_total=sum(i.amount for i in cancellable if i.payment_status == "paid"),
        unpaid_total=sum(i.amount for i in cancellable if i.payment_status == "unpaid"),
    )


async def cancel_order(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    raw_code: str,
    data: OrderCancelIn,
    played: set[str],
) -> OrderCancelOut:
    """Hủy các khối ``codes`` (lấy từ xem trước) của đơn; khóa rồi kiểm tra lại từng khối.

    Khối đã bắt đầu sau lúc xem trước vào ``skipped``. Có khối đã thu mà chưa xác nhận hoàn ->
    E-PAY-7 cho cả lệnh, không hủy một phần. Mỗi khối một dòng nhật ký.
    """
    reason = clean_reason(data.reason)
    codes = {normalize_code(c) for c in data.codes}
    if not codes:
        raise AppError("E-001", "Vui lòng chọn buổi cần hủy.", 422)
    ctx = await context(session, tenant_id)
    order = await _order(session, tenant_id, raw_code)
    blocks = await order_blocks(session, order.id, lock=True)
    if codes - {b.code for b in blocks}:
        raise AppError("E-001", "Danh sách buổi có mã không thuộc đơn này.", 422)
    chosen, skipped = [], []
    for b in blocks:
        if b.code not in codes:
            continue
        why = _skip_reason(b, b.start_at, ctx.now, played)
        if why is not None:
            skipped.append(CancelSkipped(code=b.code, reason=why))
        else:
            chosen.append(b)
    if any(b.payment_status == "paid" for b in chosen) and not data.refund_confirmed:
        raise _refund_unconfirmed()
    refund_total = sum(b.amount for b in chosen if b.payment_status == "paid")
    for b in chosen:
        await _apply(session, ctx, actor, b, reason)
    # Hoàn trừ vào ngày hủy (ADR-014): một dòng cho cả lần hủy
    await ledger.record_refunds(session, tenant_id, chosen, occurred_at=ctx.now, actor=actor)
    await session.flush()
    return OrderCancelOut(
        cancelled=[b.code for b in chosen], skipped=skipped, refund_total=refund_total
    )


async def item_customer_ref(session: AsyncSession, tenant_id: int, code: str) -> str | None:
    """``customer_ref`` của booking / vé theo mã – cho handler ``booking.cancelled``. Chỉ đọc."""
    ref = await session.scalar(
        select(Booking.customer_ref).where(Booking.tenant_id == tenant_id, Booking.code == code)
    )
    if ref is not None:
        return ref
    return await session.scalar(
        select(Ticket.customer_ref).where(Ticket.tenant_id == tenant_id, Ticket.code == code)
    )

"""Thu tiền mặt, Không thu được (T-006 §3: BR-013, BR-014, BR-015; FR-007…009).

Trạng thái một chiều ``unpaid -> paid | uncollectible`` (hủy: ``cancel_service``). Khóa dòng
booking / vé (``FOR UPDATE``):
máy thứ hai đọc bản mới nhất sau khi máy đầu commit -> ``E-012``, không ghi đè.
Hàm ở đây **không commit**.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_change, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import ledger, outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import booking_item, normalize_code, ticket_item
from app.modules.booking_engine.common import STALE_ITEM, Ctx, audit_actor, context, not_found
from app.modules.booking_engine.dto import (
    Actor,
    CollectIn,
    ItemOut,
    OrderCollectIn,
    UncollectibleIn,
)
from app.modules.booking_engine.models import Booking, EventSession, Ticket

REASON_MAX = 200
METHOD_LABELS = {"cash": "Tiền mặt", "transfer": "Chuyển khoản"}


async def lock_item(
    session: AsyncSession, tenant_id: int, raw_code: str
) -> tuple[Booking | Ticket, datetime]:
    """Khóa booking hoặc vé theo mã; trả kèm giờ bắt đầu chơi."""
    code = normalize_code(raw_code)
    b = await session.scalar(
        select(Booking)
        .where(Booking.tenant_id == tenant_id, Booking.code == code)
        .with_for_update()
    )
    if b is not None:
        return b, b.start_at
    t = await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.code == code).with_for_update()
    )
    if t is None:
        raise not_found(f"booking hoặc vé {code}")
    ev = await session.get(EventSession, t.session_id)
    return t, ev.start_at


def not_cancellable() -> AppError:
    return AppError("E-PAY-6", "Đã ở trạng thái Đã hủy hoặc Không thu được, không thể hủy.", 409)


def clean_reason(raw: str) -> str:
    reason = raw.strip()
    if not reason:
        raise AppError("E-001", "Vui lòng nhập Lý do.", 422)
    if len(reason) > REASON_MAX:
        raise AppError("E-001", f"Lý do tối đa {REASON_MAX} ký tự.", 422)
    return reason


def _check_fresh(item: Booking | Ticket, version: int) -> None:
    if item.payment_status == "cancelled":
        raise not_cancellable()
    if item.payment_status != "unpaid" or item.version != version:
        raise AppError("E-012", STALE_ITEM, 409)


async def view_of(session: AsyncSession, ctx: Ctx, item: Booking | Ticket) -> ItemOut:
    await session.flush()
    await session.refresh(item)
    if isinstance(item, Booking):
        return await booking_item(session, ctx, item)
    return await ticket_item(session, ctx, item)


def entity_of(item: Booking | Ticket) -> str:
    return "booking" if isinstance(item, Booking) else "ticket"


def cash_only(data: CollectIn | OrderCollectIn) -> None:
    if data.method != "cash":
        raise AppError(
            "E-PAY-0",
            "Chưa hỗ trợ thu chuyển khoản tại quầy. Vui lòng thu tiền mặt.",
            422,
        )


def mark_paid(
    session: AsyncSession, ctx: Ctx, tenant_id: int, actor: Actor, item: Booking | Ticket
) -> None:
    """Ghi Đã thanh toán (tiền mặt) cho một khối / vé đã khóa dòng + nhật ký + sự kiện."""
    item.payment_status = "paid"
    item.payment_method = "cash"
    item.paid_at = ctx.now
    item.collected_by_type, item.collected_by_id = actor.type, actor.id
    item.collected_by_label = actor.label
    item.version += 1
    audit(
        session,
        audit_actor(actor),
        "payment.collect",
        entity_of(item),
        item.code,
        audit_detail(
            item.code,
            item.customer_name,
            paid_changes(METHOD_LABELS["cash"]),
            method="cash",
            amount=item.amount,
        ),
    )
    outbox.add_event(
        session,
        tenant_id,
        "payment.collected",
        {"code": item.code, "kind": entity_of(item), "method": "cash", "amount": item.amount},
    )


async def collect(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: CollectIn
) -> ItemOut:
    """Thu tiền mặt: số tiền = ``amount`` (không sửa, thu đủ 1 lần); người thu = người thao tác."""
    cash_only(data)
    ctx = await context(session, tenant_id)
    item, _ = await lock_item(session, tenant_id, code)
    _check_fresh(item, data.version)
    mark_paid(session, ctx, tenant_id, actor, item)
    await ledger.record_in(
        session, tenant_id, [item], method="cash", occurred_at=ctx.now, actor=actor
    )
    return await view_of(session, ctx, item)


async def mark_uncollectible(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: UncollectibleIn
) -> ItemOut:
    """Không thu được: chỉ booking / vé tại quầy, Chưa thanh toán, đã tới giờ chơi (BR-015).

    Khung **không** trống lại (allocation giữ active); vé vẫn chiếm chỗ của sự kiện.
    """
    reason = clean_reason(data.reason)
    ctx = await context(session, tenant_id)
    item, start_at = await lock_item(session, tenant_id, code)
    _check_fresh(item, data.version)
    if item.source != "counter":
        raise AppError(
            "E-PAY-1", "Booking đặt online đã trả trước, không đánh dấu Không thu được.", 422
        )
    if ctx.now < start_at:
        raise AppError("E-PAY-1", "Chưa tới giờ chơi, chưa thể đánh dấu Không thu được.", 422)
    apply_uncollectible(session, ctx, tenant_id, actor, item, reason)
    return await view_of(session, ctx, item)


def apply_uncollectible(
    session: AsyncSession,
    ctx: Ctx,
    tenant_id: int,
    actor: Actor,
    item: Booking | Ticket,
    reason: str,
) -> None:
    """Chưa thanh toán -> Không thu được cho một khối / vé đã khóa dòng (người gọi đã kiểm điều
    kiện). Lý do rỗng (Không thu được cả đơn, T-064) -> không ghi ô "Lý do" vào nhật ký."""
    item.payment_status = "uncollectible"
    item.uncollectible_reason = reason
    item.marked_by_type, item.marked_by_id, item.marked_by_label = (
        actor.type,
        actor.id,
        actor.label,
    )
    item.marked_at = ctx.now
    item.version += 1
    audit(
        session,
        audit_actor(actor),
        "payment.uncollectible",
        entity_of(item),
        item.code,
        audit_detail(
            item.code,
            item.customer_name,
            [
                audit_change("Thanh toán", "Chưa thanh toán", "Không thu được"),
                *([audit_change("Lý do", None, reason)] if reason else []),
            ],
            amount=item.amount,
        ),
    )
    outbox.add_event(
        session,
        tenant_id,
        "payment.uncollectible",
        {"code": item.code, "kind": entity_of(item), "amount": item.amount},
    )

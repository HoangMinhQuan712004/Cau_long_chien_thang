"""Thu tiền mặt, Không thu được (T-006 §3: BR-013, BR-014, BR-015; FR-007…009).

Trạng thái một chiều ``unpaid -> paid | uncollectible``. Khóa dòng booking / vé (``FOR UPDATE``):
máy thứ hai đọc bản mới nhất sau khi máy đầu commit -> ``E-012``, không ghi đè.
Hàm ở đây **không commit**.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import AppError
from app.modules.booking_engine import outbox
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


async def _lock(
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


def _check_fresh(item: Booking | Ticket, version: int) -> None:
    if item.payment_status != "unpaid" or item.version != version:
        raise AppError("E-012", STALE_ITEM, 409)


async def _view(session: AsyncSession, ctx: Ctx, item: Booking | Ticket) -> ItemOut:
    await session.flush()
    await session.refresh(item)
    if isinstance(item, Booking):
        return await booking_item(session, ctx, item)
    return await ticket_item(session, ctx, item)


def _entity(item: Booking | Ticket) -> str:
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
        _entity(item),
        item.code,
        {"method": "cash", "method_label": METHOD_LABELS["cash"], "amount": item.amount},
    )
    outbox.add_event(
        session,
        tenant_id,
        "payment.collected",
        {"code": item.code, "kind": _entity(item), "method": "cash", "amount": item.amount},
    )


async def collect(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: CollectIn
) -> ItemOut:
    """Thu tiền mặt: số tiền = ``amount`` (không sửa, thu đủ 1 lần); người thu = người thao tác."""
    cash_only(data)
    ctx = await context(session, tenant_id)
    item, _ = await _lock(session, tenant_id, code)
    _check_fresh(item, data.version)
    mark_paid(session, ctx, tenant_id, actor, item)
    return await _view(session, ctx, item)


async def mark_uncollectible(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: UncollectibleIn
) -> ItemOut:
    """Không thu được: chỉ booking / vé tại quầy, Chưa thanh toán, đã tới giờ chơi (BR-015).

    Khung **không** trống lại (allocation giữ active); vé vẫn chiếm chỗ của sự kiện.
    """
    reason = data.reason.strip()
    if not reason:
        raise AppError("E-001", "Vui lòng nhập Lý do.", 422)
    if len(reason) > REASON_MAX:
        raise AppError("E-001", f"Lý do tối đa {REASON_MAX} ký tự.", 422)
    ctx = await context(session, tenant_id)
    item, start_at = await _lock(session, tenant_id, code)
    _check_fresh(item, data.version)
    if item.source != "counter":
        raise AppError(
            "E-PAY-1", "Booking đặt online đã trả trước, không đánh dấu Không thu được.", 422
        )
    if ctx.now < start_at:
        raise AppError("E-PAY-1", "Chưa tới giờ chơi, chưa thể đánh dấu Không thu được.", 422)
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
        _entity(item),
        item.code,
        {"reason": reason, "amount": item.amount},
    )
    outbox.add_event(
        session,
        tenant_id,
        "payment.uncollectible",
        {"code": item.code, "kind": _entity(item), "amount": item.amount},
    )
    return await _view(session, ctx, item)

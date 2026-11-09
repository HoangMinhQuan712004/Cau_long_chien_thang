"""Sổ tiền vào (ADR-014, T-057): ghi một dòng cho mỗi lần nhận / hoàn tiền.

Gọi từ đường thu quầy (``payment_service``, ``orders``), tiền về online (``online_service``,
``ticket_online``, thu QR của đơn quầy – T-058) và hủy có hoàn (``cancel_service``), **cùng
transaction** với lần thu / hoàn. Hàm ở đây **không commit**. Không thu được, hủy khoản chưa thu:
không ghi.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.dto import Actor
from app.modules.booking_engine.models import (
    Booking,
    BookingOrder,
    EventSession,
    PaymentEntry,
    PaymentEntryItem,
    Ticket,
)

# Nguồn theo phương thức: chuyển khoản tại quầy chỉ có qua QR (T-058)
SOURCE_OF_METHOD = {"cash": "counter", "transfer": "counter_qr", "online_transfer": "online"}
GATEWAY_ACTOR = Actor(type="system", id=None, label="Hệ thống")


async def _order_code(session: AsyncSession, item: Booking | Ticket) -> str | None:
    if isinstance(item, Booking):
        return await session.scalar(
            select(BookingOrder.code).where(BookingOrder.id == item.order_id)
        )
    return await session.scalar(select(EventSession.code).where(EventSession.id == item.session_id))


async def record(
    session: AsyncSession,
    tenant_id: int,
    kind: str,
    parts: Sequence[tuple[Booking | Ticket, int]],
    *,
    method: str,
    occurred_at: datetime,
    actor: Actor,
    reference: str | None = None,
    source: str | None = None,
) -> PaymentEntry | None:
    """Một dòng sổ cho ``parts`` = [(booking / vé, số tiền)] (mục 0 đ bỏ qua; tổng 0 -> không ghi).

    Các mục cùng một đơn / sự kiện: khách và mã đơn lấy từ mục đầu.
    """
    parts = [(item, amount) for item, amount in parts if amount > 0]
    if not parts:
        return None
    first = parts[0][0]
    entry = PaymentEntry(
        tenant_id=tenant_id,
        kind=kind,
        method=method,
        source=source or SOURCE_OF_METHOD[method],
        amount=sum(amount for _, amount in parts),
        occurred_at=occurred_at,
        order_code=await _order_code(session, first),
        customer_name=first.customer_name,
        customer_phone=first.customer_phone,
        member_code=first.member_code,
        actor_type=actor.type,
        actor_id=actor.id,
        actor_label=actor.label,
        reference=reference,
    )
    session.add(entry)
    await session.flush()  # id của dòng; booking / vé mới tạo cũng có id
    for item, amount in parts:
        session.add(
            PaymentEntryItem(
                tenant_id=tenant_id,
                entry_id=entry.id,
                booking_id=item.id if isinstance(item, Booking) else None,
                ticket_id=item.id if isinstance(item, Ticket) else None,
                amount=amount,
            )
        )
    await session.flush()
    return entry


async def record_in(
    session: AsyncSession,
    tenant_id: int,
    items: Sequence[Booking | Ticket],
    *,
    method: str,
    occurred_at: datetime,
    actor: Actor,
    reference: str | None = None,
    source: str | None = None,
) -> PaymentEntry | None:
    """Một lần nhận tiền cho ``items`` (mỗi mục = ``amount`` của nó)."""
    return await record(
        session,
        tenant_id,
        "in",
        [(i, i.amount) for i in items],
        method=method,
        occurred_at=occurred_at,
        actor=actor,
        reference=reference,
        source=source,
    )


async def record_refunds(
    session: AsyncSession,
    tenant_id: int,
    items: Sequence[Booking | Ticket],
    *,
    occurred_at: datetime,
    actor: Actor,
) -> None:
    """Một lần hủy có hoàn: một dòng ``refund`` cho mỗi phương thức gốc (thường chỉ một)."""
    by_method: dict[str, list[Booking | Ticket]] = {}
    for item in items:
        if item.refund_amount > 0 and item.payment_method:
            by_method.setdefault(item.payment_method, []).append(item)
    for method, group in by_method.items():
        await record(
            session,
            tenant_id,
            "refund",
            [(i, i.refund_amount) for i in group],
            method=method,
            occurred_at=occurred_at,
            actor=actor,
        )

"""Outbox (T-005 C4): sự kiện ghi cùng transaction nghiệp vụ, worker phát sau commit."""

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import events
from app.modules.booking_engine.models import Booking, OutboxEvent, Ticket

logger = logging.getLogger(__name__)


def add_event(
    session: AsyncSession, tenant_id: int, event_type: str, payload: dict[str, Any]
) -> None:
    session.add(OutboxEvent(tenant_id=tenant_id, event_type=event_type, payload=payload))


ORDER_COLLECTED = "payment.order_collected"


def order_collected(
    session: AsyncSession, tenant_id: int, items: list[Booking | Ticket], method: str
) -> None:
    """T-076 Q4: **một** ``payment.order_collected`` cho mỗi đơn trong một lần thu (một
    transaction: tiền mặt, QR quầy), cùng ``batch_id``. Vé: "đơn" là chính vé đó.

    Payload: ``order_code, batch_id, method (cash | transfer), amount, codes[], kind (booking |
    ticket), play_date`` – không tên / SĐT khách (payload được ghi log).
    """
    batch_id = uuid.uuid4().hex
    groups: dict[str, list[Booking | Ticket]] = {}
    for item in items:
        order_code = item.code.rsplit("-", 1)[0] if isinstance(item, Booking) else item.code
        groups.setdefault(order_code, []).append(item)
    for order_code, group in groups.items():
        add_event(
            session,
            tenant_id,
            ORDER_COLLECTED,
            {
                "order_code": order_code,
                "batch_id": batch_id,
                "method": method,
                "amount": sum(i.amount for i in group),
                "codes": [i.code for i in group],
                "kind": "booking" if isinstance(group[0], Booking) else "ticket",
                # Mã theo ngày chơi: BK-YYYYMMDD-…
                "play_date": f"{order_code[3:7]}-{order_code[7:9]}-{order_code[9:11]}",
            },
        )


async def publish_pending(
    session_factory: async_sessionmaker[AsyncSession], batch: int = 100
) -> int:
    """Phát các sự kiện chưa phát.

    ``FOR UPDATE SKIP LOCKED``: nhiều worker chạy song song an toàn.
    """
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for row in rows:
            # events.publish tự nuốt lỗi của handler – một handler lỗi không chặn hàng đợi.
            # ``event_id`` (T-076 Q3): giao lại cùng một event -> cùng id (khóa chống trùng)
            await events.publish(
                row.event_type, {"tenant_id": row.tenant_id, **row.payload, "event_id": row.id}
            )
            row.published_at = func.now()
        await session.commit()
    if rows:
        logger.info("Published %s outbox events", len(rows))
    return len(rows)

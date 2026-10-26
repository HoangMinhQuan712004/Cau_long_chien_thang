"""Outbox (T-005 C4): sự kiện ghi cùng transaction nghiệp vụ, worker phát sau commit."""

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import events
from app.modules.booking_engine.models import OutboxEvent

logger = logging.getLogger(__name__)


def add_event(
    session: AsyncSession, tenant_id: int, event_type: str, payload: dict[str, Any]
) -> None:
    session.add(OutboxEvent(tenant_id=tenant_id, event_type=event_type, payload=payload))


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
            # events.publish tự nuốt lỗi của handler – một handler lỗi không chặn hàng đợi
            await events.publish(row.event_type, {"tenant_id": row.tenant_id, **row.payload})
            row.published_at = func.now()
        await session.commit()
    if rows:
        logger.info("Published %s outbox events", len(rows))
    return len(rows)

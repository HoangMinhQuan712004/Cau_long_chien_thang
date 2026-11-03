"""Thông báo trong web (T-017 AC22, AC23).

``notify`` không commit; các thông báo mới giữ trong ``session.info`` để lớp gọi phát sự kiện
``member.notification_created`` **sau commit** (``publish_created``) – chỗ nối Zalo ZNS sau này.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.errors import AppError
from app.modules.member_inbox.models import MemberNotification
from app.modules.member_inbox.schemas import NotificationList, NotificationOut

CREATED = "member.notification_created"
SHOWN = timedelta(days=30)  # danh sách hiện 30 ngày
RETENTION = timedelta(days=90)  # dọn sau 90 ngày
PAGE = 50
_PENDING = "member_inbox.created"


def notify(
    session: AsyncSession,
    customer_id: int,
    kind: str,
    text: str,
    link: str | None = None,
    **payload: Any,
) -> MemberNotification:
    """Thêm thông báo (không commit). ``payload`` không được chứa SĐT."""
    row = MemberNotification(
        customer_id=customer_id, kind=kind, payload={"text": text, **payload}, link=link
    )
    session.add(row)
    session.info.setdefault(_PENDING, []).append(row)
    return row


async def publish_created(session: AsyncSession) -> None:
    """Gọi **sau commit**: phát ``member.notification_created`` cho các thông báo vừa tạo."""
    rows: list[MemberNotification] = session.info.pop(_PENDING, [])
    for row in rows:
        if row.id is None:  # không được ghi (rollback)
            continue
        await events.publish(
            CREATED, {"id": row.id, "customer_id": row.customer_id, "kind": row.kind}
        )


def discard_pending(session: AsyncSession) -> None:
    session.info.pop(_PENDING, None)


def _out(n: MemberNotification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        text=str(n.payload.get("text", "")),
        link=n.link,
        created_at=n.created_at,
        read=n.read_at is not None,
    )


def _shown(customer_id: int) -> list:
    return [
        MemberNotification.customer_id == customer_id,
        MemberNotification.created_at >= datetime.now(UTC) - SHOWN,
    ]


async def list_for(
    session: AsyncSession, customer_id: int, unread: bool | None
) -> NotificationList:
    q = select(MemberNotification).where(*_shown(customer_id))
    if unread is True:
        q = q.where(MemberNotification.read_at.is_(None))
    elif unread is False:
        q = q.where(MemberNotification.read_at.is_not(None))
    rows = await session.scalars(
        q.order_by(MemberNotification.created_at.desc(), MemberNotification.id.desc()).limit(PAGE)
    )
    return NotificationList(
        items=[_out(n) for n in rows], unread_count=await unread_count(session, customer_id)
    )


async def unread_count(session: AsyncSession, customer_id: int) -> int:
    count = await session.scalar(
        select(func.count()).where(*_shown(customer_id), MemberNotification.read_at.is_(None))
    )
    return count or 0


async def mark_read(session: AsyncSession, customer_id: int, notification_id: int) -> None:
    """Không commit. Thông báo của người khác -> 404 (SEC6, không lộ là có tồn tại)."""
    row = await session.scalar(
        select(MemberNotification).where(
            MemberNotification.id == notification_id,
            MemberNotification.customer_id == customer_id,
        )
    )
    if row is None:
        raise AppError("E-NOT-FOUND", "Không tìm thấy thông báo.", 404)
    if row.read_at is None:
        row.read_at = datetime.now(UTC)


async def mark_all_read(session: AsyncSession, customer_id: int) -> None:
    await session.execute(
        update(MemberNotification)
        .where(MemberNotification.customer_id == customer_id, MemberNotification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )


async def purge_old(session: AsyncSession) -> int:
    """Job hằng ngày: xóa thông báo quá 90 ngày (commit)."""
    result = await session.execute(
        delete(MemberNotification).where(
            MemberNotification.created_at < datetime.now(UTC) - RETENTION
        )
    )
    await session.commit()
    return result.rowcount or 0


async def purge_for(session: AsyncSession, customer_ids: list[int]) -> int:
    """Xóa mọi thông báo của các hồ sơ này (dữ liệu mẫu T-034). Không commit."""
    if not customer_ids:
        return 0
    result = await session.execute(
        delete(MemberNotification).where(MemberNotification.customer_id.in_(customer_ids))
    )
    return result.rowcount or 0

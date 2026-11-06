"""Tạo / đóng phòng (T-017 AC1–AC3, AC18).

- Sự kiện ``booking.created`` (outbox, worker) -> tạo phòng cho khối booking đó.
- Job mỗi phút: tạo phòng còn thiếu cho booking hôm nay + ngày mai (backfill lúc deploy và lưới an
  toàn khi lỡ sự kiện – idempotent theo ``booking_code``), rồi đóng phòng quá giờ + 10 phút.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine import api as engine
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.play_rooms.common import CLOSE_GRACE, hm
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember, PlayRoomRequest

logger = logging.getLogger(__name__)


async def ensure_rooms(session: AsyncSession, sources: list[engine.RoomSource]) -> int:
    """Tạo phòng (Host = khách của booking, vào Hàng chờ) – đã có thì bỏ qua. Không commit.

    Booking của khách chưa có hồ sơ (``phone:…``) không tạo phòng. Điều kiện "Host là hội viên có
    liên kết" xét lúc đọc / thao tác, không xét ở đây (chốt 31/10).
    """
    created = 0
    for src in sources:
        host = await members.customer_id_of_ref(session, src.customer_ref)
        if host is None:
            continue
        room_id = await session.scalar(
            insert(PlayRoom)
            .values(
                booking_code=src.code,
                resource_code=src.resource_code,
                resource_name=src.resource_name,
                resource_type_name=src.resource_type_name,
                start_at=src.start_at,
                end_at=src.end_at,
                host_customer_id=host,
                min_tier=src.min_tier,
                max_tier=src.max_tier,
            )
            .on_conflict_do_nothing(index_elements=[PlayRoom.booking_code])
            .returning(PlayRoom.id)
        )
        if room_id is None:
            continue
        session.add(PlayRoomMember(room_id=room_id, customer_id=host))
        created += 1
    await session.flush()
    return created


async def ensure_for_codes(session: AsyncSession, codes: list[str]) -> int:
    return await ensure_rooms(session, await engine.room_sources(session, codes))


async def backfill(session: AsyncSession, now: datetime) -> int:
    """Booking hôm nay + ngày mai (giờ VN) chưa kết thúc mà chưa có phòng. Không commit."""
    today = now.astimezone(settings.tz).date()
    sources = await engine.room_sources_ending_after(
        session, now, [today, today + timedelta(days=1)]
    )
    if not sources:
        return 0
    have = set(
        await session.scalars(
            select(PlayRoom.booking_code).where(
                PlayRoom.booking_code.in_([s.code for s in sources])
            )
        )
    )
    return await ensure_rooms(session, [s for s in sources if s.code not in have])


async def close_expired(session: AsyncSession, now: datetime) -> int:
    """Đóng phòng quá giờ kết thúc + 10 phút. Không commit.

    Yêu cầu / lời mời đang chờ -> hết hạn; kết quả bốc bỏ; trận đang chơi -> ``abandoned``
    (không tỉ số, không tính xếp hạng – AC18).
    """
    rooms = list(
        await session.scalars(
            select(PlayRoom)
            .where(PlayRoom.status == "open", PlayRoom.end_at <= now - CLOSE_GRACE)
            .with_for_update(skip_locked=True)
        )
    )
    for room in rooms:
        await close_room(session, room, now)
    return len(rooms)


async def close_room(session: AsyncSession, room: PlayRoom, now: datetime) -> None:
    room.status = "closed"
    room.closed_at = now
    room.version += 1
    await session.execute(
        update(PlayRoomRequest)
        .where(PlayRoomRequest.room_id == room.id, PlayRoomRequest.status == "pending")
        .values(status="expired", decided_at=now)
    )
    match = await session.scalar(
        select(PlayMatch).where(
            PlayMatch.room_id == room.id, PlayMatch.status.in_(("drawn", "playing"))
        )
    )
    if match is not None:
        if match.status == "drawn":
            await session.delete(match)
        else:
            match.status, match.ended_at = "abandoned", now
    await session.execute(
        update(PlayRoomMember)
        .where(PlayRoomMember.room_id == room.id, PlayRoomMember.queue_state == "playing")
        .values(queue_state="waiting")
    )


async def close_cancelled(session: AsyncSession, codes: list[str], now: datetime) -> int:
    """Booking đã bị Admin hủy (T-051) -> đóng phòng, báo người liên quan. Không commit.

    Đã đóng thì bỏ qua (handler và job chạy trùng không báo hai lần). Yêu cầu / lời mời đang chờ ->
    ``cancelled``; trận đã bốc hoặc lọt vào đúng lúc hủy -> ``abandoned``. Chủ đơn nhận thông báo
    "đã bị sân hủy" riêng nên không nhận câu này.
    """
    if not codes:
        return 0
    rooms = list(
        await session.scalars(
            select(PlayRoom)
            .where(PlayRoom.booking_code.in_(sorted(set(codes))), PlayRoom.status == "open")
            .order_by(PlayRoom.id)
            .with_for_update()
        )
    )
    for room in rooms:
        ref = await engine.item_customer_ref(session, room.booking_code)
        owner = await members.customer_id_of_ref(session, ref) if ref else None
        asked = await session.scalars(
            update(PlayRoomRequest)
            .where(PlayRoomRequest.room_id == room.id, PlayRoomRequest.status == "pending")
            .values(status="cancelled", decided_at=now)
            .returning(PlayRoomRequest.customer_id)
        )
        people = set(asked) | set(
            await session.scalars(
                select(PlayRoomMember.customer_id).where(PlayRoomMember.room_id == room.id)
            )
        )
        match = await session.scalar(
            select(PlayMatch).where(
                PlayMatch.room_id == room.id, PlayMatch.status.in_(("drawn", "playing"))
            )
        )
        if match is not None:
            match.status, match.ended_at = "abandoned", now
            await session.flush()
        await close_room(session, room, now)
        start = room.start_at.astimezone(settings.tz)
        text = (
            f"Buổi chơi {room.resource_name} {hm(room.start_at)}–{hm(room.end_at)} "
            f"{start:%d/%m} đã bị hủy nên phòng đã đóng."
        )
        for customer_id in sorted(people - {owner}):
            inbox.notify(session, customer_id, "room.cancelled", text, room_id=room.id)
    return len(rooms)


async def _close_any_cancelled(session: AsyncSession, now: datetime) -> int:
    """Lưới an toàn khi lỡ sự kiện: phòng còn mở mà booking đã hủy."""
    codes = list(
        await session.scalars(select(PlayRoom.booking_code).where(PlayRoom.status == "open"))
    )
    gone = await engine.cancelled_booking_codes(session, codes)
    return await close_cancelled(session, sorted(gone), now)


async def tick(session: AsyncSession) -> tuple[int, int]:
    """Job mỗi phút (commit): (số phòng tạo thêm, số phòng đóng)."""
    now = datetime.now(UTC)
    created = await backfill(session, now)
    closed = await close_expired(session, now)
    closed += await _close_any_cancelled(session, now)
    await session.commit()
    await inbox.publish_created(session)
    if created or closed:
        logger.info("Play rooms: %s created, %s closed", created, closed)
    return created, closed

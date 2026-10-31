"""Mặt tiền phòng chơi cho module khác (Tổng quan khu hội viên, T-018) – chỉ đọc."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members import api as members
from app.modules.play_rooms.common import CAPACITY, eligible, is_closed, person_out
from app.modules.play_rooms.models import PlayRoom, PlayRoomMember
from app.modules.play_rooms.schemas import PersonOut

PREVIEW = 4  # số avatar xem trước


@dataclass(frozen=True)
class MyRoom:
    room_id: int
    booking_code: str
    resource_name: str
    resource_type_name: str
    start_at: datetime
    end_at: datetime
    role: str  # host | member
    host_name: str
    members_preview: list[PersonOut]
    count: int
    capacity: int


async def my_rooms(session: AsyncSession, customer_id: int) -> list[MyRoom]:
    """Phòng chưa đóng (mọi ngày) mà hội viên đang ở trong, Host đủ điều kiện; theo giờ bắt đầu."""
    now = datetime.now(UTC)
    rooms = [
        r
        for r in await session.scalars(
            select(PlayRoom)
            .join(PlayRoomMember, PlayRoomMember.room_id == PlayRoom.id)
            .where(PlayRoomMember.customer_id == customer_id, PlayRoom.status == "open")
            .order_by(PlayRoom.start_at, PlayRoom.id)
        )
        if not is_closed(r, now)
    ]
    ok = await eligible(session, {r.host_customer_id for r in rooms})
    rooms = [r for r in rooms if r.host_customer_id in ok]
    if not rooms:
        return []
    by_room: dict[int, list[PlayRoomMember]] = {r.id: [] for r in rooms}
    for m in await session.scalars(
        select(PlayRoomMember)
        .where(PlayRoomMember.room_id.in_(list(by_room)))
        .order_by(PlayRoomMember.joined_at, PlayRoomMember.id)
    ):
        by_room[m.room_id].append(m)
    people = await members.room_people(
        session, {m.customer_id for ms in by_room.values() for m in ms}
    )
    out: list[MyRoom] = []
    for r in rooms:
        ms = sorted(by_room[r.id], key=lambda m: m.customer_id != r.host_customer_id)
        out.append(
            MyRoom(
                room_id=r.id,
                booking_code=r.booking_code,
                resource_name=r.resource_name,
                resource_type_name=r.resource_type_name,
                start_at=r.start_at,
                end_at=r.end_at,
                role="host" if r.host_customer_id == customer_id else "member",
                host_name=person_out(people.get(r.host_customer_id)).display_name,
                members_preview=[person_out(people.get(m.customer_id)) for m in ms[:PREVIEW]],
                count=len(ms),
                capacity=CAPACITY,
            )
        )
    return out


async def booking_codes_with_room(session: AsyncSession, codes: list[str]) -> set[str]:
    """Mã con nào đã có phòng (dù mình còn trong phòng hay không)."""
    if not codes:
        return set()
    return set(
        await session.scalars(select(PlayRoom.booking_code).where(PlayRoom.booking_code.in_(codes)))
    )


async def room_id_for_booking(session: AsyncSession, customer_id: int, code: str) -> int | None:
    """Phòng của khối booking ``code`` nếu đã tạo, Host đủ điều kiện và mình đang ở trong phòng."""
    room = await session.scalar(select(PlayRoom).where(PlayRoom.booking_code == code))
    if room is None or room.host_customer_id not in await eligible(
        session, {room.host_customer_id}
    ):
        return None
    member = await session.scalar(
        select(PlayRoomMember.id).where(
            PlayRoomMember.room_id == room.id, PlayRoomMember.customer_id == customer_id
        )
    )
    return room.id if member is not None else None

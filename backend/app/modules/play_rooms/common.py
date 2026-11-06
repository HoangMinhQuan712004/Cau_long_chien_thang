"""Phần dùng chung của phòng chơi: hằng số, người thao tác, điều kiện Host, khóa phòng."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.config import settings
from app.modules.auth import api as auth
from app.modules.members import api as members
from app.modules.play_rooms import errors
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember
from app.modules.play_rooms.schemas import PersonOut

CAPACITY = 8  # người / sân, tính cả Host
CLOSE_GRACE = timedelta(minutes=10)  # hết giờ + 10 phút -> phòng khóa (AC3)
START_EARLY = timedelta(minutes=15)  # bắt đầu trận được từ 15 phút trước giờ (AC16)


@dataclass(frozen=True)
class Me:
    """Hội viên đang thao tác (theo phiên)."""

    user_id: int
    customer_id: int

    @property
    def idem_key(self) -> str:
        return f"customer:{self.user_id}"


def closes_at(room: PlayRoom) -> datetime:
    return room.end_at + CLOSE_GRACE


def is_closed(room: PlayRoom, now: datetime) -> bool:
    return room.status == "closed" or now >= closes_at(room)


def _hm(t: datetime) -> str:
    local = t.astimezone(settings.tz)
    return f"{local.hour}h" if local.minute == 0 else f"{local.hour}h{local.minute:02d}"


def room_label(room: PlayRoom) -> str:
    """'Sân 1 · 18h–19h' – dùng trong thông báo."""
    return f"{room.resource_name} · {_hm(room.start_at)}–{_hm(room.end_at)}"


def room_link(room_id: int) -> str:
    return f"/hoi-vien/phong/{room_id}"


def avatar_url(person: members.RoomPerson | None) -> str | None:
    return members.avatar_url(person.customer_id, person.avatar_etag) if person else None


def person_out(person: members.RoomPerson | None) -> PersonOut:
    return PersonOut(
        display_name=person.display_name if person else "Hội viên",
        avatar_url=avatar_url(person),
    )


def name_of(people: dict[int, members.RoomPerson], customer_id: int) -> str:
    p = people.get(customer_id)
    return p.display_name if p else "Hội viên"


async def eligible(session: AsyncSession, customer_ids: set[int]) -> set[int]:
    """Hội viên **Hoạt động** có tài khoản liên kết (T-017 AC2, AC9) – xét lúc đọc / thao tác."""
    people = await members.room_people(session, customer_ids)
    active = {cid: p for cid, p in people.items() if p.is_active_member}
    linked = await auth.linked_phones(session, {p.phone for p in active.values()})
    return {cid for cid, p in active.items() if p.phone in linked}


def actor(me: Me, people: dict[int, members.RoomPerson]) -> AuditActor:
    p = people.get(me.customer_id)
    code = p.member_code if p and p.member_code else str(me.customer_id)
    return AuditActor(type="customer", id=me.user_id, label=f"Hội viên · {code}")


async def lock_room(session: AsyncSession, room_id: int) -> PlayRoom:
    """Khóa dòng phòng (``FOR UPDATE``): mọi thao tác ghi trên một phòng chạy lần lượt (AC10)."""
    room = await session.scalar(
        select(PlayRoom)
        .where(PlayRoom.id == room_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if room is None:
        raise errors.not_found()
    return room


async def visible_room(session: AsyncSession, room_id: int, lock: bool) -> PlayRoom:
    """Phòng có Host đủ điều kiện, không thì 404 (ẩn – AC2 chốt 31/10)."""
    if lock:
        room = await lock_room(session, room_id)
    else:
        room = await session.get(PlayRoom, room_id)
        if room is None:
            raise errors.not_found()
    if room.host_customer_id not in await eligible(session, {room.host_customer_id}):
        raise errors.not_found()
    return room


async def writable_room(
    session: AsyncSession, room_id: int, version: int | None, now: datetime
) -> PlayRoom:
    """Khóa + kiểm: 404 (không có / ẩn) -> E-ROOM-1 (đã đóng) -> E-ROOM-6 (``version`` cũ)."""
    room = await visible_room(session, room_id, lock=True)
    if is_closed(room, now):
        raise errors.closed()
    if version is not None and version != room.version:
        raise errors.stale()
    return room


def touch(room: PlayRoom) -> None:
    room.version += 1


async def member_rows(session: AsyncSession, room_id: int) -> list[PlayRoomMember]:
    return list(
        await session.scalars(
            select(PlayRoomMember)
            .where(PlayRoomMember.room_id == room_id)
            .order_by(PlayRoomMember.joined_at, PlayRoomMember.id)
        )
    )


async def member_row(
    session: AsyncSession, room_id: int, customer_id: int
) -> PlayRoomMember | None:
    return await session.scalar(
        select(PlayRoomMember).where(
            PlayRoomMember.room_id == room_id, PlayRoomMember.customer_id == customer_id
        )
    )


async def member_count(session: AsyncSession, room_id: int) -> int:
    count = await session.scalar(select(func.count()).where(PlayRoomMember.room_id == room_id))
    return count or 0


async def active_match(session: AsyncSession, room_id: int) -> PlayMatch | None:
    """Trận vừa bốc / đang chơi (tối đa một mỗi phòng)."""
    return await session.scalar(
        select(PlayMatch).where(
            PlayMatch.room_id == room_id, PlayMatch.status.in_(("drawn", "playing"))
        )
    )


async def release_player(session: AsyncSession, room_id: int, customer_id: int, me: bool) -> None:
    """Trước khi một người ra khỏi phòng: đang chơi -> E-ROOM-5; đã được bốc -> xóa kết quả bốc."""
    match = await active_match(session, room_id)
    if match is None or customer_id not in (*match.team_a, *match.team_b):
        return
    if match.status == "playing":
        raise errors.in_match(match.no, me)
    await session.delete(match)
    await session.flush()

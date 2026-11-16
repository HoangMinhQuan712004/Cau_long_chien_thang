"""Đọc: Danh sách sân hôm nay (AC4–AC6) và chi tiết phòng (AC25)."""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine import api as engine
from app.modules.members import api as members
from app.modules.play_rooms import tiers
from app.modules.play_rooms.common import (
    CAPACITY,
    START_EARLY,
    Me,
    active_match,
    avatar_url,
    closes_at,
    eligible,
    is_closed,
    member_rows,
    person_out,
    readable_room,
    rooms_entered,
)
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember, PlayRoomRequest
from app.modules.play_rooms.schemas import (
    CurrentMatchOut,
    PendingPersonOut,
    PlayerOut,
    RoomCard,
    RoomDetail,
    RoomList,
    RoomMemberOut,
)


def _today_bounds(now: datetime) -> tuple[datetime, datetime]:
    today = now.astimezone(settings.tz).date()
    start = datetime.combine(today, time(0), tzinfo=settings.tz)
    return start, start + timedelta(days=1)


# Mã đơn BK-YYYYMMDD-NNN, hoặc mã con thêm -NN (T-054). Chỉ chữ số: an toàn khi ghép vào LIKE
_SEARCH_CODE = re.compile(r"BK-\d{8}-\d{3}(-\d{2})?", re.ASCII)


async def _cards(
    session: AsyncSession, me: Me, rooms: list[PlayRoom], ended: set[int], now: datetime
) -> list[RoomCard]:
    """Thẻ phòng (không có mã booking, SĐT, id hồ sơ). ``ended``: id phòng không xin vào được."""
    ids = [r.id for r in rooms]
    entered = await rooms_entered(session, me.customer_id, [r for r in rooms if r.id in ended])
    by_room: dict[int, list[PlayRoomMember]] = {i: [] for i in ids}
    if ids:
        for m in await session.scalars(
            select(PlayRoomMember)
            .where(PlayRoomMember.room_id.in_(ids))
            .order_by(PlayRoomMember.joined_at, PlayRoomMember.id)
        ):
            by_room[m.room_id].append(m)
    mine_pending = await _my_pending(session, me, ids)
    people = await members.room_people(
        session,
        {m.customer_id for ms in by_room.values() for m in ms}
        | {r.host_customer_id for r in rooms}
        | {me.customer_id},
    )
    mine_person = people.get(me.customer_id)

    cards: list[RoomCard] = []
    for r in rooms:
        ms = sorted(by_room[r.id], key=lambda m: m.customer_id != r.host_customer_id)
        is_mine = any(m.customer_id == me.customer_id for m in ms)
        is_ended = r.id in ended
        can_view = not is_ended or r.id in entered
        cards.append(
            RoomCard(
                id=r.id,
                resource_name=r.resource_name,
                resource_type_name=r.resource_type_name,
                start_at=r.start_at,
                end_at=r.end_at,
                phase="ongoing" if r.start_at <= now else "upcoming",
                status="ended" if is_ended else "open",
                can_view=can_view,
                play_date=r.start_at.astimezone(settings.tz).date(),
                host=person_out(people.get(r.host_customer_id)),
                # Người ngoài phòng đã kết thúc không biết ai chơi, kể cả khi tìm bằng mã
                members=[person_out(people.get(m.customer_id)) for m in ms] if can_view else [],
                member_count=len(ms) if can_view else 0,
                capacity=CAPACITY,
                is_mine=is_mine,
                my_join_pending=not is_ended and (r.id, "join") in mine_pending,
                my_invite_id=None if is_ended else mine_pending.get((r.id, "invite")),
                tier_range=tiers.range_out(r),
                my_join_block=None if is_mine or is_ended else tiers.block_of(r, mine_person),
                version=r.version,
            )
        )
    return cards


async def _search(session: AsyncSession, me: Me, raw: str, now: datetime) -> list[RoomCard]:
    """Tìm đúng mã (T-054): mọi ngày, mọi trạng thái, bỏ qua ``scope``. Không tìm ra: Host không đủ
    điều kiện, booking đã hủy mà phòng không có trận ``finished``, booking chưa có phòng – cùng một
    kết quả rỗng như mã không tồn tại, không phân biệt lý do."""
    code = "".join(raw.split()).upper()
    found = _SEARCH_CODE.fullmatch(code)
    if found is None:
        return []
    match = (
        PlayRoom.booking_code == code if found.group(1) else PlayRoom.booking_code.like(f"{code}-%")
    )
    rooms = list(
        await session.scalars(
            select(PlayRoom)
            .where(match)
            .order_by(PlayRoom.start_at, PlayRoom.resource_name, PlayRoom.id)
        )
    )
    ok_hosts = await eligible(session, {r.host_customer_id for r in rooms})
    rooms = [r for r in rooms if r.host_customer_id in ok_hosts]
    gone = await engine.cancelled_booking_codes(session, [r.booking_code for r in rooms])
    cancelled = [r.id for r in rooms if r.booking_code in gone]
    played = (
        set(
            await session.scalars(
                select(PlayMatch.room_id)
                .where(PlayMatch.room_id.in_(cancelled), PlayMatch.status == "finished")
                .distinct()
            )
        )
        if cancelled
        else set()
    )
    rooms = [r for r in rooms if r.booking_code not in gone or r.id in played]
    ended = {r.id for r in rooms if is_closed(r, now) or r.booking_code in gone}
    return await _cards(session, me, rooms, ended, now)


async def list_rooms(
    session: AsyncSession, me: Me, scope: Literal["all", "mine"], q: str | None = None
) -> RoomList:
    """Phòng **hôm nay còn mở** có Host đủ điều kiện, theo giờ bắt đầu rồi tên sân. Có ``q``:
    ``items`` là kết quả tìm, số liệu banner vẫn của hôm nay."""
    now = datetime.now(UTC)
    start, end = _today_bounds(now)
    rooms = [
        r
        for r in await session.scalars(
            select(PlayRoom)
            .where(PlayRoom.status == "open", PlayRoom.start_at >= start, PlayRoom.start_at < end)
            .order_by(PlayRoom.start_at, PlayRoom.resource_name, PlayRoom.id)
        )
        if not is_closed(r, now)
    ]
    ok_hosts = await eligible(session, {r.host_customer_id for r in rooms})
    gone = await engine.cancelled_booking_codes(session, [r.booking_code for r in rooms])
    rooms = [r for r in rooms if r.host_customer_id in ok_hosts and r.booking_code not in gone]
    cards = await _cards(session, me, rooms, set(), now)
    mine = [c for c in cards if c.is_mine]
    if q is not None:
        items = await _search(session, me, q, now)
    else:
        items = mine if scope == "mine" else cards
    return RoomList(
        date=now.astimezone(settings.tz).date(),
        ongoing_count=sum(c.phase == "ongoing" for c in cards),
        upcoming_count=sum(c.phase == "upcoming" for c in cards),
        mine_count=len(mine),
        all_count=len(cards),
        items=items,
    )


async def _my_pending(
    session: AsyncSession, me: Me, room_ids: list[int]
) -> dict[tuple[int, str], int]:
    """(phòng, loại) -> id yêu cầu / lời mời đang chờ của mình."""
    if not room_ids:
        return {}
    rows = await session.scalars(
        select(PlayRoomRequest).where(
            PlayRoomRequest.room_id.in_(room_ids),
            PlayRoomRequest.customer_id == me.customer_id,
            PlayRoomRequest.status == "pending",
        )
    )
    return {(r.room_id, r.kind): r.id for r in rows}


async def room_detail(session: AsyncSession, me: Me, room_id: int) -> RoomDetail:
    """Phòng đã kết thúc chỉ người trong phòng xem được, chỉ đọc (T-054). Host không đủ điều kiện
    -> 404."""
    room = await readable_room(session, me.customer_id, room_id)
    return await detail_of(session, me, room)


async def detail_of(session: AsyncSession, me: Me, room: PlayRoom) -> RoomDetail:
    now = datetime.now(UTC)
    rows = await member_rows(session, room.id)
    rows.sort(key=lambda m: m.customer_id != room.host_customer_id)
    is_host = room.host_customer_id == me.customer_id
    in_room = any(m.customer_id == me.customer_id for m in rows)

    pending = list(
        await session.scalars(
            select(PlayRoomRequest)
            .where(PlayRoomRequest.room_id == room.id, PlayRoomRequest.status == "pending")
            .order_by(PlayRoomRequest.created_at, PlayRoomRequest.id)
        )
    )
    match = await active_match(session, room.id)
    ids = {m.customer_id for m in rows} | {p.customer_id for p in pending} | {me.customer_id}
    if match is not None:
        ids |= {*match.team_a, *match.team_b}
    people = await members.room_people(session, ids)

    def pending_out(kind: str) -> list[PendingPersonOut]:
        if not is_host:
            return []
        return [
            PendingPersonOut(
                id=p.id,
                display_name=person_out(people.get(p.customer_id)).display_name,
                avatar_url=avatar_url(people.get(p.customer_id)),
                created_at=p.created_at,
                tier=(people[p.customer_id].tier if p.customer_id in people else None),
            )
            for p in pending
            if p.kind == kind
        ]

    mine = {p.kind: p.id for p in pending if p.customer_id == me.customer_id}
    closed = is_closed(room, now)
    return RoomDetail(
        id=room.id,
        status="closed" if closed else "open",
        phase="closed" if closed else ("ongoing" if room.start_at <= now else "upcoming"),
        format=room.format,  # type: ignore[arg-type]
        resource_name=room.resource_name,
        resource_type_name=room.resource_type_name,
        start_at=room.start_at,
        end_at=room.end_at,
        closes_at=closes_at(room),
        can_start_from=room.start_at - START_EARLY,
        capacity=CAPACITY,
        version=room.version,
        my_role="host" if is_host else ("member" if in_room else "outsider"),
        my_join_pending="join" in mine,
        my_invite_id=mine.get("invite"),
        tier_range=tiers.range_out(room),
        my_join_block=None if in_room else tiers.block_of(room, people.get(me.customer_id)),
        members=[
            RoomMemberOut(
                id=m.id,
                display_name=person_out(people.get(m.customer_id)).display_name,
                avatar_url=avatar_url(people.get(m.customer_id)),
                role="host" if m.customer_id == room.host_customer_id else "member",
                queue_state=m.queue_state,  # type: ignore[arg-type]
                waiting_since=m.waiting_since,
                is_me=m.customer_id == me.customer_id,
            )
            for m in rows
        ],
        join_requests=pending_out("join"),
        invites=pending_out("invite"),
        current_match=_current(match, rows, people),
    )


def _current(
    match: PlayMatch | None,
    rows: list[PlayRoomMember],
    people: dict[int, members.RoomPerson],
) -> CurrentMatchOut | None:
    if match is None:
        return None
    row_of = {m.customer_id: m.id for m in rows}

    def players(ids: list[int]) -> list[PlayerOut]:
        return [
            PlayerOut(
                member_id=row_of.get(cid),
                display_name=str(
                    match.names.get(str(cid)) or person_out(people.get(cid)).display_name
                ),
                avatar_url=avatar_url(people.get(cid)),
            )
            for cid in ids
        ]

    return CurrentMatchOut(
        no=match.no,
        format=match.format,  # type: ignore[arg-type]
        status=match.status,  # type: ignore[arg-type]
        team_a=players(match.team_a),
        team_b=players(match.team_b),
        started_at=match.started_at,
    )

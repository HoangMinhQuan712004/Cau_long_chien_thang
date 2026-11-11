"""Theo dõi sân (T-069): Admin / người có ``play_rooms.monitor`` xem mọi phòng chơi của một ngày.

**Chỉ đọc.** Khác màn hội viên:
- tên thật + biệt danh + mã HV, kể cả hội viên chọn ẩn danh (T-030 không áp cho quyền này);
  không SĐT;
- xem được mọi phòng – kể cả phòng đã kết thúc mà mình không ở trong (T-054 không áp), phòng của
  booking đã hủy, phòng có Host không còn đủ điều kiện.

Sân lấy qua ``booking_engine.api`` (ADR-003); người qua ``members.api``.
"""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.members import api as members
from app.modules.play_rooms import errors
from app.modules.play_rooms.common import avatar_url, is_closed
from app.modules.play_rooms.matches import finished_matches, standings
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember
from app.modules.play_rooms.schemas import (
    MonitorCourt,
    MonitorDay,
    MonitorMatch,
    MonitorMember,
    MonitorPerson,
    MonitorRankingRow,
    MonitorRoom,
    MonitorRoomDetail,
)

MAX_DAYS = 366  # xem lại tối đa ±1 năm quanh hôm nay
SHOWN_MATCHES = ("drawn", "playing", "finished")  # trận bị bỏ (abandoned) không hiện

People = dict[int, members.RoomPerson]


def parse_day(raw: str | None, now: datetime) -> date:
    """``YYYY-MM-DD`` (mặc định hôm nay giờ VN), trong ±1 năm; sai -> 422 E-001."""
    today = now.astimezone(settings.tz).date()
    if raw is None or raw == "":
        return today
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        raise AppError("E-001", "Ngày không hợp lệ (định dạng YYYY-MM-DD).", 422) from None
    if abs((day - today).days) > MAX_DAYS:
        raise AppError("E-001", "Chỉ xem được trong vòng 1 năm quanh hôm nay.", 422)
    return day


def _person(people: People, cid: int, fallback: str = "Hội viên") -> MonitorPerson:
    p = people.get(cid)
    if p is None:  # hồ sơ đã xóa: tên chụp lúc bốc trận (nếu có)
        return MonitorPerson(
            customer_id=cid,
            full_name=fallback,
            nickname=None,
            member_code=None,
            tier=None,
            avatar_url=None,
        )
    return MonitorPerson(
        customer_id=cid,
        full_name=p.full_name or p.display_name,
        nickname=p.nickname,
        member_code=p.member_code,
        tier=p.tier,
        avatar_url=avatar_url(p),
    )


def _match(m: PlayMatch, people: People) -> MonitorMatch:
    def team(ids: list[int]) -> list[MonitorPerson]:
        return [_person(people, c, str(m.names.get(str(c)) or "Hội viên")) for c in ids]

    done = m.status == "finished"
    return MonitorMatch(
        no=m.no,
        format=m.format,  # type: ignore[arg-type]
        status=m.status,  # type: ignore[arg-type]
        team_a=team(m.team_a),
        team_b=team(m.team_b),
        score_a=m.score_a if done else None,
        score_b=m.score_b if done else None,
        winner=m.winner if done else None,  # type: ignore[arg-type]
        started_at=m.started_at,
        ended_at=m.ended_at,
    )


def _status(room: PlayRoom, cancelled: set[str], now: datetime) -> str:
    if room.booking_code in cancelled:
        return "cancelled"
    if is_closed(room, now):
        return "ended"
    return "playing" if room.start_at <= now else "upcoming"


def _room(
    room: PlayRoom,
    *,
    status: str,
    member_count: int,
    room_matches: list[PlayMatch],
    people: People,
) -> MonitorRoom:
    current = next((m for m in room_matches if m.status in ("drawn", "playing")), None)
    finished = [m for m in room_matches if m.status == "finished"]  # mới nhất trước
    return MonitorRoom(
        room_id=room.id,
        booking_code=room.booking_code,
        start_at=room.start_at,
        end_at=room.end_at,
        status=status,  # type: ignore[arg-type]
        host=_person(people, room.host_customer_id),
        member_count=member_count,
        format=room.format,  # type: ignore[arg-type]
        min_tier=room.min_tier,
        max_tier=room.max_tier,
        matches_finished=len(finished),
        current_match=_match(current, people) if current else None,
        last_match=_match(finished[0], people) if finished else None,
    )


async def _matches_of(session: AsyncSession, room_ids: list[int]) -> dict[int, list[PlayMatch]]:
    """Trận hiện được của các phòng, mới nhất trước (trận đang đánh chưa có ``ended_at``)."""
    out: dict[int, list[PlayMatch]] = {rid: [] for rid in room_ids}
    if not room_ids:
        return out
    rows = await session.scalars(
        select(PlayMatch)
        .where(PlayMatch.room_id.in_(room_ids), PlayMatch.status.in_(SHOWN_MATCHES))
        .order_by(PlayMatch.room_id, PlayMatch.no.desc())
    )
    for m in rows:
        out[m.room_id].append(m)
    return out


def _ids(rooms: list[PlayRoom], matches: dict[int, list[PlayMatch]]) -> set[int]:
    ids = {r.host_customer_id for r in rooms}
    for room_matches in matches.values():
        for m in room_matches:
            ids |= {*m.team_a, *m.team_b}
    return ids


async def day_view(session: AsyncSession, raw_day: str | None) -> MonitorDay:
    """Mỗi sân một hàng (thứ tự sân), phòng của ngày theo giờ. Sân ngừng / đã xóa chỉ hiện khi
    có phòng trong ngày."""
    now = datetime.now(UTC)
    day = parse_day(raw_day, now)
    start = datetime.combine(day, time(0), tzinfo=settings.tz)
    rooms = list(
        await session.scalars(
            select(PlayRoom)
            .where(PlayRoom.start_at >= start, PlayRoom.start_at < start + timedelta(days=1))
            .order_by(PlayRoom.start_at, PlayRoom.id)
        )
    )
    room_ids = [r.id for r in rooms]
    matches = await _matches_of(session, room_ids)
    counts: dict[int, int] = {}
    if room_ids:
        counts = dict(
            (
                await session.execute(
                    select(PlayRoomMember.room_id, func.count())
                    .where(PlayRoomMember.room_id.in_(room_ids))
                    .group_by(PlayRoomMember.room_id)
                )
            ).all()
        )
    people = await members.room_people(session, _ids(rooms, matches))
    cancelled = await engine.cancelled_booking_codes(session, [r.booking_code for r in rooms])

    by_court: dict[str, list[MonitorRoom]] = {}
    for r in rooms:
        by_court.setdefault(r.resource_code, []).append(
            _room(
                r,
                status=_status(r, cancelled, now),
                member_count=counts.get(r.id, 0),
                room_matches=matches[r.id],
                people=people,
            )
        )
    courts = [
        MonitorCourt(
            resource_code=c.code,
            resource_name=c.name,
            is_active=c.is_active,
            rooms=by_court.pop(c.code, []),
        )
        for c in (await engine.list_resources(session)).items
    ]
    courts = [c for c in courts if c.is_active or c.rooms]
    # Sân đã xóa nhưng còn phòng trong ngày: tên chụp trên phòng
    names = {r.resource_code: r.resource_name for r in rooms}
    courts += [
        MonitorCourt(resource_code=code, resource_name=names[code], is_active=False, rooms=items)
        for code, items in by_court.items()
    ]
    return MonitorDay(date=day, courts=courts)


async def room_view(session: AsyncSession, room_id: int) -> MonitorRoomDetail:
    """Chi tiết chỉ đọc: thành viên, mọi trận, bảng xếp hạng. Không có phòng -> 404."""
    room = await session.get(PlayRoom, room_id)
    if room is None:
        raise errors.not_found()
    now = datetime.now(UTC)
    rows = list(
        await session.scalars(
            select(PlayRoomMember)
            .where(PlayRoomMember.room_id == room.id)
            .order_by(PlayRoomMember.joined_at, PlayRoomMember.id)
        )
    )
    rows.sort(key=lambda m: m.customer_id != room.host_customer_id)  # Host đầu tiên
    room_matches = (await _matches_of(session, [room.id]))[room.id]
    table = standings(await finished_matches(session, room.id))
    ids = _ids([room], {room.id: room_matches}) | {m.customer_id for m in rows}
    ids |= {s.customer_id for s in table}
    people = await members.room_people(session, ids)
    cancelled = await engine.cancelled_booking_codes(session, [room.booking_code])
    return MonitorRoomDetail(
        room=_room(
            room,
            status=_status(room, cancelled, now),
            member_count=len(rows),
            room_matches=room_matches,
            people=people,
        ),
        members=[
            MonitorMember(
                **_person(people, m.customer_id).model_dump(),
                role="host" if m.customer_id == room.host_customer_id else "member",
                queue_state=m.queue_state,  # type: ignore[arg-type]
            )
            for m in rows
        ],
        matches=[_match(m, people) for m in room_matches],
        ranking=[
            MonitorRankingRow(
                **_person(people, s.customer_id, s.latest_name).model_dump(),
                rank=s.rank,
                wins=s.wins,
                losses=s.played - s.wins,
                played=s.played,
                win_rate=s.win_rate,
            )
            for s in table
        ],
    )

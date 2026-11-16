"""Phòng chơi mẫu cho link dev (T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Phòng tạo bằng đường thật (``lifecycle.ensure_for_codes`` từ khối booking mẫu – khoảng hạng đi theo
đơn); thành viên, yêu cầu chờ duyệt và trận đã lưu kết quả thêm thẳng vào bảng của module.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members import api as members
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.common import CLOSE_GRACE, name_of
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember, PlayRoomRequest


@dataclass(frozen=True)
class DemoMatch:
    team_a: list[int]
    team_b: list[int]
    score_a: int
    score_b: int
    started_at: datetime
    ended_at: datetime


async def seed_room(
    session: AsyncSession,
    booking_code: str,
    *,
    member_ids: list[int],
    pending_join: list[int] | None = None,
    matches: list[DemoMatch] | None = None,
    close: bool = False,
) -> int | None:
    """Phòng của khối ``booking_code`` + thành viên / xin vào / trận ``finished``. Trả id phòng."""
    await lifecycle.ensure_for_codes(session, [booking_code])
    room = await session.scalar(select(PlayRoom).where(PlayRoom.booking_code == booking_code))
    if room is None:
        return None
    joined = {room.host_customer_id}
    for cid in member_ids:
        if cid not in joined:
            session.add(PlayRoomMember(room_id=room.id, customer_id=cid))
            joined.add(cid)
    for cid in pending_join or []:
        session.add(PlayRoomRequest(room_id=room.id, customer_id=cid, kind="join"))
    games = matches or []
    people = await members.room_people(session, {c for m in games for c in (*m.team_a, *m.team_b)})
    for no, m in enumerate(games, start=1):
        session.add(
            PlayMatch(
                room_id=room.id,
                no=no,
                format="2v2" if len(m.team_a) == 2 else "1v1",
                team_a=m.team_a,
                team_b=m.team_b,
                names={str(c): name_of(people, c) for c in (*m.team_a, *m.team_b)},
                status="finished",
                drawn_at=m.started_at,
                started_at=m.started_at,
                ended_at=m.ended_at,
                score_a=m.score_a,
                score_b=m.score_b,
                winner="a" if m.score_a > m.score_b else "b",
            )
        )
    if close:
        room.status, room.closed_at = "closed", room.end_at + CLOSE_GRACE
    await session.flush()
    return room.id


async def purge_demo(
    session: AsyncSession, booking_codes: list[str], customer_ids: list[int]
) -> int:
    """Xóa phòng của khối mẫu (thành viên / yêu cầu / trận xóa theo FK cascade) và dòng thành viên /
    yêu cầu của hội viên mẫu ở phòng khác. Không commit. Trả số phòng đã xóa."""
    rooms = (
        await session.execute(delete(PlayRoom).where(PlayRoom.booking_code.in_(booking_codes)))
    ).rowcount or 0
    if customer_ids:
        await session.execute(
            delete(PlayRoomMember).where(PlayRoomMember.customer_id.in_(customer_ids))
        )
        await session.execute(
            delete(PlayRoomRequest).where(PlayRoomRequest.customer_id.in_(customer_ids))
        )
    return rooms

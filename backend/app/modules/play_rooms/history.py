"""Lịch sử chơi của hội viên (T-029): các buổi (phòng) có trận đã lưu kết quả mà mình ở đội A/B.

Chỉ dữ liệu của module phòng chơi: sân / giờ đã chụp sẵn trong ``play_room`` (không gọi engine).
Tính cả phòng mình đã rời / bị mời ra (kết quả trận giữ theo id hồ sơ – T-017 AC20).
"""

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from app.modules.play_rooms.schemas import PlayHistory, PlayHistoryItem, PlayHistorySummary


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=settings.tz)


def _next_month(start: datetime) -> datetime:
    return _month_start(start.year + start.month // 12, start.month % 12 + 1)


def parse_month(value: str | None) -> datetime:
    """``YYYY-MM`` -> đầu tháng giờ VN; None -> tháng hiện tại; tháng sai -> 422 E-001."""
    if value is None:
        now = datetime.now(UTC).astimezone(settings.tz)
        return _month_start(now.year, now.month)
    try:
        year, month = (int(p) for p in value.split("-"))
        return _month_start(year, month)
    except ValueError:
        raise AppError("E-001", "Tháng không hợp lệ (YYYY-MM).", 422) from None


async def play_history(session: AsyncSession, customer_id: int, month: str | None) -> PlayHistory:
    start = parse_month(month)
    end = _next_month(start)
    label = f"{start.year:04d}-{start.month:02d}"
    if start > datetime.now(UTC):  # tháng tương lai: trả rỗng
        return PlayHistory(
            month=label, summary=PlayHistorySummary(sessions=0, matches=0, wins=0), items=[]
        )
    rows = await session.execute(
        select(PlayMatch, PlayRoom)
        .join(PlayRoom, PlayRoom.id == PlayMatch.room_id)
        .where(
            PlayMatch.status == "finished",
            or_(PlayMatch.team_a.contains([customer_id]), PlayMatch.team_b.contains([customer_id])),
            PlayRoom.start_at >= start,
            PlayRoom.start_at < end,
        )
    )
    rooms: dict[int, PlayRoom] = {}
    played: dict[int, int] = defaultdict(int)
    won: dict[int, int] = defaultdict(int)
    for match, room in rows:
        rooms[room.id] = room
        played[room.id] += 1
        mine = "a" if customer_id in match.team_a else "b"
        if match.winner == mine:
            won[room.id] += 1
    ordered = sorted(rooms.values(), key=lambda r: (r.start_at, r.id), reverse=True)
    items = [
        PlayHistoryItem(
            room_id=r.id,
            date=r.start_at.astimezone(settings.tz).date(),
            resource_name=r.resource_name,
            resource_type_name=r.resource_type_name,
            start_at=r.start_at,
            end_at=r.end_at,
            matches=played[r.id],
            wins=won[r.id],
            losses=played[r.id] - won[r.id],
        )
        for r in ordered
    ]
    return PlayHistory(
        month=label,
        summary=PlayHistorySummary(
            sessions=len(items),
            matches=sum(i.matches for i in items),
            wins=sum(i.wins for i in items),
        ),
        items=items,
    )

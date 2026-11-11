"""Lịch sử chơi của hội viên (T-029): các buổi (phòng) có trận đã lưu kết quả mà mình ở đội A/B.

Chỉ dữ liệu của module phòng chơi: sân / giờ đã chụp sẵn trong ``play_room`` (không gọi engine).
Tính cả phòng mình đã rời / bị mời ra (kết quả trận giữ theo id hồ sơ – T-017 AC20).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

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


MAX_RANGE_DAYS = 366


def parse_range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime] | None:
    """Khoảng ngày (gồm cả 2 đầu, giờ VN) -> [đầu ngày ``from``, đầu ngày sau ``to``); không gửi ->
    None (dùng tháng). Thiếu một đầu / đảo ngược / quá 1 năm -> 422 E-001."""
    if date_from is None and date_to is None:
        return None
    if date_from is None or date_to is None:
        raise AppError("E-001", "Vui lòng chọn cả Từ ngày và Đến ngày.", 422)
    if date_from > date_to:
        raise AppError("E-001", "Từ ngày phải trước hoặc bằng Đến ngày.", 422)
    if (date_to - date_from).days >= MAX_RANGE_DAYS:
        raise AppError("E-001", "Khoảng ngày tối đa 1 năm.", 422)
    start = datetime.combine(date_from, time(), settings.tz)
    return start, datetime.combine(date_to + timedelta(days=1), time(), settings.tz)


async def play_history(
    session: AsyncSession,
    customer_id: int,
    month: str | None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> PlayHistory:
    """Theo khoảng ``date_from``–``date_to`` nếu có, không thì theo tháng (mặc định tháng này)."""
    span = parse_range(date_from, date_to)
    if span is None:
        start = parse_month(month)
        span = (start, _next_month(start))
    start, end = span
    label = f"{start.year:04d}-{start.month:02d}"
    first, last = start.date(), (end - timedelta(days=1)).date()
    if start > datetime.now(UTC):  # khoảng tương lai: trả rỗng
        return PlayHistory(
            month=label,
            start=first,
            end=last,
            summary=PlayHistorySummary(sessions=0, matches=0, wins=0),
            items=[],
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
    # Trận đã xong vẫn tính dù buổi đó về sau bị hủy (T-052)
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
        start=first,
        end=last,
        summary=PlayHistorySummary(
            sessions=len(items),
            matches=sum(i.matches for i in items),
            wins=sum(i.wins for i in items),
        ),
        items=items,
    )


@dataclass(frozen=True)
class CareerStats:
    """Tổng thắng / thua mọi thời gian của một người – cùng cách đếm Lịch sử chơi."""

    matches: int
    wins: int


async def career_stats(session: AsyncSession, customer_ids: set[int]) -> dict[int, CareerStats]:
    """Mọi trận đã lưu kết quả mà người đó ở đội A/B (kể cả phòng đã rời / buổi bị hủy sau đó, như
    Lịch sử chơi). Chưa có trận nào -> không có trong kết quả."""
    if not customer_ids:
        return {}
    ids = sorted(customer_ids)
    games = await session.scalars(
        select(PlayMatch).where(
            PlayMatch.status == "finished",
            or_(PlayMatch.team_a.overlap(ids), PlayMatch.team_b.overlap(ids)),
        )
    )
    played: dict[int, int] = defaultdict(int)
    won: dict[int, int] = defaultdict(int)
    for m in games:
        for cid in {*m.team_a, *m.team_b} & customer_ids:
            played[cid] += 1
            if m.winner == ("a" if cid in m.team_a else "b"):
                won[cid] += 1
    return {cid: CareerStats(played[cid], won[cid]) for cid in played}

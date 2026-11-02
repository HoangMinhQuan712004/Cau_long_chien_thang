"""Bảng xếp hạng tốc độ + kỷ lục cá nhân (T-030 giai đoạn A). Chỉ đọc."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth import api as auth
from app.modules.members import api as members
from app.modules.records.models import SpeedRecord
from app.modules.records.schemas import Period, SpeedMe, SpeedRanking, SpeedRankingRow

TOP = 10
BAR_FLOOR_KMH = 200
ANONYMOUS = "Hội viên ẩn danh"


def period_bounds(period: Period, day: date) -> tuple[date, date]:
    """(ngày đầu, ngày cuối – tính cả) của kỳ chứa ``day``: tuần T2→CN, tháng, năm."""
    if period == "week":
        first = day - timedelta(days=day.weekday())
        return first, first + timedelta(days=6)
    if period == "month":
        first = day.replace(day=1)
        nxt = date(first.year + first.month // 12, first.month % 12 + 1, 1)
        return first, nxt - timedelta(days=1)
    return date(day.year, 1, 1), date(day.year, 12, 31)


def _at(day: date) -> datetime:
    return datetime.combine(day, time(), settings.tz)


@dataclass(frozen=True)
class _Best:
    customer_id: int
    speed_kmh: int
    measured_at: datetime


async def _best_in(session: AsyncSession, start: datetime, end: datetime) -> list[_Best]:
    """Số đo cao nhất của từng người trong [start, end) – bằng nhau lấy lần đạt sớm hơn."""
    rows = await session.execute(
        select(SpeedRecord.customer_id, SpeedRecord.speed_kmh, SpeedRecord.measured_at)
        .where(SpeedRecord.measured_at >= start, SpeedRecord.measured_at < end)
        .order_by(
            SpeedRecord.customer_id,
            SpeedRecord.speed_kmh.desc(),
            SpeedRecord.measured_at,
            SpeedRecord.id,
        )
        .distinct(SpeedRecord.customer_id)
    )
    return [_Best(cid, kmh, at) for cid, kmh, at in rows]


async def eligible(session: AsyncSession, ids: set[int]) -> dict[int, members.RoomPerson]:
    """Hội viên Hoạt động có tài khoản liên kết (cùng điều kiện phòng chơi) – Ngừng / không còn
    liên kết thì không vào bảng."""
    people = await members.room_people(session, ids)
    active = {cid: p for cid, p in people.items() if p.is_active_member}
    linked = await auth.linked_phones(session, {p.phone for p in active.values()})
    return {cid: p for cid, p in active.items() if p.phone in linked}


def _avatar_url(person: members.RoomPerson) -> str | None:
    if person.avatar_etag is None:
        return None
    return f"{settings.API_PREFIX}/member-area/avatars/{person.customer_id}?v={person.avatar_etag}"


async def ranking(
    session: AsyncSession, customer_id: int, period: Period, day: date
) -> SpeedRanking:
    first, last = period_bounds(period, day)
    best = await _best_in(session, _at(first), _at(last + timedelta(days=1)))
    people = await eligible(session, {b.customer_id for b in best})
    ordered = sorted(
        (b for b in best if b.customer_id in people),
        key=lambda b: (-b.speed_kmh, b.measured_at, b.customer_id),
    )

    def row(rank: int, b: _Best) -> SpeedRankingRow:
        p = people[b.customer_id]
        is_me = b.customer_id == customer_id
        shown = is_me or p.show_on_records
        return SpeedRankingRow(
            rank=rank,
            display_name=p.display_name if shown else ANONYMOUS,
            avatar_url=_avatar_url(p) if shown else None,
            speed_kmh=b.speed_kmh,
            is_me=is_me,
        )

    me = None
    for rank, b in enumerate(ordered, start=1):
        if b.customer_id == customer_id:
            gap = ordered[TOP - 1].speed_kmh - b.speed_kmh if rank > TOP else None
            me = SpeedMe(
                rank=rank, speed_kmh=b.speed_kmh, measured_at=b.measured_at, gap_to_top10=gap
            )
            break
    return SpeedRanking(
        period=period,
        start=first,
        end=last,
        total_members=len(ordered),
        top=[row(rank, b) for rank, b in enumerate(ordered[:TOP], start=1)],
        me=me,
        bar_floor_kmh=BAR_FLOOR_KMH,
    )


async def record_kmh(session: AsyncSession, customer_id: int) -> int | None:
    """Kỷ lục mọi thời gian của một hội viên (km/h) – None khi chưa có số đo."""
    return await session.scalar(
        select(func.max(SpeedRecord.speed_kmh)).where(SpeedRecord.customer_id == customer_id)
    )

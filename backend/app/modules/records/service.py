"""Bảng xếp hạng tốc độ + kỷ lục cá nhân (T-030 giai đoạn A). Chỉ đọc.

T-047: mọi truy vấn ở đây chỉ lấy số đo **đã duyệt** (``APPROVED``) – bản chờ duyệt / bị từ chối
không tính hạng, kỷ lục hay video.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.members import api as members
from app.modules.records import video
from app.modules.records.models import SpeedRecord
from app.modules.records.schemas import (
    Period,
    RecordBreakItem,
    RecordBreakList,
    RecordVideoCard,
    RecordVideoList,
    SpeedMe,
    SpeedRanking,
    SpeedRankingRow,
    VideoPeriod,
)

TOP = 10
BAR_FLOOR_KMH = 200
# T-047: chỉ số đo đã duyệt mới tính (máy đo, Admin nhập, hội viên gửi đã được duyệt)
APPROVED = SpeedRecord.status == "approved"
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
        .where(APPROVED, SpeedRecord.measured_at >= start, SpeedRecord.measured_at < end)
        .order_by(
            SpeedRecord.customer_id,
            SpeedRecord.speed_kmh.desc(),
            SpeedRecord.measured_at,
            SpeedRecord.id,
        )
        .ext(distinct_on(SpeedRecord.customer_id))
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
        select(func.max(SpeedRecord.speed_kmh)).where(
            APPROVED, SpeedRecord.customer_id == customer_id
        )
    )


async def month_best(session: AsyncSession, customer_id: int, day: date) -> int | None:
    """Số đo cao nhất của hội viên trong tháng chứa ``day`` (giờ VN) – T-036."""
    first, last = period_bounds("month", day)
    return await session.scalar(
        select(func.max(SpeedRecord.speed_kmh)).where(
            APPROVED,
            SpeedRecord.customer_id == customer_id,
            SpeedRecord.measured_at >= _at(first),
            SpeedRecord.measured_at < _at(last + timedelta(days=1)),
        )
    )


@dataclass(frozen=True)
class RecordBreak:
    """Một lần phá kỷ lục toàn cụm (T-036). ``customer_id`` chỉ dùng nội bộ, không trả ra API."""

    customer_id: int
    shown: bool  # người xem được thấy tên (mình, hoặc người đó bật Hiện trên kỷ lục)
    display_name: str
    avatar_url: str | None
    speed_kmh: int
    delta_kmh: int | None  # so với kỷ lục cụm trước đó; None = số đo đầu tiên của cụm
    measured_at: datetime
    court_code: str | None
    is_current: bool
    video_url: str | None = None  # T-046: link Admin gắn (phát cả khi người đó ẩn danh)
    id: int = 0
    previous_kmh: int | None = None  # kỷ lục ngay trước; None = số đo đầu tiên của cụm
    video_set_at: datetime | None = None  # T-048: lần dán link mới nhất


async def club_record_breaks(
    session: AsyncSession, viewer_id: int, limit: int | None
) -> list[RecordBreak]:
    """``limit`` lần phá kỷ lục cụm gần nhất, mới nhất trước (``None`` = cả chuỗi – T-048).

    Đi theo thời gian, mỗi số đo vượt mức cao nhất trước đó của cả cụm là một lần phá. Chỉ tính số
    đo của hội viên đủ điều kiện như Bảng xếp hạng (Hoạt động, có liên kết). Ẩn danh như T-030.
    """
    ids = set(await session.scalars(select(SpeedRecord.customer_id).where(APPROVED).distinct()))
    people = await eligible(session, ids)
    if not people:
        return []
    previous = func.max(SpeedRecord.speed_kmh).over(
        order_by=(SpeedRecord.measured_at, SpeedRecord.id), rows=(None, -1)
    )
    ranked = (
        select(
            SpeedRecord.customer_id,
            SpeedRecord.speed_kmh,
            SpeedRecord.measured_at,
            SpeedRecord.court_code,
            SpeedRecord.video_url,
            SpeedRecord.video_set_at,
            SpeedRecord.id,
            previous.label("previous"),
        )
        .where(APPROVED, SpeedRecord.customer_id.in_(sorted(people)))
        .subquery()
    )
    rows = (
        await session.execute(
            select(ranked)
            .where((ranked.c.previous.is_(None)) | (ranked.c.speed_kmh > ranked.c.previous))
            .order_by(ranked.c.measured_at.desc(), ranked.c.id.desc())
            .limit(limit)
        )
    ).all()
    out = []
    for i, r in enumerate(rows):
        p = people[r.customer_id]
        shown = r.customer_id == viewer_id or p.show_on_records
        out.append(
            RecordBreak(
                customer_id=r.customer_id,
                shown=shown,
                display_name=p.display_name if shown else ANONYMOUS,
                avatar_url=_avatar_url(p) if shown else None,
                speed_kmh=r.speed_kmh,
                delta_kmh=None if r.previous is None else r.speed_kmh - r.previous,
                measured_at=r.measured_at,
                court_code=r.court_code,
                is_current=i == 0,
                video_url=r.video_url,
                id=r.id,
                previous_kmh=r.previous,
                video_set_at=r.video_set_at,
            )
        )
    return out


# ------------------------------------------------------------------ dòng thời gian (T-048)


def _local_date(at: datetime) -> date:
    return at.astimezone(settings.tz).date()


async def record_breaks(
    session: AsyncSession, viewer_id: int, period: VideoPeriod, today: date
) -> RecordBreakList:
    """Dòng thời gian phá kỷ lục. ``delta``, kỷ lục trước và số ngày giữ tính trên **toàn chuỗi**,
    kỳ chỉ lọc các dòng hiện ra (theo ngày đo); mốc đầu chỉ có ở "Mọi thời gian"."""
    chain = await club_record_breaks(session, viewer_id, None)
    first = last = None
    if period != "all":
        first, last = period_bounds(period, today)
    days = [_local_date(b.measured_at) for b in chain]
    shown: list[tuple[RecordBreak, int]] = []
    for i, (b, day) in enumerate(zip(chain, days, strict=True)):
        if first is not None and (b.previous_kmh is None or not first <= day <= last):
            continue
        # Mới nhất trước: lần sau của dòng i là dòng i - 1. Số đo được lệch 1 phút nên chặn âm
        shown.append((b, max(0, ((days[i - 1] if i else today) - day).days)))
    cards = await members.record_cards(session, {b.customer_id for b, _ in shown if b.shown})
    courts = (
        {c.code: c.name for c in (await engine.list_resources(session)).items}
        if any(b.court_code for b, _ in shown)
        else {}
    )
    items = []
    for b, held_days in shown:
        clip = video.parse(b.video_url)
        card = cards.get(b.customer_id) if b.shown else None
        items.append(
            RecordBreakItem(
                id=b.id,
                speed_kmh=b.speed_kmh,
                delta_kmh=b.delta_kmh,
                previous_kmh=b.previous_kmh,
                is_current=b.is_current,
                is_baseline=b.previous_kmh is None,
                held_days=held_days,
                measured_at=b.measured_at,
                label_date=_local_date(
                    b.video_set_at if clip and b.video_set_at else b.measured_at
                ),
                # Riêng API này: họ tên thật + biệt danh (người dùng chốt 06/11)
                display_name=card.full_name if card else b.display_name,
                nickname=card.nickname if card else None,
                tier=card.tier if card else None,
                avatar_url=b.avatar_url,
                racket=card.racket if card else None,
                resource_name=courts.get(b.court_code) if b.court_code else None,
                is_me=b.customer_id == viewer_id,
                video=clip,
            )
        )
    return RecordBreakList(period=period, start=first, end=last, items=items)


# ------------------------------------------------------------------ Video & kỷ lục (T-046)

VIDEO_LIMIT = 60


async def record_videos(
    session: AsyncSession, viewer_id: int, period: VideoPeriod, day: date
) -> RecordVideoList:
    """Số đo có video trong kỳ (tuần / tháng / năm / mọi thời gian), mới nhất trước. Chỉ hội viên
    đủ điều kiện như Bảng xếp hạng; ẩn danh như T-030 (video vẫn phát, tên ẩn)."""
    conds = [APPROVED, SpeedRecord.video_url.is_not(None)]
    first = last = None
    if period != "all":
        first, last = period_bounds(period, day)
        conds += [
            SpeedRecord.measured_at >= _at(first),
            SpeedRecord.measured_at < _at(last + timedelta(days=1)),
        ]
    rows = list(
        await session.scalars(
            select(SpeedRecord)
            .where(*conds)
            .order_by(SpeedRecord.measured_at.desc(), SpeedRecord.id.desc())
            .limit(VIDEO_LIMIT * 2)
        )
    )
    people = await eligible(session, {r.customer_id for r in rows})
    courts = (
        {c.code: c.name for c in (await engine.list_resources(session)).items}
        if any(r.court_code for r in rows)
        else {}
    )
    items = []
    for r in rows:
        p = people.get(r.customer_id)
        clip = video.parse(r.video_url)
        if p is None or clip is None:
            continue
        is_me = r.customer_id == viewer_id
        shown = is_me or p.show_on_records
        items.append(
            RecordVideoCard(
                speed_kmh=r.speed_kmh,
                measured_at=r.measured_at,
                display_name=p.display_name if shown else ANONYMOUS,
                avatar_url=_avatar_url(p) if shown else None,
                resource_name=courts.get(r.court_code) if r.court_code else None,
                is_me=is_me,
                video=clip,
            )
        )
    return RecordVideoList(period=period, start=first, end=last, items=items[:VIDEO_LIMIT])

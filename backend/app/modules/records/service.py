"""Bảng xếp hạng tốc độ + kỷ lục cá nhân (T-030 giai đoạn A). Chỉ đọc.

T-047: mọi truy vấn ở đây chỉ lấy số đo **đã duyệt** (``APPROVED``) – bản chờ duyệt / bị từ chối
không tính hạng, kỷ lục hay video.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.members import api as members
from app.modules.play_rooms import api as rooms
from app.modules.records import video
from app.modules.records.models import SpeedRecord
from app.modules.records.schemas import (
    Period,
    PlayStats,
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


async def eligible(session: AsyncSession, ids: set[int]) -> dict[int, members.RoomPerson]:
    """Hội viên Hoạt động có tài khoản liên kết (cùng điều kiện phòng chơi) – Ngừng / không còn
    liên kết thì không vào bảng."""
    people = await members.room_people(session, ids)
    active = {cid: p for cid, p in people.items() if p.is_active_member}
    linked = await auth.linked_phones(session, {p.phone for p in active.values()})
    return {cid: p for cid, p in active.items() if p.phone in linked}


def _avatar_url(person: members.RoomPerson) -> str | None:
    return members.avatar_url(person.customer_id, person.avatar_etag)


# Thứ tự xếp hạng (T-053): mỗi cú một hạng, không đồng hạng
RANK_ORDER = (SpeedRecord.speed_kmh.desc(), SpeedRecord.measured_at, SpeedRecord.id)


def _ahead_of(r: SpeedRecord):
    """Điều kiện "xếp trên cú ``r``" – phải khớp ``RANK_ORDER``."""
    return or_(
        SpeedRecord.speed_kmh > r.speed_kmh,
        and_(
            SpeedRecord.speed_kmh == r.speed_kmh,
            or_(
                SpeedRecord.measured_at < r.measured_at,
                and_(SpeedRecord.measured_at == r.measured_at, SpeedRecord.id < r.id),
            ),
        ),
    )


async def _court_names(session: AsyncSession, rows: list[SpeedRecord]) -> dict[str, str]:
    if not any(r.court_code for r in rows):
        return {}
    return {c.code: c.name for c in (await engine.list_resources(session)).items}


async def ranking(
    session: AsyncSession, customer_id: int, period: Period, day: date
) -> SpeedRanking:
    """Xếp theo **từng cú đập** (T-053, đổi T-030): một người chiếm được nhiều bậc. Chỉ lấy lên bộ
    nhớ các cú hiện ra (top 10 + cú tốt nhất của mình); còn lại đếm bằng SQL."""
    first, last = period_bounds(period, day)
    in_period = (
        APPROVED,
        SpeedRecord.measured_at >= _at(first),
        SpeedRecord.measured_at < _at(last + timedelta(days=1)),
    )
    ids = set(await session.scalars(select(SpeedRecord.customer_id).where(*in_period).distinct()))
    people = await eligible(session, ids)
    conds = (*in_period, SpeedRecord.customer_id.in_(sorted(people)))
    total = await session.scalar(select(func.count()).select_from(SpeedRecord).where(*conds)) or 0
    top = list(
        await session.scalars(select(SpeedRecord).where(*conds).order_by(*RANK_ORDER).limit(TOP))
    )
    mine = None
    if customer_id in people:
        mine = await session.scalar(
            select(SpeedRecord)
            .where(*conds, SpeedRecord.customer_id == customer_id)
            .order_by(*RANK_ORDER)
            .limit(1)
        )
    courts = await _court_names(session, top)

    def row(rank: int, r: SpeedRecord) -> SpeedRankingRow:
        p = people[r.customer_id]
        is_me = r.customer_id == customer_id
        shown = is_me or p.show_on_records
        return SpeedRankingRow(
            rank=rank,
            display_name=p.display_name if shown else ANONYMOUS,
            avatar_url=_avatar_url(p) if shown else None,
            speed_kmh=r.speed_kmh,
            measured_at=r.measured_at,
            resource_name=courts.get(r.court_code) if r.court_code else None,
            is_me=is_me,
            video=video.parse(r.video_url),
        )

    me = None
    if mine is not None:
        ahead = await session.scalar(
            select(func.count()).select_from(SpeedRecord).where(*conds, _ahead_of(mine))
        )
        rank = (ahead or 0) + 1
        person = people[customer_id]
        me = SpeedMe(
            rank=rank,
            display_name=person.display_name,
            avatar_url=_avatar_url(person),
            speed_kmh=mine.speed_kmh,
            measured_at=mine.measured_at,
            gap_to_top10=top[TOP - 1].speed_kmh - mine.speed_kmh if rank > TOP else None,
            video=video.parse(mine.video_url),
        )
    return SpeedRanking(
        period=period,
        start=first,
        end=last,
        total_members=len(people),
        total_records=total,
        top=[row(rank, r) for rank, r in enumerate(top, start=1)],
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


def _play_stats(s: rooms.CareerStats | None) -> PlayStats | None:
    if s is None:
        return None
    return PlayStats(matches=s.matches, wins=s.wins, losses=s.matches - s.wins)


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
    courts = await engine.resource_names(session) if any(b.court_code for b, _ in shown) else {}
    # Tổng thắng / thua mọi thời gian; ẩn danh: không lộ thành tích (cùng quy tắc tên / avatar)
    played = await rooms.career_stats(session, {b.customer_id for b, _ in shown if b.shown})
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
                play_stats=_play_stats(played.get(b.customer_id)) if b.shown else None,
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
    courts = await engine.resource_names(session) if any(r.court_code for r in rows) else {}
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

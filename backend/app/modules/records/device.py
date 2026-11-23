"""Số đo do máy đo tốc độ gửi về (T-030 giai đoạn B) và mốc kỷ lục từng kỳ cho máy đo.

Số đo máy đo vào thẳng ``approved`` (``source = 'device'``, không sửa / xóa được – E-REC-2). Chống
ghi trùng bằng ``source_ref`` (máy gửi lại cùng một cú). Không commit.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members import api as members
from app.modules.records import video
from app.modules.records.models import SPEED_RANGE, SpeedRecord
from app.modules.records.service import APPROVED, _at, eligible, period_bounds

MARK_PERIODS = ("day", "week", "month", "year")
COURT_CODE_MAX = 10
DEVICE_ID_MAX = 50
SOURCE_REF_MAX = 100


def mark_bounds(period: str, day: date) -> tuple[date, date]:
    """(ngày đầu, ngày cuối – tính cả) của kỳ chứa ``day``; ``day`` = đúng ngày đó."""
    if period == "day":
        return day, day
    return period_bounds(period, day)  # type: ignore[arg-type]


async def period_bests(session: AsyncSession, day: date) -> dict[str, int]:
    """Số đo cao nhất (km/h) của ngày / tuần / tháng / năm chứa ``day`` (giờ VN); 0 = chưa có.

    Cùng điều kiện với Bảng xếp hạng: đã duyệt, hội viên Hoạt động có tài khoản liên kết – mốc máy
    đo phải vượt là hạng 1 mà hội viên nhìn thấy.
    """
    bests = {}
    for period in MARK_PERIODS:
        first, last = mark_bounds(period, day)
        in_period = (
            APPROVED,
            SpeedRecord.measured_at >= _at(first),
            SpeedRecord.measured_at < _at(last + timedelta(days=1)),
        )
        ids = set(
            await session.scalars(select(SpeedRecord.customer_id).where(*in_period).distinct())
        )
        people = await eligible(session, ids)
        best = None
        if people:
            best = await session.scalar(
                select(func.max(SpeedRecord.speed_kmh)).where(
                    *in_period, SpeedRecord.customer_id.in_(sorted(people))
                )
            )
        bests[period] = int(best or 0)
    return bests


async def add_device_record(
    session: AsyncSession,
    *,
    customer_id: int,
    speed_kmh: float,
    measured_at: datetime,
    source_ref: str,
    court_code: str | None,
    device_id: str | None,
    video_url: str | None,
    now: datetime,
) -> tuple[int | None, str | None]:
    """Ghi một số đo máy đo. Trả ``(id, None)``, hoặc ``(None, lý do)`` khi không ghi:
    ``duplicate`` (đã có ``source_ref``), ``unknown_member`` (không phải hội viên Hoạt động),
    ``speed_range`` (ngoài 50–500 km/h sau khi làm tròn), ``bad_ref``.

    ``video_url`` không hợp lệ (không phải https .mp4 / .webm / YouTube) -> ghi số đo, bỏ video.
    """
    kmh = round(speed_kmh)
    if not SPEED_RANGE[0] <= kmh <= SPEED_RANGE[1]:
        return None, "speed_range"
    if not source_ref or len(source_ref) > SOURCE_REF_MAX:
        return None, "bad_ref"
    person = (await members.room_people(session, {customer_id})).get(customer_id)
    if person is None or not person.is_active_member:
        return None, "unknown_member"
    clip = video_url if video_url and len(video_url) <= video.MAX_LEN else None
    if clip is not None and video.parse(clip) is None:
        clip = None
    record_id = await session.scalar(
        insert(SpeedRecord)
        .values(
            customer_id=customer_id,
            speed_kmh=kmh,
            measured_at=measured_at,
            court_code=court_code if court_code and len(court_code) <= COURT_CODE_MAX else None,
            device_id=device_id[:DEVICE_ID_MAX] if device_id else None,
            source_ref=source_ref,
            video_url=clip,
            video_set_at=now if clip is not None else None,
            source="device",
            status="approved",
        )
        .on_conflict_do_nothing(index_elements=[SpeedRecord.source_ref])
        .returning(SpeedRecord.id)
    )
    if record_id is None:
        return None, "duplicate"
    return record_id, None

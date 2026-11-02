"""Kỳ đang xem + kỳ trước (SRS Báo cáo & phân tích BR-003, BR-004, BR-005)."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.core.errors import AppError

DEFAULT_DAYS = 7  # Tuần: 7 ngày tới hôm nay, gồm cả hôm nay
MAX_DAYS = 90  # OQ-3: tối đa 90 ngày mỗi lần


@dataclass(frozen=True)
class Periods:
    date_from: date
    date_to: date
    prev_from: date
    prev_to: date
    # Kỳ có hôm nay: ngày cuối kỳ trước chỉ tính tới đúng giờ này (so cùng mốc)
    prev_until: datetime | None

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1


def resolve(date_from: date | None, date_to: date | None, now: datetime) -> Periods:
    """Thiếu ngày ⇒ Tuần; kiểm khoảng ngày (E-REPORT-1/2/3); tính kỳ trước cùng độ dài."""
    today = now.date()
    date_to = date_to or today
    date_from = date_from or date_to - timedelta(days=DEFAULT_DAYS - 1)
    if date_from > date_to:
        raise AppError("E-REPORT-1", "Từ ngày phải trước hoặc bằng Đến ngày.", 422)
    if date_to > today:
        raise AppError("E-REPORT-3", "Không chọn được ngày sau hôm nay.", 422)
    days = (date_to - date_from).days + 1
    if days > MAX_DAYS:
        raise AppError("E-REPORT-2", f"Chỉ xem được tối đa {MAX_DAYS} ngày mỗi lần.", 422)
    shift = timedelta(days=days)
    return Periods(
        date_from=date_from,
        date_to=date_to,
        prev_from=date_from - shift,
        prev_to=date_to - shift,
        prev_until=now - shift if date_to == today else None,
    )


def day_start(day: date, now: datetime) -> datetime:
    """0h của ``day`` theo múi giờ của ``now`` (giờ Việt Nam)."""
    return datetime.combine(day, time(), now.tzinfo)


def current_window(p: Periods, now: datetime) -> tuple[datetime, datetime]:
    """[0h Từ ngày, 0h ngày sau Đến ngày) – trọn ngày, kể cả phần còn lại của hôm nay."""
    return day_start(p.date_from, now), day_start(p.date_to + timedelta(days=1), now)


def previous_window(p: Periods, now: datetime) -> tuple[datetime, datetime]:
    end = p.prev_until or day_start(p.prev_to + timedelta(days=1), now)
    return day_start(p.prev_from, now), end

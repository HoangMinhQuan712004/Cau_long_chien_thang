"""Giờ mở cửa / khung cao điểm theo phiên bản có ngày hiệu lực (T-005 D3, D4, D6)."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.booking_engine.dto import ScheduleOut
from app.modules.booking_engine.models import ResourceSchedule

MIN_OPEN_MINUTES = 60
MIN_PEAK_MINUTES = 30


def to_minute(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


@dataclass(frozen=True)
class Hours:
    """Giờ hoạt động một ngày, tính bằng phút từ 0h."""

    open_minute: int
    close_minute: int
    peak_bands: tuple[tuple[int, int], ...]

    @classmethod
    def of(cls, row: ResourceSchedule) -> "Hours":
        return cls(
            row.open_minute,
            row.close_minute,
            tuple((to_minute(a), to_minute(b)) for a, b in row.peak_bands),
        )

    @property
    def peak_bands_hhmm(self) -> list[list[str]]:
        return [[to_hhmm(a), to_hhmm(b)] for a, b in self.peak_bands]

    def is_peak(self, minute: int) -> bool:
        return any(a <= minute < b for a, b in self.peak_bands)

    def sells(self, start_minute: int, end_minute: int) -> bool:
        return self.open_minute <= start_minute and end_minute <= self.close_minute


def validate_hours(open_time: str, close_time: str, peak_bands: list[tuple[str, str]]) -> Hours:
    """Kiểm D6.

    Đóng cửa sau mở cửa ≥ 60 phút (E-CFG-2); cao điểm ≥ 30 phút, trong giờ mở,
    không chồng nhau (E-CFG-5).

    Định dạng "HH:MM" (bội 30 phút, tối đa 24:00) đã được DTO kiểm.
    """
    o, c = to_minute(open_time), to_minute(close_time)
    if o >= 24 * 60 or c - o < MIN_OPEN_MINUTES:
        raise AppError("E-CFG-2", "Giờ đóng cửa phải sau giờ mở cửa ít nhất 1 tiếng.", 422)
    bands = sorted((to_minute(a), to_minute(b)) for a, b in peak_bands)
    for a, b in bands:
        if b - a < MIN_PEAK_MINUTES or a < o or b > c:
            raise AppError(
                "E-CFG-5",
                "Khung cao điểm phải dài ít nhất 30 phút và nằm trong giờ mở cửa "
                f"({open_time} – {close_time}).",
                422,
            )
    for (a1, b1), (a2, b2) in zip(bands, bands[1:], strict=False):
        if a2 < b1:
            raise AppError(
                "E-CFG-5",
                f"Khung {to_hhmm(a1)} – {to_hhmm(b1)} và khung {to_hhmm(a2)} – {to_hhmm(b2)} "
                "bị chồng nhau.",
                422,
            )
    return Hours(o, c, tuple(bands))


def schedule_out(row: ResourceSchedule | None) -> ScheduleOut | None:
    if row is None:
        return None
    return ScheduleOut(
        effective_from=row.effective_from,
        open_time=to_hhmm(row.open_minute),
        close_time=to_hhmm(row.close_minute),
        peak_bands=row.peak_bands,
    )


async def schedules_of(
    session: AsyncSession, tenant_id: int, resource_ids: list[int] | None = None
) -> dict[int, list[ResourceSchedule]]:
    """Mọi phiên bản lịch theo tài nguyên, sắp tăng dần ``effective_from``."""
    stmt = (
        select(ResourceSchedule)
        .where(ResourceSchedule.tenant_id == tenant_id)
        .order_by(ResourceSchedule.resource_id, ResourceSchedule.effective_from)
    )
    if resource_ids is not None:
        stmt = stmt.where(ResourceSchedule.resource_id.in_(resource_ids))
    result: dict[int, list[ResourceSchedule]] = {}
    for row in await session.scalars(stmt):
        result.setdefault(row.resource_id, []).append(row)
    return result


def effective_on(versions: list[ResourceSchedule], day: date) -> ResourceSchedule | None:
    """Lịch của ngày D = bản có ``effective_from`` lớn nhất ≤ D."""
    current = None
    for row in versions:
        if row.effective_from <= day:
            current = row
        else:
            break
    return current


def pending_after(versions: list[ResourceSchedule], day: date) -> ResourceSchedule | None:
    """Bản lịch chờ áp dụng gần nhất (``effective_from`` > ngày)."""
    return next((row for row in versions if row.effective_from > day), None)

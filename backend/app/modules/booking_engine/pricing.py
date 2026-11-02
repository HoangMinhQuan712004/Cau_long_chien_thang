"""Loại ngày và giá khung (T-005 D1, D2, SRS BR-009).

- Loại ngày: thuộc ngày đặc biệt -> ``holiday``; T7, CN -> ``weekend``; còn lại ``weekday``.
- Giá 1 khung 1 giờ = tổng 2 nửa giờ; mỗi nửa = ``price_per_hour / 2`` theo band của nửa đó
  (cao điểm nếu nửa giờ nằm trong ``peak_bands`` của tài nguyên theo lịch hiệu lực ngày đó).
- Tiền là số nguyên VND: khung có 2 nửa khác band và tổng lẻ được làm tròn lên
  (``(a + b + 1) // 2``).
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import PriceRule, SpecialDay
from app.modules.booking_engine.schedules import Hours

HALF = 30
BAND_LABELS = {"offpeak": "Thấp điểm", "partial": "Một phần cao điểm", "peak": "Cao điểm"}


async def special_day_on(session: AsyncSession, tenant_id: int, day: date) -> SpecialDay | None:
    return await session.scalar(
        select(SpecialDay).where(
            SpecialDay.tenant_id == tenant_id,
            SpecialDay.date_from <= day,
            SpecialDay.date_to >= day,
        )
    )


def day_type_of(day: date, is_special: bool) -> str:
    if is_special:
        return "holiday"
    return "weekend" if day.weekday() >= 5 else "weekday"


def slot_price(hours: Hours, start_minute: int, prices: dict[str, int]) -> tuple[str, int]:
    """Giá khung 1 giờ bắt đầu ở ``start_minute``. ``prices`` = {"offpeak": …, "peak": …}.

    Trả (band khung, giá): band ``partial`` khi đúng một nửa là cao điểm.
    """
    halves = [hours.is_peak(start_minute), hours.is_peak(start_minute + HALF)]
    total_half_prices = sum(prices["peak" if p else "offpeak"] for p in halves)
    peak_count = sum(halves)
    band = "peak" if peak_count == 2 else "partial" if peak_count == 1 else "offpeak"
    return band, (total_half_prices + 1) // 2


async def prices_for_day(session: AsyncSession, tenant_id: int, day: date) -> dict[int, dict]:
    """{resource_type_id: {"offpeak": giá, "peak": giá}} theo loại ngày của ``day``."""
    special = await special_day_on(session, tenant_id, day)
    day_type = day_type_of(day, special is not None)
    prices: dict[int, dict] = defaultdict(dict)
    for p in await session.scalars(
        select(PriceRule).where(PriceRule.tenant_id == tenant_id, PriceRule.day_type == day_type)
    ):
        prices[p.resource_type_id][p.band] = p.price_per_hour
    return prices


def hour_price(hours: Hours | None, hour: int, prices: dict[str, int]) -> tuple[str, int] | None:
    """(band, giá) của ô 1 giờ bắt đầu lúc ``hour``; ``None`` khi sân không bán ô này hoặc bảng
    giá thiếu band cần cho ô (ô không bán được)."""
    if hours is None or not hours.sells(hour * 60, hour * 60 + 60):
        return None
    needed = {"peak" if hours.is_peak(m) else "offpeak" for m in (hour * 60, hour * 60 + HALF)}
    if not needed <= prices.keys():
        return None
    return slot_price(hours, hour * 60, prices)

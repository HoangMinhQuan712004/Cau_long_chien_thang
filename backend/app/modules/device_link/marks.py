"""Mốc kỷ lục từng kỳ trong Redis – máy đo chỉ đọc, server giữ cho đúng.

Bốn khóa (km/h): ``{prefix}:day:YYYY-MM-DD``, ``:week:GGGG-Www`` (tuần ISO), ``:month:YYYY-MM``,
``:year:YYYY``, theo giờ ``settings.TIMEZONE``. Khóa thiếu = "mốc chưa biết": máy đo không xét kỷ
lục của kỳ đó, nên khóa của kỳ sắp tới được tạo sẵn (= 0) trước khi kỳ bắt đầu.
"""

from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.records import api as records

AHEAD = timedelta(minutes=10)  # tạo sẵn khóa của kỳ bắt đầu trong khoảng này
KEEP = timedelta(days=2)  # khóa sống thêm sau khi kỳ kết thúc


def mark_keys(local: datetime, prefix: str) -> dict[str, str]:
    """Bốn khóa của các kỳ chứa ``local`` (đã ở giờ VN)."""
    iso = local.isocalendar()
    return {
        "day": f"{prefix}:day:{local:%Y-%m-%d}",
        "week": f"{prefix}:week:{iso.year:04d}-W{iso.week:02d}",
        "month": f"{prefix}:month:{local:%Y-%m}",
        "year": f"{prefix}:year:{local:%Y}",
    }


def _expire_at(period: str, local: datetime) -> int:
    _, last = records.mark_bounds(period, local.date())
    end = datetime.combine(last + timedelta(days=1), time(), settings.tz)
    return int((end + KEEP).timestamp())


async def refresh(session: AsyncSession, redis: Any, now: datetime) -> dict[str, int]:
    """Ghi mốc của bốn kỳ hiện tại = số đo cao nhất đã duyệt của kỳ (0: chưa có)."""
    prefix = settings.RECORD_MARK_PREFIX
    local = now.astimezone(settings.tz)
    bests = await records.period_bests(session, local.date())
    keys = mark_keys(local, prefix)
    for period, key in keys.items():
        await redis.set(key, str(bests[period]), exat=_expire_at(period, local))
    soon = local + AHEAD
    for period, key in mark_keys(soon, prefix).items():
        if key != keys[period]:
            await redis.set(key, "0", nx=True, exat=_expire_at(period, soon))
    return bests

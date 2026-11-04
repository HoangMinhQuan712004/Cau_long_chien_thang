"""Số đo tốc độ mẫu cho link dev (T-030 → T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Dấu mẫu: ``source_ref`` bắt đầu bằng ``demo:`` (+ ``device_id = "demo"``). Không commit.
"""

import secrets
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.records.models import SpeedRecord

DEMO_PREFIX = "demo:"


def _starts(now: datetime) -> tuple[datetime, datetime]:
    """(đầu tuần T2, đầu tháng) theo giờ VN."""
    local = now.astimezone(settings.tz)
    monday = local.date() - timedelta(days=local.weekday())
    week = datetime.combine(monday, time(), settings.tz)
    month = datetime.combine(local.date().replace(day=1), time(), settings.tz)
    return week, month


async def seed_speeds(session: AsyncSession, customer_ids: list[int], now: datetime) -> int:
    """Số đo 180–330 km/h cho mỗi người: trong tuần này, tháng này, 35–200 ngày trước và năm trước.

    Hai người đầu có **cùng** 300 km/h – cao nhất tuần / tháng này (còn lại ≤ 299) – người thứ hai
    đạt sau, để thấy quy tắc "bằng nhau thì ai đạt trước xếp trên".
    """
    rng = secrets.SystemRandom()
    week, month = _starts(now)
    rows: list[SpeedRecord] = []
    first_at: datetime | None = None
    for i, cid in enumerate(customer_ids):
        moments = [
            week + (now - week) * rng.uniform(0.1, 0.5),  # tuần này
            month + (now - month) * rng.random(),  # tháng này
            now - timedelta(days=rng.randint(35, 200)),  # trước tháng này (năm nay / năm trước)
            now - timedelta(days=rng.randint(370, 500)),  # năm trước
        ]
        for k, at in enumerate(moments):
            if k == 0 and i < 2:
                kmh = 300
                if i == 0:
                    first_at = at
                elif first_at is not None:  # bằng tốc độ, đạt sau
                    at = first_at + (now - first_at) / 2
            elif k in (0, 1):  # tuần / tháng này: dưới cặp đồng hạng 300
                kmh = rng.randint(180, 299)
            else:
                kmh = rng.randint(180, 330)
            rows.append(
                SpeedRecord(
                    customer_id=cid,
                    speed_kmh=kmh,
                    measured_at=at.astimezone(UTC),
                    device_id="demo",
                    source_ref=f"{DEMO_PREFIX}{cid}:{k}",
                )
            )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_breaks(
    session: AsyncSession,
    customer_ids: list[int],
    now: datetime,
    video_urls: list[str],
) -> int:
    """3 lần phá kỷ lục cụm gần đây (331 → 335 → 340 km/h, cao hơn mọi số đo ngẫu nhiên ≤ 330)
    cho khối "Kỷ lục mới" (T-036); gắn lần lượt ``video_urls`` (T-046, nếu có) vào các lần phá."""
    rows = []
    for k, (cid, kmh) in enumerate(zip(customer_ids, (331, 335, 340), strict=False)):
        rows.append(
            SpeedRecord(
                customer_id=cid,
                speed_kmh=kmh,
                measured_at=(now - timedelta(days=3 - k, hours=1)).astimezone(UTC),
                device_id="demo",
                video_url=video_urls[k] if k < len(video_urls) else None,
                source_ref=f"{DEMO_PREFIX}break:{cid}:{k}",
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def purge_demo(session: AsyncSession) -> int:
    result = await session.execute(
        delete(SpeedRecord).where(SpeedRecord.source_ref.startswith(DEMO_PREFIX))
    )
    return result.rowcount or 0

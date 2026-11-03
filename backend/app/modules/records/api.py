"""Mặt tiền của module Kỷ lục – module khác (member_area) chỉ gọi các hàm ở đây."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records import service
from app.modules.records.schemas import Period, SpeedRanking
from app.modules.records.service import RecordBreak

__all__ = [
    "RecordBreak",
    "club_record_breaks",
    "month_best",
    "record_kmh",
    "speed_ranking",
]


async def record_kmh(session: AsyncSession, customer_id: int) -> int | None:
    """Kỷ lục tốc độ cú đập mọi thời gian của hội viên (km/h); None khi chưa có số đo."""
    return await service.record_kmh(session, customer_id)


async def month_best(session: AsyncSession, customer_id: int, day: date) -> int | None:
    """Số đo cao nhất của hội viên trong tháng chứa ``day`` (giờ VN); None khi chưa có."""
    return await service.month_best(session, customer_id, day)


async def speed_ranking(
    session: AsyncSession, customer_id: int, period: Period, day: date
) -> SpeedRanking:
    """Bảng xếp hạng tốc độ như ``GET /member-area/speed-ranking`` (ẩn danh, chỉ hội viên đủ
    điều kiện)."""
    return await service.ranking(session, customer_id, period, day)


async def club_record_breaks(
    session: AsyncSession, viewer_id: int, limit: int = 3
) -> list[RecordBreak]:
    """Các lần phá kỷ lục toàn cụm gần nhất (mới nhất trước, ``is_current`` = đang giữ kỷ lục)."""
    return await service.club_record_breaks(session, viewer_id, limit)

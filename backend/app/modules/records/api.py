"""Mặt tiền của module Kỷ lục – module khác (member_area) chỉ gọi các hàm ở đây."""

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records import demo, service, video
from app.modules.records.schemas import Period, SpeedRanking, VideoOut
from app.modules.records.service import RecordBreak

__all__ = [
    "RecordBreak",
    "club_record_breaks",
    "month_best",
    "purge_demo",
    "record_kmh",
    "seed_demo_breaks",
    "seed_demo_speeds",
    "speed_ranking",
    "video_of",
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


async def seed_demo_speeds(session: AsyncSession, customer_ids: list[int], now: datetime) -> int:
    """Số đo mẫu (source_ref "demo:") – tuần / tháng / năm nay và năm trước. Không commit."""
    return await demo.seed_speeds(session, customer_ids, now)


async def seed_demo_breaks(
    session: AsyncSession, customer_ids: list[int], now: datetime, video_urls: list[str]
) -> int:
    """3 lần phá kỷ lục cụm mẫu, gắn link video (nếu có). Không commit."""
    return await demo.seed_breaks(session, customer_ids, now, video_urls)


async def purge_demo(session: AsyncSession) -> int:
    return await demo.purge_demo(session)


def video_of(url: str | None) -> VideoOut | None:
    """Link video đã lưu -> ``{kind, url, embed_url, thumbnail_url}`` cho FE (T-046)."""
    return video.parse(url)

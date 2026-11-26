"""Mặt tiền của module Kỷ lục – module khác (member_area) chỉ gọi các hàm ở đây."""

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records import demo, device, live, service, video
from app.modules.records.schemas import LiveRecord, Period, SpeedRanking, VideoOut
from app.modules.records.service import RecordBreak

__all__ = [
    "MARK_PERIODS",
    "RecordBreak",
    "add_device_record",
    "attach_device_video",
    "live_card",
    "club_record_breaks",
    "mark_bounds",
    "month_best",
    "publish_live",
    "period_bests",
    "purge_demo",
    "record_kmh",
    "reset_device_records",
    "seed_demo_breaks",
    "seed_demo_speeds",
    "speed_ranking",
    "video_of",
]


# Máy đo tốc độ (giai đoạn B – module device_link): ghi số đo, mốc kỷ lục từng kỳ
MARK_PERIODS = device.MARK_PERIODS
add_device_record = device.add_device_record
attach_device_video = device.attach_device_video
reset_device_records = device.reset_device_records
# Tin trực tiếp (popup chúc mừng): worker phát ``record.new`` / ``record.video`` lên Redis
publish_live = live.publish
mark_bounds = device.mark_bounds
period_bests = device.period_bests


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


async def live_card(session: AsyncSession, record_id: int, viewer_id: int) -> LiveRecord | None:
    """Một số đo cho tin trực tiếp (popup chúc mừng) – ẩn danh như Bảng xếp hạng; None khi số đo
    không còn / người đo không đủ điều kiện."""
    return await service.live_card(session, record_id, viewer_id)


def video_of(url: str | None) -> VideoOut | None:
    """Link video đã lưu -> ``{kind, url, embed_url, thumbnail_url}`` cho FE (T-046)."""
    return video.parse(url)

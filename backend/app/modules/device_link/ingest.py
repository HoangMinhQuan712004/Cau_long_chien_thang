"""Nhận tin từ máy đo: cú đập phá mốc (``shot.record``) và trạng thái sân (``status``).

Cú đập chỉ thành số đo khi máy đo nêu đúng **một** người đánh (``player_id``). Không có id người
đánh (đánh đôi khi máy đo chưa nhận ra ai đánh) -> không ghi nhận gì (người dùng chốt 23/11). Tin
của trận thử (``test: true``) luôn bỏ qua.
"""

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.device_link import messages
from app.modules.device_link.models import DeviceCourt
from app.modules.records import api as records

logger = logging.getLogger(__name__)

DEVICE_ID = "shuttletrack"
REF_PREFIX = "st:"

RECORDED = "recorded"


async def record(session: AsyncSession, court: str, raw: bytes, now: datetime) -> str:
    """Xử lý một ``shot.record``; trả kết quả: ``recorded`` hoặc lý do bỏ qua. Commit."""
    try:
        shot = messages.parse_record(raw)
    except messages.BadMessage as exc:
        logger.warning("Device link: unusable record from court %s (%s)", court, exc)
        return "bad_message"
    if shot.test:
        return "test"
    if shot.player_id is None:
        logger.info("Device link: record %s on court %s names no player", shot.shot_ref, court)
        return "no_player"
    if not shot.player_id.isdecimal() or len(shot.player_id) > 9:
        logger.warning("Device link: record %s has an unknown player id", shot.shot_ref)
        return "unknown_member"
    record_id, reason = await records.add_device_record(
        session,
        customer_id=int(shot.player_id),
        speed_kmh=shot.speed_kmh,
        measured_at=shot.impact_at,
        source_ref=f"{REF_PREFIX}{shot.shot_ref}",
        court_code=court,
        device_id=DEVICE_ID,
        video_url=shot.clip_url,
        now=now,
    )
    await session.commit()
    if record_id is None:
        level = logging.DEBUG if reason == "duplicate" else logging.WARNING
        logger.log(level, "Device link: record %s not saved (%s)", shot.shot_ref, reason)
        return reason or "skipped"
    logger.info(
        "Device link: record %s saved as speed record %s (court %s, %.1f km/h)",
        shot.shot_ref,
        record_id,
        court,
        shot.speed_kmh,
    )
    return RECORDED


async def status(session: AsyncSession, court: str, raw: bytes, now: datetime) -> bool:
    """Lưu trạng thái sân máy đo báo về; trả True khi đã lưu. Commit."""
    try:
        seen = messages.parse_status(raw)
    except messages.BadMessage as exc:
        logger.warning("Device link: unusable status from court %s (%s)", court, exc)
        return False
    if seen.test:
        return False
    values = {
        "app_online": seen.online,
        "app_state": seen.state,
        "app_error": seen.error,
        "app_match_ref": seen.match_ref,
        "app_seen_at": now,
    }
    await session.execute(
        insert(DeviceCourt)
        .values(court_code=court, **values)
        .on_conflict_do_update(index_elements=[DeviceCourt.court_code], set_=values)
    )
    await session.commit()
    logger.info(
        "Device link: court %s is %s (state %s, match %s, error %s)",
        court,
        "online" if seen.online else "offline",
        seen.state,
        seen.match_ref,
        seen.error,
    )
    return True

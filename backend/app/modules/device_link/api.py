"""Mặt tiền nối máy đo tốc độ ShuttleTrack – worker gọi (``app.workers.worker``).

Tắt khi ``MQTT_HOST`` trống. Chiều đi: lệnh trận theo phòng chơi (``sync_courts``) và mốc kỷ lục
từng kỳ trong Redis (``refresh_marks``). Chiều về: cú đập phá mốc thành số đo nguồn "Máy đo", và
trạng thái sân phía máy đo.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.device_link import ingest, marks, messages, sync
from app.modules.device_link.link import Link

logger = logging.getLogger(__name__)

__all__ = ["Link", "refresh_marks", "start", "sync_courts"]


def start(redis: Any) -> Link | None:
    """Mở kết nối tới broker (không chặn; tự nối lại). None khi tắt."""
    if not settings.device_link_enabled:
        return None

    async def handle(name: str, payload: bytes) -> None:
        prefix = settings.MQTT_TOPIC_PREFIX
        court = messages.court_of(prefix, name, "record")
        if court is not None:
            async with SessionLocal() as session:
                outcome = await ingest.record(session, court, payload, datetime.now(UTC))
                if outcome == ingest.RECORDED:  # mốc mới có ngay, không chờ lượt ghi định kỳ
                    await marks.refresh(session, redis, datetime.now(UTC))
            return
        court = messages.court_of(prefix, name, "status")
        if court is not None and payload:
            async with SessionLocal() as session:
                await ingest.status(session, court, payload, datetime.now(UTC))

    link = Link(handle)
    link.start()
    return link


async def sync_courts(link: Link | None) -> int:
    """Phát lệnh trận còn thiếu cho từng sân; 0 khi tắt / chưa nối."""
    if link is None or not link.connected:
        return 0
    async with SessionLocal() as session:
        return await sync.sync_courts(session, link.publish)


async def refresh_marks(redis: Any) -> dict[str, int]:
    """Ghi mốc kỷ lục ngày / tuần / tháng / năm vào Redis; {} khi tắt."""
    if not settings.device_link_enabled:
        return {}
    async with SessionLocal() as session:
        return await marks.refresh(session, redis, datetime.now(UTC))

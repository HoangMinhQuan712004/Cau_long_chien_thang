"""Phát lệnh trận cho máy đo: trạng thái mong muốn suy từ DB, so với lệnh đã phát của từng sân.

Sân có trận ``playing`` -> ``match.start`` (retained); trận hết (lưu tỉ số, phòng đóng, booking
hủy, booking đổi sân) -> ``match.stop`` của đúng trận đã phát. Chỉ ghi nhận "đã phát" khi broker
xác nhận (QoS 1); chưa xác nhận thì lần chạy sau phát lại – máy đo nhận trùng không sao (cùng
``match_id``: chỉ thay vị trí; ``match.stop`` của trận không chạy: bỏ qua).
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.device_link import messages
from app.modules.device_link.models import DeviceCourt
from app.modules.play_rooms import api as rooms

logger = logging.getLogger(__name__)

Publish = Callable[[str, dict, bool], Awaitable[bool]]


async def _mark_sent(session: AsyncSession, court: str, body: dict, state: str) -> None:
    values = {
        "match_ref": body["match_id"],
        "match_state": state,
        "players": body.get("players"),
        "sent_at": datetime.now(UTC),
    }
    await session.execute(
        insert(DeviceCourt)
        .values(court_code=court, **values)
        .on_conflict_do_update(index_elements=[DeviceCourt.court_code], set_=values)
    )


async def sync_courts(session: AsyncSession, publish: Publish) -> int:
    """Phát các lệnh còn thiếu; trả số lệnh broker đã xác nhận. Commit."""
    prefix = settings.MQTT_TOPIC_PREFIX
    wanted = {}
    for match in await rooms.playing_matches(session):
        if messages.COURT.fullmatch(match.court_code):
            wanted[match.court_code] = match
        else:
            logger.warning("Device link: court code %r cannot be a topic", match.court_code)
    sent = {row.court_code: row for row in await session.scalars(select(DeviceCourt))}
    done = 0
    now = datetime.now(UTC)
    for court in sorted(wanted.keys() | sent.keys()):
        match, row = wanted.get(court), sent.get(court)
        if match is not None:
            body = messages.start_message(match, now)
            if (
                row is not None
                and row.match_state == "started"
                and row.match_ref == body["match_id"]
                and row.players == body["players"]
            ):
                continue
            state = "started"
        elif row is not None and row.match_state == "started" and row.match_ref:
            body, state = messages.stop_message(row.match_ref, now), "stopped"
        else:
            continue
        if not await publish(messages.topic(prefix, court, "match"), body, True):
            logger.warning("Device link: %s for court %s not confirmed", body["type"], court)
            continue
        await _mark_sent(session, court, body, state)
        logger.info("Device link: %s %s sent to court %s", body["type"], body["match_id"], court)
        done += 1
    await session.commit()
    return done

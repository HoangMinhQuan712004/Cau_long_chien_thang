"""Tin trực tiếp về số đo máy đo (popup chúc mừng trên Bảng xếp hạng).

Worker (device_link) phát lên kênh Redis ``CHANNEL`` một tin rất gọn ``{"event", "record_id"}``:
``record.new`` khi số đo máy đo vừa ghi, ``record.video`` khi video cắt xong được gắn vào. Không
mang tên / id hội viên: mỗi kết nối websocket tự đọc số đo và ẩn danh theo người xem
(``service.live_card``), như Bảng xếp hạng.

``GET /api/v1/member-area/records/live`` (websocket): chỉ hội viên đã đăng nhập (cookie
``access_token``), Origin thuộc ``ALLOWED_ORIGINS``. Server -> trình duyệt:
``{"event": "record.new" | "record.video", "record": LiveRecord}``; trình duyệt không gửi gì.
"""

import asyncio
import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.middleware import origin_allowed
from app.modules.auth import api as auth
from app.modules.records import service

logger = logging.getLogger(__name__)

CHANNEL = "records:live"
EVENTS = ("record.new", "record.video")
# Đóng khi chưa đăng nhập / không phải hội viên: FE làm mới phiên rồi nối lại
CLOSE_UNAUTHORIZED = 4401
CLOSE_ORIGIN = 4403
PING_S = 25.0

router = APIRouter(prefix="/member-area", tags=["member-area"])


async def publish(redis: Any, event: str, record_id: int) -> None:
    """Phát một tin; Redis lỗi -> chỉ log tên lỗi (popup là phụ, số đo đã lưu)."""
    try:
        await redis.publish(CHANNEL, json.dumps({"event": event, "record_id": record_id}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live records: publish failed (%s)", type(exc).__name__)


def _parse(data: Any) -> tuple[str, int] | None:
    try:
        msg = json.loads(data)
        event, record_id = msg["event"], msg["record_id"]
    except (ValueError, TypeError, KeyError):
        return None
    if event not in EVENTS or not isinstance(record_id, int):
        return None
    return event, record_id


async def _viewer(ws: WebSocket) -> int | None:
    token = ws.cookies.get(auth.ACCESS_COOKIE)
    if not token:
        return None
    async with SessionLocal() as session:
        member = await auth.member_of_token(session, token)
    return member.customer_id if member is not None else None


@router.websocket("/records/live")
async def records_live(ws: WebSocket) -> None:
    headers = {k.lower(): v for k, v in ws.scope.get("headers", [])}
    if not origin_allowed(headers):
        await ws.close(code=CLOSE_ORIGIN)  # trước accept: bắt tay bị từ chối (403)
        return
    viewer = await _viewer(ws)
    await ws.accept()
    if viewer is None:  # sau accept để trình duyệt nhận mã 4401 (làm mới phiên rồi nối lại)
        await ws.close(code=CLOSE_UNAUTHORIZED)
        return
    client = aioredis.from_url(settings.REDIS_URL)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(CHANNEL)
        receiver = asyncio.create_task(_drain(ws))
        quiet_since = time.monotonic()
        try:
            while not receiver.done():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:  # hết 1 s, hoặc tin xác nhận subscribe
                    if time.monotonic() - quiet_since >= PING_S:
                        await ws.send_json({"event": "ping"})
                        quiet_since = time.monotonic()
                    continue
                parsed = _parse(msg.get("data"))
                if parsed is None:
                    continue
                event, record_id = parsed
                async with SessionLocal() as session:
                    card = await service.live_card(session, record_id, viewer)
                if card is not None:
                    await ws.send_json({"event": event, "record": card.model_dump(mode="json")})
                    quiet_since = time.monotonic()
        finally:
            receiver.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live records: connection ended (%s)", type(exc).__name__)
    finally:
        try:
            await pubsub.aclose()
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


async def _drain(ws: WebSocket) -> None:
    """Đọc (và bỏ) mọi thứ trình duyệt gửi; trả về khi trình duyệt đóng kết nối."""
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        return

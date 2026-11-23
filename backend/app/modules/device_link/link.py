"""Kết nối MQTT tới broker của máy đo – chỉ worker mở (một kết nối, một client id).

paho chạy luồng mạng riêng (tự nối lại 1–60 giây); tin đến được chuyển sang vòng lặp asyncio của
worker và xử lý lần lượt. Phiên giữ lại trên broker (``clean_session=False``) + QoS 1 + xác nhận
tay: tin ``record`` gửi lúc worker tắt được broker giữ và giao lại; tin chỉ được xác nhận sau khi
đã xử lý xong (ghi DB). Không log mật khẩu; lỗi kết nối chỉ ghi mã lý do.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.modules.device_link import messages

logger = logging.getLogger(__name__)

QOS = 1
KEEPALIVE = 30
PUBLISH_TIMEOUT = 5.0
RETRY_DELAYS = (1.0, 5.0, 15.0)  # xử lý một tin lỗi (DB chập chờn) -> thử lại, rồi mới bỏ

Handler = Callable[[str, bytes], Awaitable[None]]


def _new_client() -> Any:
    import paho.mqtt.client as mqtt  # import trễ: API không cần gói này

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=settings.MQTT_CLIENT_ID,
        clean_session=False,
        manual_ack=True,
    )
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or None)
    if settings.MQTT_TLS:
        client.tls_set()
    client.reconnect_delay_set(1, 60)
    return client


class Link:
    def __init__(self, handler: Handler, client: Any = None) -> None:
        self._handler = handler
        self._client = client if client is not None else _new_client()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbox: asyncio.Queue[Any] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._connected = False
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._consume())
        self._client.connect_async(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=KEEPALIVE)
        self._client.loop_start()
        logger.info(
            "Device link: connecting to %s:%s as %s",
            settings.MQTT_HOST,
            settings.MQTT_PORT,
            settings.MQTT_CLIENT_ID,
        )

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._connected = False  # ngắt chủ động: không cảnh báo "disconnected"
        try:
            self._client.disconnect()
        finally:
            await asyncio.to_thread(self._client.loop_stop)

    # -- luồng mạng của paho ------------------------------------------------------------------
    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason: Any, props: Any) -> None:
        if getattr(reason, "is_failure", False):
            logger.warning("Device link: broker refused the connection (%s)", reason)
            return
        prefix = settings.MQTT_TOPIC_PREFIX
        client.subscribe(
            [
                (messages.topic_filter(prefix, "record"), QOS),
                (messages.topic_filter(prefix, "status"), QOS),
            ]
        )
        self._connected = True
        logger.info("Device link: connected")

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason: Any, p: Any) -> None:
        if self._connected:
            logger.warning("Device link: disconnected (%s)", reason)
        self._connected = False

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._inbox.put_nowait, message)

    # -- vòng lặp asyncio của worker -----------------------------------------------------------
    async def _consume(self) -> None:
        while True:
            message = await self._inbox.get()
            for delay in (*RETRY_DELAYS, None):
                try:
                    await self._handler(message.topic, message.payload)
                    break
                except Exception:
                    logger.exception("Device link: handling a message on %s failed", message.topic)
                    if delay is None:
                        logger.error("Device link: message on %s dropped", message.topic)
                        break
                    await asyncio.sleep(delay)
            self._client.ack(message.mid, message.qos)

    async def publish(self, name: str, body: dict, retain: bool) -> bool:
        """Phát QoS 1 và chờ broker xác nhận; False khi chưa nối hoặc chưa được xác nhận."""
        if not self._connected:
            return False
        payload = json.dumps(body, separators=(",", ":"))
        info = self._client.publish(name, payload, qos=QOS, retain=retain)
        if info.rc != 0:
            return False
        try:
            await asyncio.to_thread(info.wait_for_publish, PUBLISH_TIMEOUT)
            return bool(info.is_published())
        except (ValueError, RuntimeError):
            return False

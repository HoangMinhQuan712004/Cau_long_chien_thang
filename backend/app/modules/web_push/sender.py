"""Chỗ nối gửi push (T-076 Q1). Mặc định gửi thật (VAPID + aes128gcm); test thay bằng bản giả
``app.modules.web_push.testing``.

Gửi thật: ``pywebpush`` mã hóa nội dung, ``py_vapid`` ký JWT; request đi bằng ``httpx`` **không
theo chuyển hướng** (3xx = lỗi) và có timeout. Không log endpoint đầy đủ hay khóa.
"""

import json
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx

from app.core.config import settings
from app.modules.web_push import endpoints

TIMEOUT_SECONDS = 10.0
VAPID_EXPIRY_SECONDS = 12 * 3600


@dataclass(frozen=True)
class Message:
    """Nội dung gửi tới service worker (JSON): không SĐT, không tên người."""

    title: str
    body: str
    url: str  # đường dẫn cùng domain, bắt đầu bằng "/"
    tag: str | None = None  # thông báo cùng tag thay cho nhau trên máy
    ttl: int = 3600  # giây dịch vụ push giữ khi máy đang tắt

    def payload(self) -> bytes:
        data = {k: v for k, v in asdict(self).items() if k != "ttl" and v is not None}
        return json.dumps(data, ensure_ascii=False).encode()


@dataclass(frozen=True)
class Target:
    subscription_id: int
    user_id: int
    endpoint: str
    p256dh: str
    auth: str


@dataclass(frozen=True)
class Result:
    """``status`` = mã HTTP của dịch vụ push; None khi không có phản hồi (``error``)."""

    status: int | None
    error: str | None = None  # timeout | network | invalid

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def gone(self) -> bool:
        """Thiết bị đã hủy đăng ký -> xóa dòng."""
        return self.status in (404, 410)


class Sender(Protocol):
    async def send(self, target: Target, message: Message) -> Result: ...


class WebPushSender:
    """Gửi thật. Chỉ dùng khi đã cấu hình VAPID (``settings.push_enabled``).

    ``transport``: chỉ cho test (``httpx.MockTransport``) – không ra mạng.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def send(self, target: Target, message: Message) -> Result:
        # Kiểm lại trước khi gửi: dòng cũ / dữ liệu hỏng không bao giờ làm server gọi host lạ
        if endpoints.host_of(target.endpoint) is None:
            return Result(None, "invalid")
        try:
            body, headers = _encrypt(target, message)
        except Exception:
            return Result(None, "invalid")  # khóa thiết bị hỏng
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=TIMEOUT_SECONDS,
                trust_env=False,
                transport=self._transport,
            ) as client:
                r = await client.post(target.endpoint, content=body, headers=headers)
        except httpx.TimeoutException:
            return Result(None, "timeout")
        except httpx.HTTPError:
            return Result(None, "network")
        return Result(r.status_code)


def _encrypt(target: Target, message: Message) -> tuple[bytes, dict[str, str]]:
    from py_vapid import Vapid
    from pywebpush import WebPusher

    info = {"endpoint": target.endpoint, "keys": {"p256dh": target.p256dh, "auth": target.auth}}
    encoded = WebPusher(info).encode(message.payload(), "aes128gcm")
    parts = httpx.URL(target.endpoint)
    claims = {
        "sub": settings.vapid_subject,
        "aud": f"{parts.scheme}://{parts.host}",
        "exp": int(time.time()) + VAPID_EXPIRY_SECONDS,
    }
    headers = dict(Vapid.from_string(private_key=settings.VAPID_PRIVATE_KEY).sign(claims))
    headers.update(
        {
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(message.ttl),
            "Urgency": "high",
        }
    )
    return encoded["body"], headers


_sender: Sender | None = None


def get_sender() -> Sender:
    global _sender
    if _sender is None:
        _sender = WebPushSender()
    return _sender


def set_sender(sender: Sender | None) -> None:
    """Test / CI: ``set_sender(FakePushService())``; None -> trở lại gửi thật."""
    global _sender
    _sender = sender

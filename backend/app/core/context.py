"""Ngữ cảnh request (request-id, IP client) dùng cho log và nhật ký thao tác (ADR-004 B7).

Middleware ``RequestContextMiddleware`` đặt giá trị vào contextvars ở đầu mỗi request;
mọi code chạy trong request (dependency, service, audit) đọc qua ``request_id()`` / ``client_ip()``.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def request_id() -> str | None:
    return _request_id.get()


def client_ip() -> str | None:
    return _client_ip.get()


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


def resolve_client_ip(scope: Scope) -> str | None:
    """IP thật của client.

    Mỗi proxy tin cậy (có ghi XFF) nối IP nó nhận được vào cuối ``X-Forwarded-For``. Với N proxy
    như vậy, IP client = phần tử thứ N tính từ cuối; giá trị client tự gửi nằm phía trước nên không
    giả mạo được. Prod/dev: Caddy -> Next -> API, chỉ Caddy ghi XFF -> N = 1.
    """
    direct = scope.get("client")
    direct_ip = direct[0] if direct else None
    hops = settings.TRUSTED_PROXY_COUNT
    if hops <= 0:
        return direct_ip
    xff = _header(scope, b"x-forwarded-for")
    if not xff:
        return direct_ip
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    # Ít phần tử hơn số proxy: request không đi đủ chuỗi proxy -> không tin XFF
    return parts[-hops] if len(parts) >= hops else direct_ip


class RequestContextMiddleware:
    """Sinh / nhận ``X-Request-ID``, xác định IP client; trả lại ``X-Request-ID`` trong response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        rid = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        t1 = _request_id.set(rid)
        t2 = _client_ip.set(resolve_client_ip(scope))

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _request_id.reset(t1)
            _client_ip.reset(t2)


class RequestIdLogFilter(logging.Filter):
    """Gắn ``request_id`` vào mọi bản ghi log (``-`` khi ngoài request)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        return True


class StripQueryLogFilter(logging.Filter):
    """Access log của uvicorn: bỏ query string (có thể chứa SĐT, mã tìm kiếm)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
        )
    for handler in root.handlers:
        if not any(isinstance(f, RequestIdLogFilter) for f in handler.filters):
            handler.addFilter(RequestIdLogFilter())
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StripQueryLogFilter) for f in access.filters):
        access.addFilter(StripQueryLogFilter())

"""Middleware bảo mật mức HTTP (ADR-004 S4, S18).

- ``OriginCheckMiddleware``: request ghi (không phải GET/HEAD/OPTIONS) mang cookie phiên phải có
  ``Origin`` (hoặc ``Referer``) thuộc ``ALLOWED_ORIGINS`` -> ngược lại 403 ``E-SEC-1``.
- ``BodyLimitMiddleware``: body > ``MAX_BODY_BYTES`` -> 413 ``E-SEC-6``.
"""

from urllib.parse import urlsplit

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.errors import AppError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Cookie xác thực của trình duyệt (app.modules.auth.deps)
SESSION_COOKIES = ("access_token", "refresh_token", "admin_session")
# Đường dẫn công khai nhận request từ bên thứ ba (webhook cổng thanh toán – xác thực bằng HMAC)
ORIGIN_EXEMPT_PATHS: set[str] = {f"{settings.API_PREFIX}/payments/sepay/webhook"}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, "message": message}}, status_code=status)


def _headers(scope: Scope) -> dict[bytes, bytes]:
    return dict(scope.get("headers", []))


def _origin_of(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def origin_allowed(headers: dict[bytes, bytes]) -> bool:
    """Origin (hoặc Referer khi thiếu Origin) thuộc ``ALLOWED_ORIGINS``."""
    origin = headers.get(b"origin", b"").decode("latin-1").strip()
    if not origin or origin == "null":
        referer = headers.get(b"referer", b"").decode("latin-1").strip()
        origin = _origin_of(referer) if referer else None
    allowed = {o.rstrip("/").lower() for o in settings.ALLOWED_ORIGINS}
    return bool(origin) and origin.rstrip("/").lower() in allowed


def _has_session_cookie(cookie_header: str) -> bool:
    for item in cookie_header.split(";"):
        name = item.split("=", 1)[0].strip()
        if name in SESSION_COOKIES:
            return True
    return False


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] not in SAFE_METHODS
            and scope["path"] not in ORIGIN_EXEMPT_PATHS
        ):
            headers = _headers(scope)
            cookie = headers.get(b"cookie", b"").decode("latin-1")
            if cookie and _has_session_cookie(cookie) and not origin_allowed(headers):
                await _error(403, "E-SEC-1", "Yêu cầu không hợp lệ (nguồn gửi không được phép).")(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        limit = settings.MAX_BODY_BYTES
        too_large = _error(413, "E-SEC-6", "Dữ liệu gửi lên quá lớn.")
        length = _headers(scope).get(b"content-length")
        if length is not None:
            try:
                if int(length) > limit:
                    await too_large(scope, receive, send)
                    return
            except ValueError:
                await _error(400, "E-SEC-6", "Content-Length không hợp lệ.")(scope, receive, send)
                return

        # Đọc trước toàn bộ body (tối đa ``limit`` byte) rồi phát lại cho ứng dụng:
        # chặn cả trường hợp chunked / Content-Length khai sai.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                await too_large(scope, receive, send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        buffered = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def require_origin(request: Request) -> None:
    """Dependency cho route ghi công khai (đăng nhập, web khách): Origin / Referer phải là site
    của mình **kể cả khi chưa có cookie phiên** (ADR-004 S4, T-013 SEC9). GET / HEAD / OPTIONS
    bỏ qua: Next gọi ``GET /auth/me`` từ server component, không có Origin."""
    if request.method in SAFE_METHODS:
        return
    if not origin_allowed(dict(request.scope.get("headers", []))):
        raise AppError("E-SEC-1", "Yêu cầu không hợp lệ (nguồn gửi không được phép).", 403)

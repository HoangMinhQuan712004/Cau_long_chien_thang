"""Gửi lại cookie ``admin_session`` theo hạn của phiên trong DB (T-077).

``deps.get_auth_state`` (gia hạn DB nếu đến hạn) ghi token + ``expires_at`` vào ``request.state``;
middleware này thêm ``Set-Cookie`` (max-age = thời gian còn tới ``expires_at``, không bao giờ dài
hơn DB) vào response – kể cả khi route tự trả ``Response``. Response đã tự đặt / xóa cookie
``admin_session`` (đăng nhập, đăng xuất) thì không chen vào.
"""

import math
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.auth.cookies import admin_cookie_header
from app.modules.auth.deps import ADMIN_SESSION_COOKIE

_PREFIX = f"{ADMIN_SESSION_COOKIE}=".encode()


class AdminSessionRenewalMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = scope.get("state", {}).get("admin_session_cookie")
                headers = list(message.get("headers", []))
                touched = any(
                    k.lower() == b"set-cookie" and v.startswith(_PREFIX) for k, v in headers
                )
                if current and not touched:
                    token, expires_at = current
                    # Làm tròn xuống: cookie không bao giờ sống lâu hơn phiên trong DB
                    left = math.floor((expires_at - datetime.now(UTC)).total_seconds())
                    if left > 0:
                        headers.append((b"set-cookie", admin_cookie_header(token, left)))
                        message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

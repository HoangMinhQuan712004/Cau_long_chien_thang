"""Gửi lại cookie ``admin_session`` khi phiên vừa được gia hạn (T-077).

``deps.get_auth_state`` gia hạn phiên trong DB và ghi token vào ``request.state``; middleware này
thêm ``Set-Cookie`` (max-age = hạn trượt) vào response – kể cả khi route tự trả ``Response``.
Response đã tự đặt / xóa cookie ``admin_session`` (đăng nhập, đăng xuất) thì không chen vào.
"""

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
                token = scope.get("state", {}).get("renewed_admin_session")
                headers = list(message.get("headers", []))
                touched = any(
                    k.lower() == b"set-cookie" and v.startswith(_PREFIX) for k, v in headers
                )
                if token and not touched:
                    headers.append((b"set-cookie", admin_cookie_header(token)))
                    message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

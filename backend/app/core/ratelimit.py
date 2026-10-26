"""Rate limit fixed window trên Redis (ADR-004 §2, S18).

Khóa ``rl:{scope}:{key}:{window}``; vượt giới hạn -> 429 ``E-SEC-5`` + ``Retry-After``.
- Toàn API: ``RateLimitMiddleware`` – ``RATE_LIMIT_PER_MINUTE`` request/phút/IP.
- Từng route: ``Depends(rate_limit("search", 60, key="user"))``.
Redis lỗi -> cho qua (ghi log): không để sự cố Redis chặn toàn bộ API.
"""

import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from redis.asyncio import Redis
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.context import client_ip
from app.core.errors import AppError
from app.core.permissions import OptionalPrincipal

logger = logging.getLogger(__name__)

RATE_LIMIT_MESSAGE = "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút."


class Backend(Protocol):
    async def hit(self, key: str, window_s: int) -> int:
        """Tăng bộ đếm của khóa, trả số lần trong cửa sổ hiện tại."""
        ...


class RedisBackend:
    def __init__(self, url: str):
        self._redis = Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    async def hit(self, key: str, window_s: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s + 1)
            count, _ = await pipe.execute()
        return int(count)


class MemoryBackend:
    """Dùng cho test / chạy cục bộ không có Redis (một tiến trình)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def hit(self, key: str, window_s: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def clear(self) -> None:
        self.counts.clear()


_backend: Backend | None = None
# Đồng hồ của cửa sổ rate limit; test đóng băng để cửa sổ không đổi giữa chừng (tránh chập chờn
# khi chuỗi request vắt qua mốc đổi phút)
_clock: Callable[[], float] = time.time


def get_backend() -> Backend:
    global _backend
    if _backend is None:
        _backend = RedisBackend(settings.REDIS_URL)
    return _backend


def set_backend(backend: Backend) -> None:
    global _backend
    _backend = backend


def set_clock(clock: Callable[[], float]) -> None:
    global _clock
    _clock = clock


async def check(scope: str, key: str, limit: int, window_s: int) -> int | None:
    """Ghi nhận 1 lượt; trả ``Retry-After`` (giây) nếu vượt giới hạn, ngược lại ``None``."""
    if not settings.RATE_LIMIT_ENABLED:
        return None
    now = _clock()
    window = int(now // window_s)
    try:
        count = await get_backend().hit(f"rl:{scope}:{key}:{window}", window_s)
    except Exception:
        logger.warning("Rate limit backend unavailable, allowing request", exc_info=True)
        return None
    if count > limit:
        return max(1, math.ceil((window + 1) * window_s - now))
    return None


def _too_many(retry_after: int) -> AppError:
    return AppError("E-SEC-5", RATE_LIMIT_MESSAGE, 429, headers={"Retry-After": str(retry_after)})


def rate_limit(
    scope: str, limit: int, window_s: int = 60, key: Literal["ip", "user"] = "ip"
) -> Callable[..., Awaitable[None]]:
    """Dependency giới hạn riêng cho route: ``Depends(rate_limit("quote", 60, key="user"))``.

    ``key="user"`` dùng người đăng nhập (chưa đăng nhập -> IP).
    """

    async def dependency(principal: OptionalPrincipal) -> None:
        if key == "user" and principal is not None:
            k = principal.key
        else:
            k = client_ip() or "unknown"
        retry_after = await check(scope, k, limit, window_s)
        if retry_after is not None:
            raise _too_many(retry_after)

    return dependency


class RateLimitMiddleware:
    """Giới hạn chung cho mọi request ``/api/...`` theo IP."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(settings.API_PREFIX):
            retry_after = await check(
                "api", client_ip() or "unknown", settings.RATE_LIMIT_PER_MINUTE, 60
            )
            if retry_after is not None:
                err = _too_many(retry_after)
                response = JSONResponse(
                    {"detail": err.detail}, status_code=429, headers=err.headers
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

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

    async def peek(self, key: str) -> int:
        """Số lần hiện tại của khóa (không tăng)."""
        ...

    async def put(self, key: str, value: float, ttl_s: int) -> None:
        """Ghi một số (vd mốc hết khóa) kèm thời hạn."""
        ...

    async def read(self, key: str) -> float | None: ...

    async def delete(self, *keys: str) -> None: ...


class RedisBackend:
    def __init__(self, url: str):
        self._redis = Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    async def hit(self, key: str, window_s: int) -> int:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_s + 1)
            count, _ = await pipe.execute()
        return int(count)

    async def peek(self, key: str) -> int:
        return int(await self._redis.get(key) or 0)

    async def put(self, key: str, value: float, ttl_s: int) -> None:
        await self._redis.set(key, str(value), ex=ttl_s)

    async def read(self, key: str) -> float | None:
        raw = await self._redis.get(key)
        return float(raw) if raw is not None else None

    async def delete(self, *keys: str) -> None:
        await self._redis.delete(*keys)


class MemoryBackend:
    """Dùng cho test / chạy cục bộ không có Redis (một tiến trình)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.values: dict[str, float] = {}  # không tự hết hạn: người gọi so mốc với đồng hồ

    async def hit(self, key: str, window_s: int) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def peek(self, key: str) -> int:
        return self.counts.get(key, 0)

    async def put(self, key: str, value: float, ttl_s: int) -> None:
        self.values[key] = value

    async def read(self, key: str) -> float | None:
        return self.values.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.counts.pop(key, None)
            self.values.pop(key, None)

    def clear(self) -> None:
        self.counts.clear()
        self.values.clear()


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


def _window_key(scope: str, key: str, window_s: int) -> tuple[str, float, int]:
    now = _clock()
    window = int(now // window_s)
    return f"rl:{scope}:{key}:{window}", now, window


async def failures_exceeded(scope: str, key: str, limit: int, window_s: int) -> int | None:
    """Đã có ≥ ``limit`` lần sai trong cửa sổ -> ``Retry-After`` (giây); không tăng bộ đếm.

    Dùng cho đếm nhập sai mật khẩu (ghi bằng ``record_failure``). Backend lỗi -> cho qua.
    """
    rl_key, now, window = _window_key(scope, key, window_s)
    try:
        count = await get_backend().peek(rl_key)
    except Exception:
        logger.warning("Rate limit backend unavailable, allowing request", exc_info=True)
        return None
    if count >= limit:
        return max(1, math.ceil((window + 1) * window_s - now))
    return None


async def record_failure(scope: str, key: str, window_s: int) -> None:
    rl_key, _, _ = _window_key(scope, key, window_s)
    try:
        await get_backend().hit(rl_key, window_s)
    except Exception:
        logger.warning("Rate limit backend unavailable, failure not recorded", exc_info=True)


async def streak_lock(
    scope: str, key: str, limit: int, lock_s: int, streak_ttl_s: int
) -> int | None:
    """Khóa theo chuỗi lần sai liên tiếp (không theo cửa sổ cố định), đếm + mốc khóa trên Redis.

    Đang khóa -> ``Retry-After`` còn lại (không đếm thêm). Chưa khóa -> đếm 1 lần sai (bộ đếm
    hết hạn sau ``streak_ttl_s`` không sai thêm); chạm ``limit`` -> khóa ``lock_s`` giây, trả
    ``lock_s``.
    Không khóa -> ``None``. Backend lỗi -> cho qua (``None``).
    """
    count_key, lock_key = f"streak:{scope}:{key}", f"lock:{scope}:{key}"
    now = _clock()
    try:
        backend = get_backend()
        until = await backend.read(lock_key)
        if until is not None and until > now:
            return max(1, math.ceil(until - now))
        if await backend.hit(count_key, streak_ttl_s) < limit:
            return None
        await backend.put(lock_key, now + lock_s, lock_s + 1)
        await backend.delete(count_key)
    except Exception:
        logger.warning("Rate limit backend unavailable, streak not recorded", exc_info=True)
        return None
    return lock_s


def too_many(retry_after: int) -> AppError:
    return _too_many(retry_after)


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

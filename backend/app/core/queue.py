"""Đẩy job sang ARQ worker – **chỉ gọi sau commit** (T-013, port PR #17)."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)


class SecretArg(str):
    """Tham số job bí mật (OTP): ``repr`` che giá trị (arq ghi repr tham số vào log)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "'******'"


_pool: ArqRedis | None = None
# Test thay bằng hàm ghi lại job (không cần Redis)
_sink: Callable[[str, tuple[Any, ...]], Awaitable[None]] | None = None


def set_sink(sink: Callable[[str, tuple[Any, ...]], Awaitable[None]] | None) -> None:
    global _sink
    _sink = sink


async def enqueue(job: str, *args: Any) -> None:
    """Redis lỗi -> chỉ log tên job (không log tham số – có thể chứa OTP), không hỏng request."""
    global _pool
    if _sink is not None:
        await _sink(job, args)
        return
    try:
        if _pool is None:
            redis = RedisSettings.from_dsn(settings.REDIS_URL)
            redis.conn_retries = 0  # Redis chết thì trả ngay
            _pool = await create_pool(redis)
        await _pool.enqueue_job(job, *args)
    except Exception:
        logger.exception("Không đẩy được job %s sang worker", job)

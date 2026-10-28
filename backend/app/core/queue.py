"""Đẩy job sang ARQ worker; chỉ gọi sau commit."""

import logging
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


class SecretArg(str):
    """Tham số job bí mật (OTP): `repr` che giá trị trong log arq."""

    def __repr__(self) -> str:
        return "'******'"


async def enqueue(job: str, *args: Any) -> None:
    """Redis lỗi ⇒ chỉ log (không log args – có thể chứa OTP), không làm hỏng request."""
    global _pool
    try:
        if _pool is None:
            # không thử lại: Redis chết thì trả ngay
            redis = RedisSettings.from_dsn(settings.REDIS_URL)
            redis.conn_retries = 0
            _pool = await create_pool(redis)
        await _pool.enqueue_job(job, *args)
    except Exception:
        logger.exception("Không đẩy được job %s sang worker", job)


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None

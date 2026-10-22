"""ARQ worker. Chạy: arq app.workers.worker.WorkerSettings"""

import logging

from arq import cron
from arq.connections import RedisSettings

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.bookings import service as bookings_service

logger = logging.getLogger(__name__)


async def expire_pending_bookings(ctx) -> int:
    async with SessionLocal() as session:
        count = await bookings_service.expire_pending(session)
    if count:
        logger.info("Expired %s pending bookings", count)
    return count


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [expire_pending_bookings]
    cron_jobs = [cron(expire_pending_bookings, second=0)]  # mỗi phút

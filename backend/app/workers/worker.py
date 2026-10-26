"""ARQ worker. Chạy: arq app.workers.worker.WorkerSettings"""

import logging

from arq import cron
from arq.connections import RedisSettings

import app.models  # noqa: F401
import app.modules.notifications.handlers  # noqa: F401  (handler nhận sự kiện outbox)
from app.core import audit, idempotency
from app.core.config import settings
from app.core.context import setup_logging
from app.core.db import SessionLocal
from app.modules.booking_engine import api as booking_engine
from app.modules.bookings import service as bookings_service

setup_logging()
logger = logging.getLogger(__name__)


async def expire_pending_bookings(ctx) -> int:
    async with SessionLocal() as session:
        count = await bookings_service.expire_pending(session)
    if count:
        logger.info("Expired %s pending bookings", count)
    return count


async def publish_booking_outbox(ctx) -> int:
    return await booking_engine.publish_outbox(SessionLocal)


async def expire_holds(ctx) -> int:
    async with SessionLocal() as session:
        count = await booking_engine.expire_holds(session)
        await session.commit()
    if count:
        logger.info("Expired %s booking holds", count)
    return count


async def purge_audit_log(ctx) -> int:
    async with SessionLocal() as session:
        count = await audit.purge_expired(session)
    if count:
        logger.info("Purged %s audit log rows older than %s", count, audit.RETENTION)
    return count


async def purge_idempotency_keys(ctx) -> int:
    async with SessionLocal() as session:
        return await idempotency.purge_expired(session)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [
        expire_pending_bookings,
        publish_booking_outbox,
        expire_holds,
        purge_audit_log,
        purge_idempotency_keys,
    ]
    cron_jobs = [
        cron(expire_pending_bookings, second=0),  # mỗi phút
        cron(publish_booking_outbox, second=set(range(0, 60, 2)), unique=True),  # mỗi 2 giây
        cron(expire_holds, second={0, 30}, unique=True),  # mỗi 30 giây
        cron(purge_audit_log, hour=3, minute=15, second=0),  # hằng ngày
        cron(purge_idempotency_keys, minute=5, second=0),  # mỗi giờ
    ]

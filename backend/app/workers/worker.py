"""ARQ worker. Chạy: arq app.workers.worker.WorkerSettings"""

import logging

from arq import cron
from arq.connections import RedisSettings

import app.models  # noqa: F401
import app.modules.members.handlers  # noqa: F401  (handler nhận sự kiện outbox)
import app.modules.notifications.handlers  # noqa: F401
import app.modules.payments.handlers  # noqa: F401
from app.core import audit, idempotency
from app.core.config import settings
from app.core.context import setup_logging
from app.core.db import SessionLocal
from app.modules.auth import otp as otp_service
from app.modules.auth.models import OtpCode
from app.modules.booking_engine import api as booking_engine
from app.modules.notifications import zalo

setup_logging()
logger = logging.getLogger(__name__)


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


async def send_zalo_otp(ctx, code_id: int, otp: str) -> bool:
    """Gửi OTP qua Zalo; mã đã bị thay / đã dùng thì bỏ qua (tham số ``otp`` che khi log)."""
    async with SessionLocal() as session:
        row = await session.get(OtpCode, code_id)
        if row is None or row.used_at is not None or row.token_hash is not None:
            return False
        phone = row.phone
    return await zalo.send_otp(phone, otp)


async def purge_otp_codes(ctx) -> int:
    async with SessionLocal() as session:
        return await otp_service.purge_old(session)


async def purge_idempotency_keys(ctx) -> int:
    async with SessionLocal() as session:
        return await idempotency.purge_expired(session)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions = [
        publish_booking_outbox,
        expire_holds,
        purge_audit_log,
        purge_idempotency_keys,
        send_zalo_otp,
        purge_otp_codes,
    ]
    cron_jobs = [
        cron(publish_booking_outbox, second=set(range(0, 60, 2)), unique=True),  # mỗi 2 giây
        cron(expire_holds, second={0, 30}, unique=True),  # mỗi 30 giây
        cron(purge_audit_log, hour=3, minute=15, second=0),  # hằng ngày
        cron(purge_idempotency_keys, minute=5, second=0),  # mỗi giờ
        cron(purge_otp_codes, minute=35, second=0),  # mỗi giờ: mã quá 24 giờ
    ]

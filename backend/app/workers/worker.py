"""ARQ worker. Chạy: arq app.workers.worker.WorkerSettings"""

import logging

from arq import cron, func
from arq.connections import RedisSettings

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import PasswordResetCode
from app.modules.bookings import service as bookings_service
from app.modules.notifications import zalo

logger = logging.getLogger(__name__)


async def expire_pending_bookings(ctx) -> int:
    async with SessionLocal() as session:
        count = await bookings_service.expire_pending(session)
    if count:
        logger.info("Expired %s pending bookings", count)
    return count


async def send_zalo_otp(ctx, code_id: int, otp: str) -> None:
    """Gửi OTP tới SĐT của mã (job chỉ mang id mã); mã đã thay/đã dùng ⇒ bỏ qua."""
    async with SessionLocal() as session:
        code = await session.get(PasswordResetCode, code_id)
    if code is None or code.used_at is not None:
        return
    await zalo.send_otp(code.phone, otp)


async def startup(ctx) -> None:
    """CLI `arq` chỉ gắn handler cho logger "arq" ⇒ log INFO của app (vd OTP khi dev) bị bỏ."""
    app_logger = logging.getLogger("app")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s: %(name)s %(message)s", "%H:%M:%S"))
        app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    on_startup = startup
    # không lưu kết quả (tham số có OTP)
    functions = [expire_pending_bookings, func(send_zalo_otp, keep_result=0)]
    cron_jobs = [cron(expire_pending_bookings, second=0)]  # mỗi phút

"""Job ARQ gửi push (T-076) – chạy trong worker, mỗi job một session riêng, lỗi không lan ra."""

import logging

from app.core.db import SessionLocal
from app.modules.auth import api as auth
from app.modules.web_push import service

logger = logging.getLogger(__name__)


async def push_test(ctx, user_id: int, url: str) -> int:
    """Gửi thử: chỉ các thiết bị của chính tài khoản (đang hoạt động)."""
    async with SessionLocal() as session:
        if not await auth.active_user_ids(session, {user_id}):
            return 0
        return await service.deliver(session, {user_id}, service.test_message(url))

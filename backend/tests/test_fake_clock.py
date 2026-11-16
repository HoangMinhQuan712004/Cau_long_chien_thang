"""T-067: giờ của Postgres (``now()``, ``DEFAULT now()``) luôn khớp giờ Python – cả khi chạy với
``TEST_FAKE_NOW`` (giờ giả), để test không lệch giữa hai đồng hồ."""

import os
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.db import SessionLocal
from app.modules.auth.models import OtpCode
from tests import fake_clock


async def test_database_clock_follows_python_clock():
    async with SessionLocal() as s:
        db_now = await s.scalar(text("SELECT now()"))
        otp = OtpCode(phone="0800000000", purpose="register", code_hash="x" * 64, expires_at=db_now)
        s.add(otp)
        await s.flush()
        await s.refresh(otp)
        created = otp.created_at
        await s.rollback()
    py_now = datetime.now(UTC)
    assert abs((db_now - py_now).total_seconds()) < 1
    assert abs((created - py_now).total_seconds()) < 1  # DEFAULT now() của bảng cũng theo
    if os.environ.get(fake_clock.ENV):
        target = datetime.fromisoformat(os.environ[fake_clock.ENV])
        assert fake_clock.active() and abs((py_now - target).total_seconds()) < 3600

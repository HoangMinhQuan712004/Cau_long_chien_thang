import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.core.config import settings

# Dùng DB riêng cho test: <tên db>_test (phải set TRƯỚC khi import app.core.db)
settings.DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    make_url(settings.DATABASE_URL)
    .set(database=f"{make_url(settings.DATABASE_URL).database}_test")
    .render_as_string(hide_password=False),
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts import seed  # noqa: E402

API = settings.API_PREFIX
ORIGIN = "http://testserver"
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Origin check (ADR-004 S4): client test gửi Origin của "site" test
settings.ALLOWED_ORIGINS = [ORIGIN]
# Rate limit chạy bằng bộ nhớ trong test (không cần Redis); reset trước mỗi test
_rate_limit_backend = ratelimit.MemoryBackend()
ratelimit.set_backend(_rate_limit_backend)


def _alembic_upgrade_head() -> None:
    # Không truyền alembic.ini: tránh fileConfig() ghi đè cấu hình logging của test
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncIterator[None]:
    """DB test dựng bằng migration thật (schema ``booking``, trigger ``audit_log``, EXCLUDE…)."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS booking CASCADE"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await conn.execute(text("DROP FUNCTION IF EXISTS audit_log_guard() CASCADE"))
    # env.py của alembic tự chạy asyncio.run -> chạy ở thread riêng
    await asyncio.to_thread(_alembic_upgrade_head)
    await seed.main()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    """Mỗi test bắt đầu với bộ đếm rate limit trống (tương đương dọn khóa ``rl:*``)."""
    _rate_limit_backend.clear()


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
    )


def idem() -> dict[str, str]:
    """Header ``Idempotency-Key`` mới (UUID v4) cho một lần bấm nút."""
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
async def anon() -> AsyncIterator[AsyncClient]:
    async with _client() as c:
        yield c


_counter = 0


@asynccontextmanager
async def new_customer() -> AsyncIterator[AsyncClient]:
    """Client đã đăng ký + đăng nhập (cookie) bằng một khách hàng mới."""
    global _counter
    _counter += 1
    async with _client() as c:
        r = await c.post(
            f"{API}/auth/register",
            json={
                "email": f"user{_counter}@test.vn",
                "password": "password123",
                "full_name": f"Khách {_counter}",
                "phone": "0900000000",
            },
        )
        assert r.status_code == 201, r.text
        yield c


@pytest.fixture
async def customer() -> AsyncIterator[AsyncClient]:
    async with new_customer() as c:
        yield c


@pytest.fixture
async def admin() -> AsyncIterator[AsyncClient]:
    async with _client() as c:
        r = await c.post(
            f"{API}/auth/login",
            json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
        )
        assert r.status_code == 200, r.text
        yield c


_STAFF_EMAIL = "quay@test.vn"
_STAFF_PASSWORD = "password123"


@pytest.fixture
async def staff(admin: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Client đăng nhập bằng "Tài khoản tại máy" (vai ``staff``) – tạo lần đầu qua API admin."""
    async with _client() as c:
        r = await c.post(
            f"{API}/auth/login", json={"email": _STAFF_EMAIL, "password": _STAFF_PASSWORD}
        )
        if r.status_code == 401:
            created = await admin.post(
                f"{API}/admin/users",
                json={
                    "email": _STAFF_EMAIL,
                    "password": _STAFF_PASSWORD,
                    "full_name": "Tài khoản tại máy",
                    "phone": "0911222333",
                    "role": "staff",
                },
            )
            assert created.status_code == 201, created.text
            r = await c.post(
                f"{API}/auth/login", json={"email": _STAFF_EMAIL, "password": _STAFF_PASSWORD}
            )
        assert r.status_code == 200, r.text
        yield c


def slot(court_id: int, hour: int, minute: int = 0, minutes: int = 60, days: int = 2) -> dict:
    """Slot vào ngày (hôm nay + days) theo giờ địa phương."""
    day = datetime.now(settings.tz).date() + timedelta(days=days)
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz)
    end = start + timedelta(minutes=minutes)
    return {"court_id": court_id, "start": start.isoformat(), "end": end.isoformat()}

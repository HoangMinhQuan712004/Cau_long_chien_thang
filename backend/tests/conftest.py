import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.engine import make_url

from app.core.config import settings

# Dùng DB riêng cho test: <tên db>_test (phải set TRƯỚC khi import app.core.db)
settings.DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    make_url(settings.DATABASE_URL)
    .set(database=f"{make_url(settings.DATABASE_URL).database}_test")
    .render_as_string(hide_password=False),
)

# Mọi test gọi từ cùng IP (127.0.0.1) ⇒ nới giới hạn đăng ký; test giới hạn dùng IP riêng (XFF)
settings.REGISTER_IP_MAX_PER_HOUR = 100_000

from sqlalchemy import text  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.scripts import seed  # noqa: E402
from tests.client import API, make_client  # noqa: E402
from tests.helpers import new_staff, reset_state  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await seed.main()
    yield
    await engine.dispose()


@pytest.fixture
async def anon() -> AsyncIterator[AsyncClient]:
    async with make_client() as c:
        yield c


_counter = 0


@asynccontextmanager
async def new_customer() -> AsyncIterator[AsyncClient]:
    """Client đã đăng ký + đăng nhập (cookie) bằng một khách hàng mới."""
    global _counter
    _counter += 1
    async with make_client() as c:
        r = await c.post(
            f"{API}/auth/register",
            json={
                "password": "Password@123",
                "full_name": f"Khách {_counter}",
                "phone": f"09{_counter:08d}",
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
    async with make_client() as c:
        r = await c.post(
            f"{API}/auth/sign-in",
            json={"login": settings.FIRST_ADMIN_PHONE, "password": settings.FIRST_ADMIN_PASSWORD},
        )
        assert r.status_code == 200, r.text
        yield c


def slot(court_id: int, hour: int, minute: int = 0, minutes: int = 60, days: int = 2) -> dict:
    """Slot vào ngày (hôm nay + days) theo giờ địa phương."""
    day = datetime.now(settings.tz).date() + timedelta(days=days)
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz)
    end = start + timedelta(minutes=minutes)
    return {"court_id": court_id, "start": start.isoformat(), "end": end.isoformat()}


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncIterator[None]:
    await reset_state()
    yield
    await reset_state()


@pytest.fixture
async def staff(admin) -> dict:
    """Nhân viên mới (dict từ API) – đăng nhập bằng `{"login": staff["username"], ...}`."""
    return await new_staff(admin)

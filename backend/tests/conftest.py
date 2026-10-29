import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

from app.core import queue, ratelimit  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts import seed  # noqa: E402
from tests.db_guard import reset_refusal  # noqa: E402

API = settings.API_PREFIX
ORIGIN = "http://testserver"
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Origin check (ADR-004 S4): client test gửi Origin của "site" test
settings.ALLOWED_ORIGINS = [ORIGIN]
# Đặt online (T-008): cấu hình SePay giả để bật online + giả lập tiền về
SEPAY_SECRET = "test-webhook-secret"
settings.SEPAY_BANK_CODE = "Vietcombank"
settings.SEPAY_BANK_NAME = "Vietcombank"
settings.SEPAY_ACCOUNT_NUMBER = "0123456789"
settings.SEPAY_ACCOUNT_NAME = "SAN CAU LONG TEST"
settings.SEPAY_WEBHOOK_SECRET = SEPAY_SECRET
settings.PAYMENTS_SIMULATE = True
# Khóa mã hóa cố định cho test (T-012). Không ghi dòng payments.settings: test T-008 dùng .env
settings.PAYMENTS_ENCRYPTION_KEY = "dGVzdC1rZXktZm9yLXBheW1lbnRzLWVuY3J5cHRpb24="
# Rate limit chạy bằng bộ nhớ trong test (không cần Redis); reset trước mỗi test
_rate_limit_backend = ratelimit.MemoryBackend()
ratelimit.set_backend(_rate_limit_backend)
# Đóng băng đồng hồ rate limit ở đầu một cửa sổ phút: chuỗi request trong một test không bao giờ
# bị tách sang cửa sổ mới (nguyên nhân test 429 chập chờn khi chạy qua mốc đổi phút)
_RATE_LIMIT_NOW = (time.time() // 60) * 60 + 1
ratelimit.set_clock(lambda: _RATE_LIMIT_NOW)
# OTP (T-013): chế độ thử = có kênh gửi mã (link dev); job worker ghi vào danh sách thay vì Redis
settings.OTP_TEST_MODE = True
# Mọi test gọi từ cùng IP 127.0.0.1 -> nới giới hạn OTP theo IP; test giới hạn IP tự hạ + IP riêng
settings.OTP_IP_MAX_PER_HOUR = 1_000_000
ENQUEUED_JOBS: list[tuple[str, tuple]] = []


async def _record_job(job: str, args: tuple) -> None:
    ENQUEUED_JOBS.append((job, args))


queue.set_sink(_record_job)


def _alembic_upgrade_head() -> None:
    # Không truyền alembic.ini: tránh fileConfig() ghi đè cấu hình logging của test
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncIterator[None]:
    """DB test dựng bằng migration thật (schema ``booking``, trigger ``audit_log``, EXCLUDE…)."""
    refusal = reset_refusal(settings.DATABASE_URL, settings.ENV, os.environ.get("CI"))
    if refusal:
        pytest.exit(refusal, returncode=2)
    async with engine.begin() as conn:
        # Xóa sạch (gồm bảng legacy_* và enum của luồng cũ – không còn trong metadata)
        await conn.execute(text("DROP SCHEMA IF EXISTS booking CASCADE"))
        await conn.execute(text("DROP SCHEMA IF EXISTS payments CASCADE"))
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # env.py của alembic tự chạy asyncio.run -> chạy ở thread riêng
    await asyncio.to_thread(_alembic_upgrade_head)
    await seed.main()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_payment_config_cache() -> None:
    """Cấu hình thanh toán cache ≤ 10 giây theo tiến trình – mỗi test đọc lại từ DB / .env."""
    from app.modules.payments import config as payment_config

    payment_config.clear_cache()


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
CUSTOMER_PASSWORD = "Password123"


def unique_phone() -> str:
    """SĐT duy nhất cho test (``08`` + 8 số ngẫu nhiên)."""
    return "08" + str(uuid.uuid4().int)[:8]


@asynccontextmanager
async def new_customer(phone: str | None = None) -> AsyncIterator[AsyncClient]:
    """Client đã đăng ký + đăng nhập (JWT cookie) bằng một khách mới (SĐT chưa xác minh)."""
    global _counter
    _counter += 1
    async with _client() as c:
        r = await c.post(
            f"{API}/auth/register",
            json={
                "full_name": f"Khách {_counter}",
                "phone": phone or unique_phone(),
                "password": CUSTOMER_PASSWORD,
            },
        )
        assert r.status_code == 201, r.text
        yield c


@pytest.fixture
async def customer() -> AsyncIterator[AsyncClient]:
    async with new_customer() as c:
        yield c


async def sign_in(client: AsyncClient, login: str, password: str):
    return await client.post(f"{API}/auth/sign-in", json={"login": login, "password": password})


@pytest.fixture
async def admin() -> AsyncIterator[AsyncClient]:
    """Admin đăng nhập bằng SĐT (phiên quản trị, cookie ``admin_session``)."""
    async with _client() as c:
        r = await sign_in(c, settings.FIRST_ADMIN_PHONE, settings.FIRST_ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        yield c


STAFF_NAME = "Nhân Viên Quầy"
STAFF_PASSWORD = "Password123"
_staff_username: str | None = None


def is_staff_label(label: str | None) -> bool:
    """Nhãn người thao tác của nhân viên fixture: ``NV00x · Nhân Viên Quầy`` (ADR-008 §2)."""
    return bool(label) and label.startswith("NV") and label.endswith(f" · {STAFF_NAME}")


@pytest.fixture
async def staff(admin: AsyncClient) -> AsyncIterator[AsyncClient]:
    """Nhân viên (vai ``staff``): tạo một lần qua ``/admin/staff``, đăng nhập bằng tên đăng nhập."""
    global _staff_username
    if _staff_username is None:
        created = await admin.post(
            f"{API}/admin/staff", json={"full_name": STAFF_NAME, "password": STAFF_PASSWORD}
        )
        assert created.status_code == 201, created.text
        _staff_username = created.json()["username"]
    async with _client() as c:
        r = await sign_in(c, _staff_username, STAFF_PASSWORD)
        assert r.status_code == 200, r.text
        yield c

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url

from app.core.config import settings
from tests import fake_clock

# Giờ giả cho cả bộ (``TEST_FAKE_NOW``, T-067) – bật trước mọi chỗ đọc giờ lúc import
fake_clock.start()


def _test_database_url() -> str:
    """DB test: ``<tên db>_test`` (hoặc ``TEST_DATABASE_URL``). Chạy song song (pytest-xdist,
    T-059): mỗi worker một DB riêng ``<tên>_gw0_test``… – mã ``BK-YYYYMMDD-NNN`` tuần tự theo ngày,
    số đếm và thẻ tổng phụ thuộc dữ liệu chung nên các worker không được dùng chung DB."""
    url = make_url(
        os.environ.get("TEST_DATABASE_URL")
        or make_url(settings.DATABASE_URL).set(
            database=f"{make_url(settings.DATABASE_URL).database}_test"
        )
    )
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        name = url.database or ""
        base, test = (name[: -len("_test")], "_test") if name.endswith("_test") else (name, "")
        url = url.set(database=f"{base}_{worker}{test}")
    return url.render_as_string(hide_password=False)


# Phải set TRƯỚC khi import app.core.db
settings.DATABASE_URL = _test_database_url()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from pwdlib import PasswordHash  # noqa: E402
from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: E402
from sqlalchemy import delete, text, update  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core import queue, ratelimit, security  # noqa: E402

# Argon2 rẻ CHỈ khi test (T-059): bản ``recommended`` (m=64 MiB, t=3, p=4) tốn ~0,2 giây và 64 MiB
# mỗi lần băm / so – mỗi lần đăng nhập của fixture. Vẫn là argon2id thật (``$argon2id$…``), chỉ
# hạ tham số; đặt trước seed để mọi hash trong DB test cùng tham số. Code ứng dụng không đổi.
security.password_hash = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))

from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth.models import OtpCode, Role, User  # noqa: E402
from app.modules.auth.utils import normalize_phone  # noqa: E402
from app.scripts import seed  # noqa: E402
from tests.db_guard import reset_refusal  # noqa: E402

API = settings.API_PREFIX
ORIGIN = "http://testserver"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def vn_today() -> date:
    """Hôm nay theo giờ VN (múi giờ nghiệp vụ). Không dùng ``date.today``: máy CI chạy UTC,
    00:00–07:00 giờ VN nó còn là hôm qua -> đặt quầy "hôm nay" thành ngày đã qua (E-004)."""
    return datetime.now(settings.tz).date()


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


async def _create_database_if_missing(database_url: str) -> None:
    """DB của worker xdist (hoặc DB test lần đầu) chưa có thì tạo; đặt / gỡ giờ giả (T-067)."""
    url = make_url(database_url)
    server = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with server.connect() as conn:
            found = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
            )
            if not found:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            await fake_clock.configure_database(conn, url.database)
    finally:
        await server.dispose()


@pytest.fixture(scope="session", autouse=True)
async def setup_db() -> AsyncIterator[None]:
    """DB test dựng bằng migration thật (schema ``booking``, trigger ``audit_log``, EXCLUDE…)."""
    refusal = reset_refusal(settings.DATABASE_URL, settings.ENV, os.environ.get("CI"))
    if refusal:
        pytest.exit(refusal, returncode=2)
    await _create_database_if_missing(settings.DATABASE_URL)
    async with engine.begin() as conn:
        # Xóa sạch (gồm bảng legacy_* và enum của luồng cũ – không còn trong metadata)
        await conn.execute(text("DROP SCHEMA IF EXISTS booking CASCADE"))
        await conn.execute(text("DROP SCHEMA IF EXISTS payments CASCADE"))
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await fake_clock.install_now(conn)
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


_customer_hash: str | None = None


@asynccontextmanager
async def new_customer(phone: str | None = None) -> AsyncIterator[AsyncClient]:
    """Client đã đăng nhập (JWT cookie) bằng một khách mới, **SĐT chưa xác minh** – như tài khoản
    tự đăng ký không OTP đời T-013. Từ T-021 đường đó đã đóng (410) nên tạo thẳng trong DB;
    đăng ký thật (OTP, thành hội viên) dùng ``new_registered``."""
    global _counter, _customer_hash
    _counter += 1
    if _customer_hash is None:
        _customer_hash = hash_password(CUSTOMER_PASSWORD)
    phone = phone or unique_phone()
    async with SessionLocal() as s:
        s.add(
            User(
                phone=phone,
                full_name=f"Khách {_counter}",
                hashed_password=_customer_hash,
                role=Role.MEMBER,
                is_active=True,
            )
        )
        await s.commit()
    async with _client() as c:
        r = await sign_in(c, phone, CUSTOMER_PASSWORD)
        assert r.status_code == 200, r.text
        yield c


async def age_otp_codes(phone: str) -> None:
    """Mã OTP đã phát cho SĐT coi như phát từ 2 giờ trước (bỏ chờ gửi lại / giới hạn giờ)."""
    async with SessionLocal() as s:
        await s.execute(
            update(OtpCode)
            .where(OtpCode.phone == phone)
            .values(created_at=OtpCode.created_at - timedelta(hours=2))
        )
        await s.commit()


async def register(
    client: AsyncClient, phone: str, full_name: str = "Khách Đăng Ký", password: str = ""
):
    """Đăng ký 2 bước (T-021) bằng mã thử; trả response của bước verify.

    Lùi giờ các mã cũ của SĐT: test gửi nhiều mã cho cùng số không vướng chờ gửi lại 60 giây."""
    await age_otp_codes(normalize_phone(phone) or phone)
    r = await client.post(
        f"{API}/auth/register/request",
        json={"full_name": full_name, "phone": phone, "password": password or CUSTOMER_PASSWORD},
    )
    assert r.status_code == 202, r.text
    return await client.post(
        f"{API}/auth/register/verify", json={"phone": phone, "otp": r.json()["test_otp"]}
    )


@asynccontextmanager
async def new_registered(
    phone: str | None = None, full_name: str | None = None
) -> AsyncIterator[AsyncClient]:
    """Client vừa đăng ký 2 bước (SĐT đã xác minh = hội viên, T-021) và đã đăng nhập."""
    global _counter
    _counter += 1
    async with _client() as c:
        r = await register(c, phone or unique_phone(), full_name or f"Khách {_counter}")
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
    """Admin đăng nhập bằng SĐT (phiên quản trị, cookie ``admin_session``).

    Gỡ khóa nhập sai trước: một test lỗi giữa chừng để Admin bị khóa không kéo đổ mọi test sau.
    """
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.phone == settings.FIRST_ADMIN_PHONE)
            .values(failed_login_count=0, locked_until=None)
        )
        await s.commit()
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


@asynccontextmanager
async def extra_admin(password: str, **fields) -> AsyncIterator[tuple[int, str]]:
    """Admin phụ (tạo rồi **xóa**): ngoài test, DB chỉ có một Admin như thực tế – lệnh
    ``reset_admin_password`` và test QA dựa vào điều đó. Trả ``(id, SĐT)``."""
    phone = unique_phone()
    async with SessionLocal() as s:
        user = User(
            phone=phone,
            phone_verified_at=datetime.now(UTC),
            full_name="Admin phụ",
            hashed_password=hash_password(password),
            role=Role.ADMIN,
            **fields,
        )
        s.add(user)
        await s.commit()
        user_id = user.id
    try:
        yield user_id, phone
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(User).where(User.id == user_id))
            await s.commit()

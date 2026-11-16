"""T-021 AC7: migration ``9738bbfe2eb7`` backfill hội viên cho tài khoản đã xác minh SĐT.

Dựng DB riêng ``<db>_mig_t021`` ở revision trước (``5b98d354dd77``), nạp tài khoản / hồ sơ kiểu
cũ bằng SQL, nâng cấp rồi kiểm; sau đó hạ cấp. Không đụng DB test chính.
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import BACKEND_DIR

BEFORE = "5b98d354dd77"
TARGET = "9738bbfe2eb7"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_t021")

LEGACY = """
INSERT INTO customer (kind, member_code, full_name, phone, is_active)
    VALUES ('member', 'HV0005', 'Hội Viên Cũ', '0900000003', true),
           ('temp', NULL, 'Khách Tạm', '0900000002', true);
INSERT INTO users (phone, full_name, role, is_active, phone_verified_at, hashed_password)
    VALUES ('0900000001', '  Nguyễn  Văn An ', 'member', true, now() - interval '2 day', 'x'),
           ('0900000002', 'Tên Tài Khoản', 'member', true, now() - interval '1 day', 'x'),
           ('0900000003', 'Hội Viên Cũ', 'member', true, now(), 'x'),
           ('0900000004', 'Chưa Xác Minh', 'member', true, NULL, 'x'),
           ('0900000005', 'Đã Khóa', 'member', false, now(), 'x')
"""


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


async def alembic(fn, revision: str) -> None:
    old = settings.DATABASE_URL
    settings.DATABASE_URL = MIG_URL.render_as_string(hide_password=False)
    try:
        await asyncio.to_thread(fn, _cfg(), revision)
    finally:
        settings.DATABASE_URL = old


async def rows(sql: str):
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).all()
    finally:
        await engine.dispose()


async def run(sql: str) -> None:
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            for stmt in [s for s in sql.split(";\n") if s.strip()]:
                await conn.execute(text(stmt))
    finally:
        await engine.dispose()


@pytest.fixture
async def legacy_db():
    server = create_async_engine(make_url(REAL_URL).set(database="postgres"))
    server = server.execution_options(isolation_level="AUTOCOMMIT")
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
        await c.execute(text(f"CREATE DATABASE {MIG_URL.database}"))
    await alembic(command.upgrade, BEFORE)
    await run(LEGACY)
    yield
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
    await server.dispose()


async def test_backfill_creates_or_upgrades_members(legacy_db):
    await alembic(command.upgrade, TARGET)

    customers = await rows(
        "SELECT phone, kind, member_code, full_name, source FROM customer ORDER BY phone"
    )
    assert customers == [
        # xác minh sớm nhất -> mã kế tiếp đầu tiên; họ tên lấy từ tài khoản (gộp khoảng trắng)
        ("0900000001", "member", "HV0006", "Nguyễn Văn An", "self_register"),
        # hồ sơ tạm -> nâng trên cùng dòng, giữ họ tên của hồ sơ
        ("0900000002", "member", "HV0007", "Khách Tạm", "self_register"),
        ("0900000003", "member", "HV0005", "Hội Viên Cũ", "counter"),  # đã là hội viên
    ]
    audits = await rows(
        "SELECT action, entity_code, actor_type, detail->>'phone', detail->'target'->>'name'"
        " FROM audit_log WHERE detail->>'backfill' = 'true' ORDER BY entity_code"
    )
    assert audits == [
        ("member.self_register", "HV0006", "system", "0900 xxx 001", "Nguyễn Văn An"),
        ("member.auto_upgrade_temp", "HV0007", "system", "0900 xxx 002", "Khách Tạm"),
    ]
    enum = await rows("SELECT unnest(enum_range(NULL::otp_purpose))::text")
    assert ("register",) in enum

    # Hạ cấp: cột / bảng / giá trị enum bỏ đi; hội viên đã tạo vẫn giữ
    await alembic(command.downgrade, BEFORE)
    assert await rows("SELECT count(*) FROM customer WHERE kind = 'member'") == [(3,)]
    assert ("register",) not in await rows("SELECT unnest(enum_range(NULL::otp_purpose))::text")
    assert await rows("SELECT to_regclass('registration_requests') IS NULL") == [(True,)]
    # Nâng lại: không backfill lần hai (đã là hội viên)
    await alembic(command.upgrade, TARGET)
    assert await rows("SELECT count(*) FROM customer WHERE kind = 'member'") == [(3,)]


async def test_downgrade_keeps_disabled_accounts_without_login(legacy_db):
    """Tài khoản bị gỡ SĐT + vô hiệu (AC3) không thỏa ràng buộc cũ -> hạ cấp vẫn chạy."""
    await alembic(command.upgrade, TARGET)
    await run("UPDATE users SET phone = NULL, is_active = false WHERE phone = '0900000004'")
    await alembic(command.downgrade, BEFORE)
    assert await rows("SELECT count(*) FROM users WHERE phone IS NULL") == [(1,)]

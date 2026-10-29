"""T-013 AC32: migration ``3c30569e12af`` trên production – SĐT Admin thiếu / mẫu -> dừng.

Dựng DB riêng ``<db>_mig_be`` ở revision trước T-013 (không đụng DB test chính, khác DB của QA).
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import SAMPLE_ADMIN_PHONE, settings
from tests.conftest import BACKEND_DIR

BEFORE = "cc9af0a8c694"
TARGET = "3c30569e12af"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_be")
REAL_PHONE = "0987000111"


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


async def alembic(fn, revision: str) -> None:
    """env.py tự chạy ``asyncio.run`` -> chạy ở thread riêng, trỏ vào DB riêng."""
    old = settings.DATABASE_URL
    settings.DATABASE_URL = MIG_URL.render_as_string(hide_password=False)
    try:
        await asyncio.to_thread(fn, _cfg(), revision)
    finally:
        settings.DATABASE_URL = old


async def query(sql: str):
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(text(sql))).all()
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
    engine = create_async_engine(MIG_URL)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (email, full_name, hashed_password, role, is_active) "
                "VALUES ('chusan@gmail.com', 'Chủ sân', 'x', 'admin', true)"
            )
        )
    await engine.dispose()
    yield
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
    await server.dispose()


async def state() -> tuple[str, str | None]:
    [(version,)] = await query("SELECT version_num FROM alembic_version")
    [(phone,)] = await query("SELECT phone FROM users WHERE email = 'chusan@gmail.com'")
    return version, phone


async def test_production_needs_a_real_first_admin_phone(legacy_db, monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")

    # Không đặt biến (đang lấy mặc định) -> dừng, dữ liệu không đổi
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", SAMPLE_ADMIN_PHONE)
    monkeypatch.setattr(
        settings, "__pydantic_fields_set__", settings.model_fields_set - {"FIRST_ADMIN_PHONE"}
    )
    assert settings.first_admin_phone_is_sample
    with pytest.raises(RuntimeError, match="FIRST_ADMIN_PHONE"):
        await alembic(command.upgrade, TARGET)
    assert await state() == (BEFORE, None)

    # Đặt rõ nhưng là SĐT mẫu (viết kiểu khác) -> vẫn dừng
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "+84 912 345 678")
    assert "FIRST_ADMIN_PHONE" in settings.model_fields_set
    with pytest.raises(RuntimeError, match="FIRST_ADMIN_PHONE"):
        await alembic(command.upgrade, TARGET)
    assert await state() == (BEFORE, None)

    # SĐT thật -> chạy, Admin nhận SĐT
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", REAL_PHONE)
    await alembic(command.upgrade, TARGET)
    assert await state() == (TARGET, REAL_PHONE)

    # Admin đã có SĐT (lên lại sau downgrade) -> không xét biến nữa
    await alembic(command.downgrade, BEFORE)
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", SAMPLE_ADMIN_PHONE)
    await alembic(command.upgrade, TARGET)
    assert await state() == (TARGET, REAL_PHONE)


async def test_sample_phone_is_fine_outside_production(legacy_db, monkeypatch):
    monkeypatch.setattr(settings, "ENV", "staging")
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", SAMPLE_ADMIN_PHONE)
    assert not settings.first_admin_phone_is_sample
    await alembic(command.upgrade, TARGET)
    assert await state() == (TARGET, SAMPLE_ADMIN_PHONE)

# ruff: noqa: E501
"""QA T-017: migration ``0cbf30ad5193`` (phòng chơi + hộp thư) – nâng, đảo ngược, nâng lại, khớp model.

DB riêng ``<db>_mig_qa17``; không backfill trong migration (phòng do job ``play_rooms_tick`` tạo).
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

BEFORE = "9738bbfe2eb7"
TARGET = "0cbf30ad5193"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa17")
TABLES = {"play_room", "play_room_member", "play_room_request", "play_match", "member_notification"}


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


async def tables() -> set[str]:
    got = await rows("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    return {r[0] for r in got} & TABLES


@pytest.fixture
async def mig_db():
    server = create_async_engine(make_url(REAL_URL).set(database="postgres"))
    server = server.execution_options(isolation_level="AUTOCOMMIT")
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
        await c.execute(text(f"CREATE DATABASE {MIG_URL.database}"))
    await alembic(command.upgrade, BEFORE)
    yield
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
    await server.dispose()


async def test_upgrade_creates_the_five_tables_without_backfilled_rows(mig_db):
    assert await tables() == set()
    await alembic(command.upgrade, TARGET)
    assert await tables() == TABLES
    for t in TABLES:
        assert (await rows(f"SELECT count(*) FROM {t}"))[0][0] == 0, (
            f"{t}: migration không backfill"
        )


async def test_schema_matches_models_and_roundtrip_is_clean(mig_db):
    await alembic(command.upgrade, TARGET)
    await alembic(command.downgrade, BEFORE)
    assert await tables() == set(), "đảo ngược gỡ sạch 5 bảng"
    await alembic(command.upgrade, TARGET)
    assert await tables() == TABLES
    # `alembic check` chỉ chạy được khi DB ở head; các migration sau T-017 làm head đổi -> nâng tới `head`
    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")


async def test_constraints_enforce_unique_room_per_booking_and_member_per_room(mig_db):
    await alembic(command.upgrade, TARGET)
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO customer (kind, member_code, full_name, phone, is_active) VALUES ('member','HV9001','Chủ','0911222333', true)"
                )
            )
            cid = (
                await conn.execute(text("SELECT id FROM customer WHERE phone='0911222333'"))
            ).scalar_one()
            cols = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='play_room' AND is_nullable='NO' AND column_default IS NULL"
                )
            )
            need = {r[0] for r in cols}
        assert "booking_code" in need and "host_customer_id" in need, need
        uniq = await rows(
            "SELECT indexdef FROM pg_indexes WHERE tablename='play_room' AND indexdef ILIKE '%UNIQUE%'"
        )
        assert any("booking_code" in r[0] for r in uniq), (
            "phòng duy nhất theo booking_code (mã con)"
        )
        uniq_m = await rows(
            "SELECT indexdef FROM pg_indexes WHERE tablename='play_room_member' AND indexdef ILIKE '%UNIQUE%'"
        )
        assert any("room_id" in r[0] and "customer_id" in r[0] for r in uniq_m), (
            "một hội viên một dòng trong phòng"
        )
        assert cid
    finally:
        await engine.dispose()

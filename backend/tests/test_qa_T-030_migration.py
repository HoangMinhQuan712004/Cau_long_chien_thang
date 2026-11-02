# ruff: noqa: E501
"""QA T-030: migration ``ee7aaa89b694`` (bảng speed_record) – nâng, đảo ngược, nâng lại, khớp model.

DB riêng ``<db>_mig_qa30``; bảng mới, không backfill.
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

BEFORE = "0cbf30ad5193"
TARGET = "ee7aaa89b694"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa30")


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


async def cols(table: str) -> dict[str, tuple[str, str | None]]:
    got = await rows(
        f"SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='{table}'"
    )
    return {r[0]: (r[1], r[2]) for r in got}


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


async def test_upgrade_creates_speed_record_and_downgrade_drops_it(mig_db):
    assert await cols("speed_record") == {}
    await alembic(command.upgrade, TARGET)
    got = await cols("speed_record")
    assert {
        "id",
        "customer_id",
        "speed_kmh",
        "measured_at",
        "court_code",
        "device_id",
        "source_ref",
        "video_url",
        "created_at",
    } <= set(got), got
    assert (
        got["customer_id"][0] == "NO"
        and got["source_ref"][0] == "NO"
        and got["court_code"][0] == "YES"
    )
    assert (await rows("SELECT count(*) FROM speed_record"))[0][0] == 0
    await alembic(command.downgrade, BEFORE)
    assert await cols("speed_record") == {}


async def test_constraints_and_indexes_exist_after_upgrade(mig_db):
    await alembic(command.upgrade, TARGET)
    checks = await rows(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid WHERE t.relname='speed_record' AND c.contype='c'"
    )
    assert any("speed_kmh" in d[0] and "50" in d[0] and "500" in d[0] for d in checks), checks
    uniq = await rows(
        "SELECT indexdef FROM pg_indexes WHERE tablename='speed_record' AND indexdef ILIKE '%UNIQUE%'"
    )
    assert any("source_ref" in d[0] for d in uniq), uniq
    idx = " ".join(
        r[0] for r in await rows("SELECT indexdef FROM pg_indexes WHERE tablename='speed_record'")
    )
    assert "measured_at" in idx and "customer_id" in idx


async def test_schema_matches_models_and_roundtrip_is_clean(mig_db):
    await alembic(command.upgrade, TARGET)
    await alembic(command.downgrade, BEFORE)
    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")

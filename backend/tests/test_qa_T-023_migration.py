# ruff: noqa: E501
"""QA T-023: migration ``9f73fd765c58`` (checkout.kind + ticket.checkout_id) – nâng, đảo ngược, nâng lại, khớp model.

DB riêng ``<db>_mig_qa23``; dữ liệu cũ không đổi (checkout cũ = ``court``).
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
TARGET = "9f73fd765c58"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa23")


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
        f"SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_schema='booking' AND table_name='{table}'"
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


async def test_upgrade_adds_kind_and_checkout_id_and_downgrade_removes_them(mig_db):
    assert "kind" not in await cols("checkout") and "checkout_id" not in await cols("ticket")
    await alembic(command.upgrade, TARGET)
    kind = (await cols("checkout"))["kind"]
    assert kind[0] == "NO" and "court" in (kind[1] or ""), (
        "checkout.kind bắt buộc, mặc định court (dữ liệu cũ = court)"
    )
    assert (await cols("ticket"))["checkout_id"][0] == "YES", (
        "ticket.checkout_id cho phép NULL (vé quầy)"
    )
    await alembic(command.downgrade, BEFORE)
    assert "kind" not in await cols("checkout") and "checkout_id" not in await cols("ticket")


async def test_kind_only_accepts_court_or_ticket_and_exclusion_constraint_is_untouched(mig_db):
    await alembic(command.upgrade, TARGET)
    defs = await rows(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='booking' AND t.relname='checkout' AND c.contype='c'"
    )
    assert any("kind" in d[0] and "court" in d[0] and "ticket" in d[0] for d in defs), defs
    ex = await rows("SELECT conname FROM pg_constraint WHERE conname='ex_allocation_no_overlap'")
    assert ex, "exclusion constraint chống trùng lịch không đổi"
    hold_defs = await rows(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='booking' AND t.relname='hold' AND c.contype='c'"
    )
    assert any("seat" in d[0] for d in hold_defs), "hold kind seat vẫn có"


async def test_schema_matches_models_and_roundtrip_is_clean(mig_db):
    await alembic(command.upgrade, TARGET)
    await alembic(command.downgrade, BEFORE)
    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")

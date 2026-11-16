"""T-048: migration ``a4c91e7d2f58`` (speed_record.video_set_at) – điền cũ, check, up/down/up.

DB riêng ``<db>_mig_t048``.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import BACKEND_DIR

BEFORE = "d5cf1587486a"
TARGET = "a4c91e7d2f58"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_t048")

CREATED = datetime(2026, 1, 1, tzinfo=UTC)
PASTED_1 = datetime(2026, 2, 1, tzinfo=UTC)
PASTED_2 = datetime(2026, 3, 1, tzinfo=UTC)
LATER = datetime(2026, 4, 1, tzinfo=UTC)
YT = "https://youtu.be/dQw4w9WgXcQ"


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


async def fetch(sql: str, **params) -> list:
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql), params)).all())
    finally:
        await engine.dispose()


async def write(sql: str, **params) -> None:
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)
    finally:
        await engine.dispose()


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


async def old_record(rid: int, url: str | None) -> None:
    await write(
        "INSERT INTO speed_record (id, customer_id, speed_kmh, measured_at, source_ref, video_url,"
        " created_at) VALUES (:id, 1, 200, :at, :ref, :url, :at)",
        id=rid,
        at=CREATED,
        ref=f"mig:{rid}",
        url=url,
    )


async def audit_row(action: str, code: str, at: datetime, entity_type: str = "speed_record"):
    await write(
        "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type, entity_code)"
        " VALUES (:at, 'admin', 'Admin', :action, :entity, :code)",
        at=at,
        action=action,
        entity=entity_type,
        code=code,
    )


async def set_at(rid: int) -> datetime | None:
    return (await fetch("SELECT video_set_at FROM speed_record WHERE id = :id", id=rid))[0][0]


async def test_backfill_uses_latest_video_set_audit_then_created_at(mig_db):
    await old_record(1, YT)  # có nhật ký
    await old_record(2, YT)  # không có nhật ký (Admin nhập / hội viên gửi kèm link)
    await old_record(3, None)  # không có video, dù từng có nhật ký gắn rồi gỡ
    await audit_row("record.video_set", "1", PASTED_1)
    await audit_row("record.video_set", "1", PASTED_2)
    await audit_row("record.video_removed", "1", LATER)  # không phải lần dán
    await audit_row("record.video_set", "3", PASTED_1)
    await audit_row("record.video_set", "2", LATER, entity_type="other")  # mã trùng, thực thể khác

    await alembic(command.upgrade, TARGET)

    assert await set_at(1) == PASTED_2
    assert await set_at(2) == CREATED
    assert await set_at(3) is None


async def test_check_rejects_mismatch(mig_db):
    await alembic(command.upgrade, TARGET)
    await old_record(1, None)
    with pytest.raises(DBAPIError, match="speed_video_set_at"):
        await write("UPDATE speed_record SET video_url = :url WHERE id = 1", url=YT)
    with pytest.raises(DBAPIError, match="speed_video_set_at"):
        await write("UPDATE speed_record SET video_set_at = now() WHERE id = 1")
    await write(
        "UPDATE speed_record SET video_url = :url, video_set_at = now() WHERE id = 1", url=YT
    )


async def test_downgrade_keeps_rows_and_roundtrip_is_clean(mig_db):
    await old_record(1, YT)
    await alembic(command.upgrade, TARGET)
    await alembic(command.downgrade, BEFORE)
    columns = await fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'speed_record'"
    )
    assert "video_set_at" not in {c[0] for c in columns}
    assert (await fetch("SELECT video_url FROM speed_record WHERE id = 1"))[0][0] == YT
    await alembic(command.upgrade, "head")
    assert await set_at(1) == CREATED
    await alembic(lambda cfg, _rev: command.check(cfg), "head")

# ruff: noqa: E501
"""QA T-047: migration ``5b7e2c9d41a3`` (speed_record: source/status/duyệt/version) – dữ liệu cũ, đảo ngược, khớp model.

DB riêng ``<db>_mig_qa47``. Bản ghi cũ phải thành device / approved; downgrade bỏ bản chưa duyệt / bị từ chối.
"""

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.conftest import BACKEND_DIR

BEFORE = "73296951e195"
TARGET = "5b7e2c9d41a3"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa47")


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


async def run(sql: str, *, commit: bool = False):
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() if commit else engine.connect() as conn:
            res = await conn.execute(text(sql))
            return None if commit else res.all()
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


async def seed_old_rows() -> None:
    await run(
        "INSERT INTO customer (kind, member_code, full_name, phone, is_active) VALUES ('member','HVQA47','QA Mig','0900000047',true)",
        commit=True,
    )
    await run(
        "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) "
        "SELECT id, 300, now() - interval '2 days', 'old-1' FROM customer WHERE phone='0900000047'",
        commit=True,
    )


async def test_old_rows_become_device_approved_and_defaults_apply(mig_db):
    await seed_old_rows()
    await alembic(command.upgrade, TARGET)
    row = (
        await run(
            "SELECT source, status, version, submitted_by, reviewed_by, reject_reason, updated_at = created_at FROM speed_record WHERE source_ref='old-1'"
        )
    )[0]
    assert tuple(row) == ("device", "approved", 1, None, None, None, True)
    # bản ghi mới không nêu cột -> mặc định device/approved/version 1 (máy đo cũ không phải sửa)
    await run(
        "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) SELECT id, 301, now(), 'dev-2' FROM customer WHERE phone='0900000047'",
        commit=True,
    )
    row = (await run("SELECT source, status, version FROM speed_record WHERE source_ref='dev-2'"))[
        0
    ]
    assert tuple(row) == ("device", "approved", 1)


async def test_constraints_reject_bad_source_status_and_rejected_without_reason(mig_db):
    await seed_old_rows()
    await alembic(command.upgrade, TARGET)
    base = "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref, source, status, reject_reason) SELECT id, 200, now(), '{ref}', '{src}', '{st}', {rr} FROM customer WHERE phone='0900000047'"
    for ref, src, st, rr in (
        ("b1", "robot", "approved", "NULL"),
        ("b2", "member", "weird", "NULL"),
        ("b3", "member", "rejected", "NULL"),
    ):
        with pytest.raises(DBAPIError):
            await run(base.format(ref=ref, src=src, st=st, rr=rr), commit=True)
    with pytest.raises(DBAPIError):  # lý do > 200 ký tự
        await run(
            base.format(ref="b4", src="member", st="rejected", rr=f"'{'x' * 201}'"), commit=True
        )
    await run(base.format(ref="ok1", src="member", st="rejected", rr="'ok'"), commit=True)
    await run(base.format(ref="ok2", src="admin", st="approved", rr="NULL"), commit=True)
    idx = " ".join(
        r[0] for r in await run("SELECT indexdef FROM pg_indexes WHERE tablename='speed_record'")
    )
    assert "status" in idx and "measured_at" in idx


async def test_downgrade_drops_pending_and_rejected_but_keeps_approved_rows(mig_db):
    await seed_old_rows()
    await alembic(command.upgrade, TARGET)
    ins = "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref, source, status, reject_reason) SELECT id, {k}, now(), '{ref}', '{src}', '{st}', {rr} FROM customer WHERE phone='0900000047'"
    await run(ins.format(k=210, ref="p", src="member", st="pending", rr="NULL"), commit=True)
    await run(ins.format(k=220, ref="r", src="member", st="rejected", rr="'x'"), commit=True)
    await run(ins.format(k=230, ref="a", src="admin", st="approved", rr="NULL"), commit=True)
    await alembic(command.downgrade, BEFORE)
    refs = sorted(r[0] for r in await run("SELECT source_ref FROM speed_record"))
    assert refs == ["a", "old-1"], "chỉ bản đã duyệt còn lại; pending / rejected bị bỏ"
    cols = {
        r[0]
        for r in await run(
            "SELECT column_name FROM information_schema.columns WHERE table_name='speed_record'"
        )
    }
    assert not cols & {
        "source",
        "status",
        "version",
        "updated_at",
        "reject_reason",
        "submitted_by",
        "reviewed_by",
        "reviewed_at",
    }


async def test_schema_matches_models_and_roundtrip_is_clean(mig_db):
    await seed_old_rows()
    await alembic(command.upgrade, TARGET)
    await alembic(command.downgrade, BEFORE)
    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")
    row = (await run("SELECT source, status FROM speed_record WHERE source_ref='old-1'"))[0]
    assert tuple(row) == ("device", "approved")

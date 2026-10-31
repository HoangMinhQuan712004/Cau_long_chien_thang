# ruff: noqa: E501
"""QA T-019 AC6: migration ``5b98d354dd77`` trên dữ liệu kiểu cũ – kiểm độc lập với test của BACKEND.

DB riêng ``<db>_mig_qa19``. Khác test BE: có ``code_sequence`` như dev thật (mã không được cấp lại),
``alembic check`` sau nâng cấp, exclusion constraint trên dữ liệu đã chuyển, vòng lên-xuống-lên,
ảnh chụp khách ở đơn, và khung của lượt chờ thanh toán đã được nhả.
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

BEFORE = "a3d81f5c2b6e"
TARGET = "5b98d354dd77"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa19")

CUSTOMER = "'x', 'temp', 'Khách', '0900000001'"
LEGACY = f"""
INSERT INTO booking.tenant (id, code, name, settings) VALUES (1, 't', 'T', '{{}}'::jsonb)
    ON CONFLICT DO NOTHING;
INSERT INTO booking.resource_type (id, tenant_id, code, name) VALUES (101, 1, 'mig', 'Mig');
INSERT INTO booking.resource (id, tenant_id, code, name, resource_type_id)
    VALUES (101, 1, 'M01', 'Sân M1', 101), (102, 1, 'M02', 'Sân M2', 101);
-- Lượt online đã thanh toán, 2 khối (mã cũ: mỗi khối một mã, pay_ref = mã đầu)
INSERT INTO booking.checkout (id, tenant_id, token_hash, pay_ref, play_date, amount, status,
    expires_at, customer_ref, customer_kind, customer_name, customer_phone)
    VALUES ('00000000-0000-0000-0000-000000000001', 1, 'a', 'BK20261101001', '2026-11-01',
    200000, 'paid', now(), {CUSTOMER});
INSERT INTO booking.hold (id, tenant_id, kind, checkout_id, code, amount, expires_at, status)
    VALUES ('00000000-0000-0000-0000-0000000000a1', 1, 'court',
            '00000000-0000-0000-0000-000000000001', 'BK-20261101-001', 100000, now(), 'converted'),
           ('00000000-0000-0000-0000-0000000000a2', 1, 'court',
            '00000000-0000-0000-0000-000000000001', 'BK-20261101-002', 100000, now(), 'converted');
INSERT INTO booking.booking (id, tenant_id, code, source, resource_id, play_date, start_at, end_at,
    amount, payment_status, payment_method, paid_at, created_by_type, created_by_label,
    checkout_id, customer_ref, customer_kind, customer_name, customer_phone)
    VALUES (1, 1, 'BK-20261101-001', 'online', 101, '2026-11-01', '2026-11-01 10:00+07',
            '2026-11-01 11:00+07', 100000, 'paid', 'online_transfer', now(), 'web', 'Web',
            '00000000-0000-0000-0000-000000000001', {CUSTOMER}),
           (2, 1, 'BK-20261101-002', 'online', 102, '2026-11-01', '2026-11-01 10:00+07',
            '2026-11-01 11:00+07', 100000, 'paid', 'online_transfer', now(), 'web', 'Web',
            '00000000-0000-0000-0000-000000000001', {CUSTOMER}),
           (3, 1, 'BK-20261101-003', 'counter', 101, '2026-11-01', '2026-11-01 12:00+07',
            '2026-11-01 13:00+07', 90000, 'unpaid', NULL, NULL, 'staff', 'NV001',
            NULL, {CUSTOMER});
INSERT INTO booking.allocation (tenant_id, resource_id, time_range, kind, booking_id, owner_code)
    VALUES (1, 101, '[2026-11-01 10:00+07,2026-11-01 11:00+07)', 'booking', 1, 'BK-20261101-001'),
           (1, 102, '[2026-11-01 10:00+07,2026-11-01 11:00+07)', 'booking', 2, 'BK-20261101-002'),
           (1, 101, '[2026-11-01 12:00+07,2026-11-01 13:00+07)', 'booking', 3, 'BK-20261101-003');
-- Lượt đang chờ thanh toán: migration cho hết hạn, nhả khung
INSERT INTO booking.checkout (id, tenant_id, token_hash, pay_ref, play_date, amount, status,
    expires_at, customer_ref, customer_kind, customer_name, customer_phone)
    VALUES ('00000000-0000-0000-0000-000000000002', 1, 'b', 'BK20261101004', '2026-11-01',
    100000, 'pending', now() + interval '5 minutes', 'y', 'temp', 'Khách B', '0900000002');
INSERT INTO booking.hold (id, tenant_id, kind, checkout_id, code, amount, expires_at, status)
    VALUES ('00000000-0000-0000-0000-0000000000b1', 1, 'court',
            '00000000-0000-0000-0000-000000000002', 'BK-20261101-004', 100000,
            now() + interval '5 minutes', 'active');
INSERT INTO booking.allocation (tenant_id, resource_id, time_range, kind, hold_id, owner_code)
    VALUES (1, 102, '[2026-11-01 14:00+07,2026-11-01 15:00+07)', 'hold',
            '00000000-0000-0000-0000-0000000000b1', 'BK-20261101-004')
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


SEQUENCE = """
INSERT INTO booking.code_sequence (tenant_id, prefix, day, last_value)
    VALUES (1, 'BK', '2026-11-01', 4) ON CONFLICT (tenant_id, prefix, day) DO UPDATE SET last_value = 4
"""


@pytest.fixture
async def legacy_db():
    server = create_async_engine(make_url(REAL_URL).set(database="postgres"))
    server = server.execution_options(isolation_level="AUTOCOMMIT")
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
        await c.execute(text(f"CREATE DATABASE {MIG_URL.database}"))
    await alembic(command.upgrade, BEFORE)
    await run(LEGACY + ";\n" + SEQUENCE)
    yield
    async with server.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_URL.database} WITH (FORCE)"))
    await server.dispose()


async def test_ac6_codes_sequence_and_snapshots(legacy_db):
    await alembic(command.upgrade, TARGET)
    orders = await rows(
        "SELECT code, channel, play_date::text, customer_name, created_by_label "
        "FROM booking.booking_order ORDER BY code"
    )
    assert [o[0] for o in orders] == ["BK-20261101-001", "BK-20261101-002", "BK-20261101-003"]
    assert [o[1] for o in orders] == ["online", "online", "counter"]
    assert {o[2] for o in orders} == {"2026-11-01"}
    assert orders[2][3] == "Khách" and orders[2][4] == "NV001", "snapshot copied from the booking"
    # mã đã cấp không được cấp lại: dãy của ngày chơi vẫn >= mã lớn nhất đã dùng (4)
    seq = await rows("SELECT last_value FROM booking.code_sequence WHERE day = '2026-11-01'")
    assert seq and all(s[0] >= 4 for s in seq), seq
    unique = await rows("SELECT count(*), count(DISTINCT code) FROM booking.booking_order")
    assert unique == [(3, 3)]
    pending = await rows("SELECT status FROM booking.checkout WHERE pay_ref = 'BK20261101004'")
    assert pending == [("expired",)], "AC6: a pending checkout is expired by the migration"


async def test_ac6_exclusion_constraint_unchanged_and_released_slot_is_free(legacy_db):
    await alembic(command.upgrade, TARGET)
    # khung đã đặt (M01 10:00-11:00) vẫn chặn đặt chồng
    with pytest.raises(Exception, match="allocation|exclusion|conflict"):
        await run(
            "INSERT INTO booking.allocation (tenant_id, resource_id, time_range, kind, booking_id, owner_code) "
            "VALUES (1, 101, '[2026-11-01 10:30+07,2026-11-01 11:30+07)', 'booking', 1, 'X')"
        )
    # khung của lượt chờ đã hết hạn (M02 14:00-15:00) được nhả: đặt lại được
    await run(
        "INSERT INTO booking.allocation (tenant_id, resource_id, time_range, kind, booking_id, owner_code) "
        "VALUES (1, 102, '[2026-11-01 14:00+07,2026-11-01 15:00+07)', 'booking', 3, 'FREED')"
    )
    assert await rows("SELECT count(*) FROM booking.allocation WHERE owner_code='FREED'") == [(1,)]


async def test_ac6_schema_matches_models_after_upgrade(legacy_db):
    await alembic(command.upgrade, TARGET)
    await alembic(
        lambda cfg, _rev: command.check(cfg), TARGET
    )  # raises if autogenerate finds a diff


async def test_ac6_up_down_up_roundtrip_is_stable(legacy_db):
    await alembic(command.upgrade, TARGET)
    first = await rows("SELECT code, seq FROM booking.booking ORDER BY code")
    await alembic(command.downgrade, BEFORE)
    assert [r[0] for r in await rows("SELECT code FROM booking.booking ORDER BY code")] == [
        "BK-20261101-001",
        "BK-20261101-002",
        "BK-20261101-003",
    ]
    await alembic(command.upgrade, TARGET)
    assert await rows("SELECT code, seq FROM booking.booking ORDER BY code") == first
    assert await rows("SELECT count(*) FROM booking.booking WHERE order_id IS NULL") == [(0,)]

"""T-019 AC6: migration ``5b98d354dd77`` trên dữ liệu kiểu cũ (mỗi khối một mã).

Dựng DB riêng ``<db>_mig_t019`` ở revision trước (``dad220bfc992``), nạp dữ liệu cũ bằng SQL,
nâng cấp rồi kiểm; sau đó hạ cấp. Không đụng DB test chính.
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

BEFORE = "dad220bfc992"
TARGET = "5b98d354dd77"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_t019")

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


async def test_old_bookings_become_orders(legacy_db):
    await alembic(command.upgrade, TARGET)

    orders = await rows(
        "SELECT code, channel, checkout_id IS NOT NULL FROM booking.booking_order ORDER BY code"
    )
    assert orders == [
        ("BK-20261101-001", "online", True),  # mã đơn của lượt = mã đã làm pay_ref
        ("BK-20261101-002", "online", False),
        ("BK-20261101-003", "counter", False),
    ]
    blocks = await rows(
        "SELECT b.code, b.seq, o.code FROM booking.booking b "
        "JOIN booking.booking_order o ON o.id = b.order_id ORDER BY b.code"
    )
    assert blocks == [
        ("BK-20261101-001-01", 1, "BK-20261101-001"),
        ("BK-20261101-002-01", 1, "BK-20261101-002"),
        ("BK-20261101-003-01", 1, "BK-20261101-003"),
    ]
    holds = await rows("SELECT code, status FROM booking.hold ORDER BY code")
    assert holds == [
        ("BK-20261101-001-01", "converted"),
        ("BK-20261101-002-01", "converted"),
        ("BK-20261101-004-01", "expired"),
    ]
    checkouts = await rows(
        "SELECT pay_ref, order_code, status FROM booking.checkout ORDER BY pay_ref"
    )
    assert checkouts == [
        ("BK20261101001", "BK-20261101-001", "paid"),
        ("BK20261101004", "BK-20261101-004", "expired"),
    ]
    allocs = await rows("SELECT owner_code, active FROM booking.allocation ORDER BY owner_code")
    assert allocs == [
        ("BK-20261101-001-01", True),
        ("BK-20261101-002-01", True),
        ("BK-20261101-003-01", True),
        ("BK-20261101-004-01", False),  # giữ chỗ chờ thanh toán đã nhả khung
    ]

    # Hạ cấp: trả mã cũ
    await alembic(command.downgrade, BEFORE)
    assert await rows("SELECT code FROM booking.booking ORDER BY code") == [
        ("BK-20261101-001",),
        ("BK-20261101-002",),
        ("BK-20261101-003",),
    ]
    assert [r[0] for r in await rows("SELECT code FROM booking.hold ORDER BY code")] == [
        "BK-20261101-001",
        "BK-20261101-002",
        "BK-20261101-004",
    ]


async def test_downgrade_refuses_multi_block_orders(legacy_db):
    await alembic(command.upgrade, TARGET)
    await run(
        "UPDATE booking.booking SET order_id = "
        "(SELECT id FROM booking.booking_order WHERE code = 'BK-20261101-001'), seq = 2, "
        "code = 'BK-20261101-001-02' WHERE id = 2"
    )
    with pytest.raises(RuntimeError, match="nhiều khối"):
        await alembic(command.downgrade, BEFORE)
    assert await rows("SELECT version_num FROM alembic_version") == [(TARGET,)]

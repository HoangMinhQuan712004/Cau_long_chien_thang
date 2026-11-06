"""T-051: migration ``c7e2a91f4d36`` – up / down / up sạch, dữ liệu cũ không đổi, downgrade từ chối
khi đã có dòng ``cancelled``, exclusion constraint không đổi. DB riêng ``<db>_mig_t051``.
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

BEFORE = "a4c91e7d2f58"
TARGET = "c7e2a91f4d36"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_t051")
EXCLUSION = """
    SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c
    WHERE c.conname = 'ex_allocation_no_overlap'
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


async def fetch(sql: str) -> list:
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).all())
    finally:
        await engine.dispose()


async def write(*statements: str) -> None:
    """Bỏ qua khóa ngoại (``replica``): chỉ cần dòng vé để kiểm check, không dựng cả sự kiện."""
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in statements:
                await conn.execute(text(sql))
    finally:
        await engine.dispose()


def ticket(code: str, seq: int, **columns: str) -> str:
    values = {
        "tenant_id": "1",
        "session_id": "1",
        "seq": str(seq),
        "code": f"'{code}'",
        "source": "'counter'",
        "amount": "50000",
        "customer_ref": "'1'",
        "customer_kind": "'temp'",
        "customer_name": "'Khách'",
        "customer_phone": "'0900000000'",
        "created_by_type": "'admin'",
        "created_by_label": "'Admin'",
        **columns,
    }
    return f"INSERT INTO booking.ticket ({', '.join(values)}) VALUES ({', '.join(values.values())})"


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


async def test_old_rows_unchanged_and_roundtrip_is_clean(mig_db):
    exclusion = await fetch(EXCLUSION)
    assert exclusion
    await write(ticket("SK-V01", 1))
    await alembic(command.upgrade, TARGET)
    row = (await fetch("SELECT payment_status, refund_amount, cancel_reason FROM booking.ticket"))[
        0
    ]
    assert tuple(row) == ("unpaid", 0, None)
    assert await fetch(EXCLUSION) == exclusion

    await alembic(command.downgrade, BEFORE)
    assert (await fetch("SELECT payment_status FROM booking.ticket"))[0][0] == "unpaid"
    columns = await fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'booking' AND table_name IN ('booking', 'ticket') "
        "AND column_name IN ('cancel_reason', 'refund_amount')"
    )
    assert columns == []
    with pytest.raises(DBAPIError, match="payment_status"):
        await write(ticket("SK-V02", 2, payment_status="'cancelled'", cancel_reason="'x'"))

    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")


async def test_checks_and_downgrade_refuses_cancelled_rows(mig_db):
    await alembic(command.upgrade, TARGET)
    for bad in (
        {"payment_status": "'cancelled'"},  # thiếu lý do + thời điểm
        {"payment_status": "'cancelled'", "cancel_reason": "'x'"},
        {"refund_amount": "50001"},
        {"refund_amount": "-1"},
    ):
        with pytest.raises(DBAPIError, match="ck_ticket"):
            await write(ticket("SK-V03", 3, **bad))
    await write(
        ticket(
            "SK-V04",
            4,
            payment_status="'cancelled'",
            cancel_reason="'Khách báo bận'",
            cancelled_at="now()",
            refund_amount="50000",
        )
    )
    with pytest.raises(RuntimeError, match="cancelled rows"):
        await alembic(command.downgrade, BEFORE)
    assert (await fetch("SELECT count(*) FROM booking.ticket"))[0][0] == 1

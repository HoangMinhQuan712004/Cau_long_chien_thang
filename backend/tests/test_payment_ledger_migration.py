"""T-057: migration ``e3a17c9b5d24`` (sổ tiền vào) – backfill đúng khóa gộp, tổng sổ khớp tiền đã
thu / đã hoàn trên booking + vé, up / down / up sạch. DB riêng ``<db>_mig_t057``.
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

BEFORE = "bb86440fad96"
TARGET = "e3a17c9b5d24"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_t057")

T1 = "'2026-11-01 10:00+07'"
T2 = "'2026-11-02 11:00+07'"
T3 = "'2026-11-03 12:00+07'"
T4 = "'2026-11-05 09:00+07'"
T5 = "'2026-11-06 09:00+07'"
T6 = "'2026-11-07 09:00+07'"
CUSTOMER = {
    "customer_ref": "'1'",
    "customer_kind": "'temp'",
    "customer_name": "'Khách Cũ'",
    "customer_phone": "'0900000000'",
}
NV1 = {"collected_by_type": "'staff'", "collected_by_id": "7", "collected_by_label": "'NV001'"}


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
    """Bỏ qua khóa ngoại (``replica``): không dựng sân, tenant thật – chỉ cần dòng để gộp."""
    engine = create_async_engine(MIG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            for sql in statements:
                await conn.execute(text(sql))
    finally:
        await engine.dispose()


def insert(table: str, **values: str) -> str:
    return (
        f"INSERT INTO booking.{table} ({', '.join(values)}) VALUES ({', '.join(values.values())})"
    )


def order(oid: int, code: str, channel: str = "'counter'") -> str:
    return insert(
        "booking_order",
        id=str(oid),
        tenant_id="1",
        code=f"'{code}'",
        play_date="'2026-11-10'",
        channel=channel,
        created_by_label="'Admin'",
        **CUSTOMER,
    )


def booking(bid: int, oid: int, seq: int, amount: int, **columns: str) -> str:
    return insert(
        "booking",
        id=str(bid),
        tenant_id="1",
        order_id=str(oid),
        seq=str(seq),
        code=f"'BK-{oid}-{seq:02d}'",
        source="'counter'",
        resource_id="1",
        play_date="'2026-11-10'",
        start_at="'2026-11-10 18:00+07'",
        end_at="'2026-11-10 19:00+07'",
        amount=str(amount),
        created_by_type="'admin'",
        created_by_label="'Admin'",
        **CUSTOMER,
        **columns,
    )


def ticket(tid: int, seq: int, amount: int, ref: str, **columns: str) -> str:
    return insert(
        "ticket",
        id=str(tid),
        tenant_id="1",
        session_id="1",
        seq=str(seq),
        code=f"'SK-V{seq:02d}'",
        source="'counter'",
        amount=str(amount),
        created_by_type="'admin'",
        created_by_label="'Admin'",
        **{**CUSTOMER, "customer_ref": f"'{ref}'"},
        **columns,
    )


def paid(at: str, method: str = "'cash'", **who: str) -> dict:
    return {"payment_status": "'paid'", "payment_method": method, "paid_at": at, **(who or NV1)}


def cancelled(paid_at: str, at: str, refund: int) -> dict:
    return {
        **paid(paid_at),
        "payment_status": "'cancelled'",
        "cancel_reason": "'Khách báo bận'",
        "cancelled_at": at,
        "cancelled_by_type": "'admin'",
        "cancelled_by_id": "1",
        "cancelled_by_label": "'Admin'",
        "refund_amount": str(refund),
    }


ONLINE = {"collected_by_type": "'web'", "collected_by_label": "'Khách đặt online'"}


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


async def test_backfill_groups_each_payment_and_totals_match(mig_db):
    await write(
        order(1, "BK-20261110-001"),
        order(2, "BK-20261110-002", channel="'online'"),
        insert(
            "session",
            id="1",
            tenant_id="1",
            code="'BK-20261110-003'",
            name="'Giao lưu'",
            play_date="'2026-11-10'",
            start_at="'2026-11-10 19:00+07'",
            end_at="'2026-11-10 21:00+07'",
            capacity="10",
            ticket_price="30000",
            created_by_type="'admin'",
            created_by_label="'Admin'",
        ),
        # Đơn quầy: 3 khối thu cùng lần (một bị hủy sau, có hoàn), 1 khối thu lần khác, 1 chưa thu
        booking(1, 1, 1, 100_000, **paid(T1)),
        booking(2, 1, 2, 50_000, **paid(T1)),
        booking(3, 1, 3, 60_000, **cancelled(T1, T4, 60_000)),
        booking(4, 1, 4, 70_000, **paid(T2)),
        booking(5, 1, 5, 40_000),
        booking(6, 1, 6, 0, **paid(T2)),  # khối 0 đ: không có mục
        # Đơn online: một giao dịch SePay cho 2 khối
        booking(
            7, 2, 1, 80_000, gateway_ref="'sepay:555:1'", **paid(T3, "'online_transfer'", **ONLINE)
        ),
        booking(
            8, 2, 2, 90_000, gateway_ref="'sepay:555:2'", **paid(T3, "'online_transfer'", **ONLINE)
        ),
        # Vé: hai khách khác nhau thu cùng lúc -> hai dòng; một vé hủy có hoàn
        ticket(1, 1, 30_000, "a", **paid(T2)),
        ticket(2, 2, 30_000, "b", **cancelled(T2, T5, 30_000)),
        # Dữ liệu trước T-019: một giao dịch SePay trả 2 khối, bị tách thành 2 đơn -> một dòng sổ,
        # mã đơn nhỏ nhất (Sửa 09/11). Vé: một giao dịch trả 2 vé -> một dòng.
        order(5, "BK-20261110-005", channel="'online'"),
        order(4, "BK-20261110-004", channel="'online'"),
        booking(
            9,
            5,
            1,
            300_000,
            gateway_ref="'sepay:42637:2'",
            **paid(T6, "'online_transfer'", **ONLINE),
        ),
        booking(
            10,
            4,
            1,
            300_000,
            gateway_ref="'sepay:42637:1'",
            **paid(T6, "'online_transfer'", **ONLINE),
        ),
        ticket(
            3,
            3,
            30_000,
            "c",
            gateway_ref="'sepay:888:1'",
            **paid(T6, "'online_transfer'", **ONLINE),
        ),
        ticket(
            4,
            4,
            30_000,
            "d",
            gateway_ref="'sepay:888:2'",
            **paid(T6, "'online_transfer'", **ONLINE),
        ),
    )
    await alembic(command.upgrade, TARGET)

    rows = await fetch(
        "SELECT e.kind, e.method, e.source, e.amount, e.order_code, e.actor_label, e.reference, "
        "count(i.id), sum(i.amount) FROM booking.payment_entry e "
        "JOIN booking.payment_entry_item i ON i.entry_id = e.id "
        "GROUP BY e.id ORDER BY e.occurred_at, e.kind, e.amount"
    )
    assert [tuple(r) for r in rows] == [
        ("in", "cash", "counter", 210_000, "BK-20261110-001", "NV001", None, 3, 210_000),
        ("in", "cash", "counter", 30_000, "BK-20261110-003", "NV001", None, 1, 30_000),
        ("in", "cash", "counter", 30_000, "BK-20261110-003", "NV001", None, 1, 30_000),
        ("in", "cash", "counter", 70_000, "BK-20261110-001", "NV001", None, 1, 70_000),
        ("in", "online_transfer", "online", 170_000, "BK-20261110-002", "Hệ thống", "sepay:555", 2,
         170_000),
        ("refund", "cash", "counter", 60_000, "BK-20261110-001", "Admin", None, 1, 60_000),
        ("refund", "cash", "counter", 30_000, "BK-20261110-003", "Admin", None, 1, 30_000),
        ("in", "online_transfer", "online", 60_000, "BK-20261110-003", "Hệ thống", "sepay:888", 2,
         60_000),
        ("in", "online_transfer", "online", 600_000, "BK-20261110-004", "Hệ thống", "sepay:42637",
         2, 600_000),
    ]  # fmt: skip

    # Cổng AC8: Σ in − Σ refund của sổ = Σ đã thu − Σ đã hoàn trên booking + vé
    [(ledger,)] = await fetch(
        "SELECT sum(CASE WHEN kind = 'in' THEN amount ELSE -amount END) FROM booking.payment_entry"
    )
    [(source,)] = await fetch(
        "SELECT sum(CASE WHEN paid_at IS NOT NULL AND payment_status IN ('paid', 'cancelled') "
        "THEN amount ELSE 0 END) - sum(refund_amount) FROM ("
        "SELECT paid_at, payment_status, amount, refund_amount FROM booking.booking UNION ALL "
        "SELECT paid_at, payment_status, amount, refund_amount FROM booking.ticket) x"
    )
    assert ledger == source == 210_000 + 70_000 + 170_000 + 60_000 + 600_000 + 60_000 - 90_000
    await write(entry())  # dãy id tiếp tục sau backfill (không đụng id đã dùng)

    await alembic(command.downgrade, BEFORE)
    assert (
        await fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'booking' "
            "AND table_name LIKE 'payment_entry%'"
        )
        == []
    )
    assert (await fetch("SELECT count(*) FROM booking.booking"))[0][0] == 10
    await alembic(command.upgrade, "head")
    assert (await fetch("SELECT count(*) FROM booking.payment_entry"))[0][0] == 9
    await alembic(lambda cfg, _rev: command.check(cfg), "head")


def entry(**over: str) -> str:
    values = {
        "tenant_id": "1",
        "kind": "'in'",
        "method": "'online_transfer'",
        "source": "'online'",
        "amount": "1000",
        "occurred_at": "now()",
        "customer_name": "'x'",
        "customer_phone": "'0900000000'",
        "actor_type": "'system'",
        "actor_label": "'Hệ thống'",
        **over,
    }
    return insert("payment_entry", **values)


async def test_reference_is_unique_per_tenant_and_checks_hold(mig_db):
    await alembic(command.upgrade, TARGET)
    await write(
        entry(reference="'sepay:1'"), entry(), entry()
    )  # không có reference: không giới hạn
    with pytest.raises(DBAPIError, match="uq_payment_entry_tenant_reference"):
        await write(entry(reference="'sepay:1'"))
    for bad in ({"amount": "0"}, {"kind": "'out'"}, {"source": "'bank'"}, {"method": "'card'"}):
        with pytest.raises(DBAPIError, match="ck_payment_entry"):
            await write(entry(**bad))

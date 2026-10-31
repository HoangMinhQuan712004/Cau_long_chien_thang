# ruff: noqa: E501
"""QA T-021 AC7: migration ``9738bbfe2eb7`` (backfill hội viên) – kiểm độc lập với test của BACKEND.

DB riêng ``<db>_mig_qa21``: Admin/NV đã xác minh, tài khoản khóa, chưa xác minh, SĐT lạ định dạng, mã HV đang có,
hồ sơ tạm, thứ tự cấp mã theo thời điểm xác minh, nhật ký Hệ thống, đảo ngược + nâng lại không backfill hai lần.
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

BEFORE = "5b98d354dd77"
TARGET = "9738bbfe2eb7"
REAL_URL = settings.DATABASE_URL
MIG_URL = make_url(REAL_URL).set(database=f"{make_url(REAL_URL).database}_mig_qa21")

LEGACY = """
INSERT INTO customer (kind, member_code, full_name, phone, is_active)
    VALUES ('member', 'HV0007', 'Hội Viên Quầy', '0911000005', true),
           ('temp', NULL, 'Hồ Sơ Tạm Giữ Tên', '0911000002', true);
INSERT INTO users (phone, full_name, role, is_active, phone_verified_at, hashed_password)
    VALUES ('0911000003', 'Xác Minh Sau', 'member', true, now() - interval '1 day', 'x'),
           ('0911000001', 'Xác Minh Trước', 'member', true, now() - interval '3 day', 'x'),
           ('0911000002', 'Tên Tài Khoản Tạm', 'member', true, now() - interval '2 day', 'x'),
           ('0911000004', 'Chưa Xác Minh', 'member', true, NULL, 'x'),
           ('0911000005', 'Đã Là Hội Viên', 'member', true, now(), 'x'),
           ('0911000006', 'Tài Khoản Khóa', 'member', false, now(), 'x'),
           ('+84911000007', 'Định Dạng Lạ', 'member', true, now(), 'x'),
           ('0911000008', 'Quản Trị Viên', 'admin', true, now(), 'x'),
           ('0911000009', 'Nhân Viên', 'staff', true, now(), 'x')
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


async def test_backfill_scope_codes_order_and_source(legacy_db):
    await alembic(command.upgrade, TARGET)
    got = await rows(
        "SELECT phone, kind, member_code, full_name, source, is_active FROM customer ORDER BY phone"
    )
    by = {r[0]: r for r in got}
    # chỉ tài khoản member, hoạt động, SĐT đã xác minh, định dạng 0xxxxxxxxx, chưa có hồ sơ hội viên
    assert set(by) == {"0911000001", "0911000002", "0911000003", "0911000005"}, set(by)
    assert by["0911000005"][1:5] == ("member", "HV0007", "Hội Viên Quầy", "counter"), (
        "hội viên quầy giữ nguyên"
    )
    # thứ tự cấp mã theo thời điểm xác minh (cũ nhất trước), tiếp sau mã lớn nhất đang có (HV0007)
    assert (
        by["0911000001"][2] == "HV0008"
        and by["0911000002"][2] == "HV0009"
        and by["0911000003"][2] == "HV0010"
    )
    assert (
        by["0911000001"][1] == "member"
        and by["0911000001"][3] == "Xác Minh Trước"
        and by["0911000001"][4] == "self_register"
    )
    # hồ sơ tạm được nâng, giữ họ tên của hồ sơ
    assert (
        by["0911000002"][1] == "member"
        and by["0911000002"][3] == "Hồ Sơ Tạm Giữ Tên"
        and by["0911000002"][4] == "self_register"
    )
    assert len(got) == 4, (
        "không tạo hồ sơ cho Admin/NV, tài khoản khóa, chưa xác minh, SĐT định dạng lạ"
    )


async def test_backfill_upgrades_the_temp_row_in_place_and_bumps_version(legacy_db):
    before = await rows("SELECT id, public_id, version FROM customer WHERE phone='0911000002'")
    await alembic(command.upgrade, TARGET)
    after = await rows("SELECT id, public_id, version FROM customer WHERE phone='0911000002'")
    assert after[0][0] == before[0][0] and after[0][1] == before[0][1], "cùng bản ghi"
    assert after[0][2] == before[0][2] + 1
    unchanged = await rows("SELECT version FROM customer WHERE phone='0911000005'")
    assert unchanged[0][0] == 1, "hội viên quầy không đổi version"


async def test_backfill_writes_system_audit_rows_without_full_phone(legacy_db):
    await alembic(command.upgrade, TARGET)
    got = await rows(
        "SELECT actor_type, action, entity_code, detail::text FROM audit_log WHERE detail::text LIKE '%backfill%' ORDER BY id"
    )
    assert len(got) == 3, got
    assert {r[0] for r in got} == {"system"}
    assert {r[2] for r in got} == {"HV0008", "HV0009", "HV0010"}
    assert not any(p in r[3] for r in got for p in ("0911000001", "0911000002", "0911000003")), (
        "SĐT che"
    )
    assert (
        sum("auto_upgrade" in r[1] for r in got) == 1
        and sum("self_register" in r[1] for r in got) == 2
    )


async def test_disabled_account_without_any_login_method_is_allowed_after_upgrade(legacy_db):
    await alembic(command.upgrade, TARGET)
    await run("UPDATE users SET phone=NULL, is_active=false WHERE phone='0911000004'")
    assert await rows(
        "SELECT count(*) FROM users WHERE phone IS NULL AND username IS NULL AND google_sub IS NULL AND NOT is_active"
    ) == [(1,)]
    with pytest.raises(Exception, match="login_id|check"):
        await run(
            "UPDATE users SET phone=NULL WHERE phone='0911000003'"
        )  # đang hoạt động mà không còn cách đăng nhập


async def test_schema_matches_models_downgrade_keeps_members_and_reupgrade_does_not_backfill_twice(
    legacy_db,
):
    await alembic(command.upgrade, TARGET)
    await alembic(lambda cfg, _rev: command.check(cfg), TARGET)
    first = await rows("SELECT phone, member_code FROM customer ORDER BY phone")
    await alembic(command.downgrade, BEFORE)
    assert await rows("SELECT phone, member_code FROM customer ORDER BY phone") == first, (
        "đảo ngược giữ nguyên hội viên đã tạo"
    )
    await alembic(command.upgrade, TARGET)
    assert await rows("SELECT phone, member_code FROM customer ORDER BY phone") == first, (
        "nâng lại không tạo thêm / đổi mã"
    )
    assert (await rows("SELECT count(*) FROM audit_log WHERE detail::text LIKE '%backfill%'"))[0][
        0
    ] == 3, "không ghi nhật ký backfill lần hai"

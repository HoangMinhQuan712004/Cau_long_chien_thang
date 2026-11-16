# ruff: noqa: E501
"""QA T-013 AC32–AC34: migration ``3c30569e12af`` trên bản sao dữ liệu cũ (Admin chỉ có email, ...).

Mỗi test dựng một DB riêng ``<db>_mig`` ở revision trước T-013 (``cc9af0a8c694``), nạp dữ liệu cũ,
rồi chạy migration thật. Không đụng DB test chính.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from tests.conftest import BACKEND_DIR

BEFORE = "cc9af0a8c694"
TARGET = "3c30569e12af"
HASH_ADMIN = "$2b$12$adminhashadminhashadminhashadminhashadminhashadminhash"
HASH_COUNTER = "$2b$12$counterhashcounterhashcounterhashcounterhashcounterha"
HASH_CUSTOMER = "$2b$12$customerhashcustomerhashcustomerhashcustomerhashcustom"
REAL_URL = settings.DATABASE_URL
MIG_DB = f"{make_url(REAL_URL).database.removesuffix('_test')}_mig"


def alembic_cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


async def run_alembic(fn, *args) -> None:
    """env.py của alembic tự chạy ``asyncio.run`` -> chạy ở thread riêng, trỏ vào DB riêng."""
    old = settings.DATABASE_URL
    settings.DATABASE_URL = make_url(REAL_URL).set(database=MIG_DB).render_as_string(False)
    try:
        await asyncio.to_thread(fn, alembic_cfg(), *args)
    finally:
        settings.DATABASE_URL = old


@asynccontextmanager
async def legacy_db(seed_sql: str) -> AsyncIterator[AsyncEngine]:
    admin = create_async_engine(
        make_url(REAL_URL).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as c:
        await c.execute(text(f"DROP DATABASE IF EXISTS {MIG_DB} WITH (FORCE)"))
        await c.execute(text(f"CREATE DATABASE {MIG_DB}"))
    await admin.dispose()
    await run_alembic(command.upgrade, BEFORE)
    eng = create_async_engine(make_url(REAL_URL).set(database=MIG_DB))
    try:
        async with eng.begin() as conn:
            for stmt in [s for s in seed_sql.split(";\n") if s.strip()]:
                await conn.execute(text(stmt))
        yield eng
    finally:
        await eng.dispose()


async def rows(eng: AsyncEngine, sql: str):
    async with eng.connect() as conn:
        return (await conn.execute(text(sql))).mappings().all()


def user(rs, email):
    return next(r for r in rs if r["email"] == email)


LEGACY = f"""
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (1, 'admin@gmail.com', NULL, 'Admin', '{HASH_ADMIN}', 'admin', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (2, 'counter@sancaulong.vn', NULL, 'Tài khoản tại máy', '{HASH_COUNTER}', 'staff', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (3, 'second.admin@x.vn', NULL, 'Admin Hai', '{HASH_ADMIN}', 'admin', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (4, 'c1@x.vn', '0987 654 321', 'Khách Một', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (5, 'c2@x.vn', '+84 987 654 321', 'Khách Trùng Số', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (6, 'c3@x.vn', 'abc-không-phải-số', 'Khách Số Hỏng', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (7, 'Khach.Hang@Mail.com', NULL, 'Khách Không SĐT', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (8, 'c5@x.vn', '0911.222.333', 'Khách Chấm', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (9, 'c6@x.vn', '12345', 'Khách Quá Ngắn', '{HASH_CUSTOMER}', 'customer', true);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (10, 'c7@x.vn', '0933-444-555', 'Khách Gạch', '{HASH_CUSTOMER}', 'customer', false);
INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
 (11, 'counter2@sancaulong.vn', NULL, 'Quầy Hai', '{HASH_COUNTER}', 'staff', true)
"""


async def test_ac32_full_data_set_migrates_in_the_documented_order(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    async with legacy_db(LEGACY) as eng:
        await run_alembic(command.upgrade, TARGET)
        rs = await rows(eng, "SELECT * FROM users ORDER BY id")
        assert len(rs) == 11

        # AC32.2 + AC33: Admin id nhỏ nhất nhận SĐT; mật khẩu giữ nguyên; coi như đã xác minh
        a = user(rs, "admin@gmail.com")
        assert a["phone"] == "0912345678" and a["hashed_password"] == HASH_ADMIN
        assert a["phone_verified_at"] is not None and a["role"] == "admin"
        # Admin thứ hai chỉ có email -> không SĐT, có username từ email + id
        a2 = user(rs, "second.admin@x.vn")
        assert a2["phone"] is None and a2["username"] == "second.admin_3"
        assert a2["hashed_password"] == HASH_ADMIN

        # AC32.4: "Tài khoản tại máy" -> NV001 / nv001, mật khẩu giữ nguyên
        s1, s2 = user(rs, "counter@sancaulong.vn"), user(rs, "counter2@sancaulong.vn")
        assert (s1["staff_code"], s1["username"]) == ("NV001", "nv001")
        assert (s2["staff_code"], s2["username"]) == ("NV002", "nv002")
        assert s1["hashed_password"] == HASH_COUNTER and s1["full_name"] == "Tài khoản tại máy"
        assert s1["phone"] is None and s1["phone_verified_at"] is None

        # AC32.1: chuẩn hóa SĐT; trùng giữ id nhỏ nhất; không hợp lệ -> NULL
        assert user(rs, "c1@x.vn")["phone"] == "0987654321"
        assert user(rs, "c2@x.vn")["phone"] is None, "duplicate keeps the smallest id"
        assert user(rs, "c3@x.vn")["phone"] is None and user(rs, "c6@x.vn")["phone"] is None
        assert user(rs, "c5@x.vn")["phone"] == "0911222333"
        assert user(rs, "c7@x.vn")["phone"] == "0933444555"

        # AC32.3: khách không SĐT -> username = left(lower(local-part), 49 - len(id)) || '_' || id
        assert user(rs, "Khach.Hang@Mail.com")["username"] == "khach.hang_7"
        assert user(rs, "c2@x.vn")["username"] == "c2_5"
        assert user(rs, "c1@x.vn")["username"] is None, "phone owners get no generated username"

        # AC32.6: khách có SĐT cũ chưa xác minh; hồ sơ khác giữ nguyên
        for email in ("c1@x.vn", "c5@x.vn", "c7@x.vn"):
            assert user(rs, email)["phone_verified_at"] is None, email
        assert not user(rs, "c7@x.vn")["is_active"], "is_active preserved"
        assert all(r["hashed_password"] for r in rs)

        # AC32.5: email nullable nhưng dữ liệu còn nguyên
        assert all(r["email"] for r in rs)
        nullable = await rows(
            eng,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name='users' AND column_name IN ('email','hashed_password')",
        )
        assert all(r["is_nullable"] == "YES" for r in nullable)

        # ràng buộc: SĐT unique, CHECK có ít nhất một định danh, sequence nối tiếp NV003
        assert not await rows(
            eng, "SELECT phone FROM users WHERE phone IS NOT NULL GROUP BY phone HAVING count(*)>1"
        )
        with pytest.raises(Exception, match="ck_users_login_id|uq_users_phone|violates"):
            async with eng.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO users (email, full_name, role, is_active) "
                        "VALUES ('x@x.vn','X','customer',true)"
                    )
                )
        nxt = await rows(eng, "SELECT nextval('staff_code_seq') AS n")
        assert nxt[0]["n"] == 3, "staff_code_seq continues after NV002"

        # bảng mới
        tables = {
            r["table_name"]
            for r in await rows(
                eng, "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert {"admin_sessions", "otp_codes"} <= tables
        head = await rows(eng, "SELECT version_num FROM alembic_version")
        assert head[0]["version_num"] == TARGET


async def test_ac32_alembic_check_is_clean_after_upgrade(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    async with legacy_db(LEGACY):
        await run_alembic(command.upgrade, "head")
        await run_alembic(command.check)  # ném CommandError nếu model lệch migration


ONE_ADMIN = LEGACY.replace(
    f"'Admin Hai', '{HASH_ADMIN}', 'admin'",
    f"'Admin Hai', '{HASH_ADMIN}', 'customer'",
)


async def test_ac32_downgrade_then_upgrade_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    async with legacy_db(ONE_ADMIN) as eng:
        await run_alembic(command.upgrade, TARGET)
        async with eng.begin() as conn:
            # Google-only (không mật khẩu) và tài khoản mới không email
            await conn.execute(
                text(
                    "INSERT INTO users (id, phone, username, full_name, hashed_password, role, is_active, google_sub, google_email) "
                    "VALUES (100, NULL, NULL, 'Chỉ Google', NULL, 'customer', true, 'g-sub-1', 'g@gmail.com')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO users (id, phone, full_name, hashed_password, role, is_active) "
                    f"VALUES (101, '0966777888', 'Không Email', '{HASH_CUSTOMER}', 'customer', true)"
                )
            )
        await run_alembic(command.downgrade, BEFORE)
        rs = await rows(eng, "SELECT id, email, phone, hashed_password FROM users ORDER BY id")
        ids = [r["id"] for r in rs]
        assert 100 not in ids, "Google-only account removed on downgrade"
        assert 101 in ids
        assert next(r for r in rs if r["id"] == 101)["email"] == "user101@khong-co-email.invalid"
        assert all(r["email"] and r["hashed_password"] for r in rs), "NOT NULL restored"
        cols = {
            r["column_name"]
            for r in await rows(
                eng, "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
            )
        }
        assert not cols & {"username", "staff_code", "google_sub", "token_version", "locked_until"}
        seq = await rows(eng, "SELECT 1 FROM pg_class WHERE relname='staff_code_seq'")
        assert not seq
        types = await rows(
            eng, "SELECT 1 FROM pg_type WHERE typname IN ('otp_purpose','session_end_reason')"
        )
        assert not types
        # lên lại sạch
        await run_alembic(command.upgrade, "head")
        again = await rows(
            eng,
            "SELECT phone, staff_code FROM users WHERE email='admin@gmail.com' OR role='staff' ORDER BY id",
        )
        assert again[0]["phone"] == "0912345678" and again[1]["staff_code"] == "NV001"


@pytest.mark.parametrize("bad", ["", "   ", "abc", "12345", "0123"])
async def test_ac32_missing_or_invalid_first_admin_phone_stops_the_migration(monkeypatch, bad):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", bad)
    async with legacy_db(LEGACY) as eng:
        with pytest.raises(Exception) as exc:
            await run_alembic(command.upgrade, TARGET)
        msg = str(exc.value)
        assert "FIRST_ADMIN_PHONE" in msg, msg
        if bad.strip():
            assert bad not in msg.replace("FIRST_ADMIN_PHONE", ""), "the value is never printed"
        # không đổi gì: vẫn ở revision cũ, cột mới chưa có, dữ liệu nguyên vẹn
        head = await rows(eng, "SELECT version_num FROM alembic_version")
        assert head[0]["version_num"] == BEFORE
        cols = {
            r["column_name"]
            for r in await rows(
                eng, "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
            )
        }
        assert "username" not in cols and "token_version" not in cols
        rs = await rows(eng, "SELECT email, phone FROM users ORDER BY id")
        assert user(rs, "c1@x.vn")["phone"] == "0987 654 321", "phones untouched after the abort"
        assert not await rows(eng, "SELECT 1 FROM pg_class WHERE relname='staff_code_seq'")


async def test_ac32_first_admin_phone_owned_by_someone_else_stops_the_migration(monkeypatch):
    # 0987654321 là SĐT (đã chuẩn hóa) của khách id 4
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0987 654 321")
    async with legacy_db(LEGACY) as eng:
        with pytest.raises(Exception) as exc:
            await run_alembic(command.upgrade, TARGET)
        assert "FIRST_ADMIN_PHONE" in str(exc.value)
        assert "0987654321" not in str(exc.value)
        head = await rows(eng, "SELECT version_num FROM alembic_version")
        assert head[0]["version_num"] == BEFORE


async def test_ac33_admin_that_already_has_a_phone_is_never_overwritten(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    seed = f"""
    INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
     (1, 'owner@x.vn', '+84 90 111 2233', 'Chủ Sân', '{HASH_ADMIN}', 'admin', true)
    """
    async with legacy_db(seed) as eng:
        await run_alembic(command.upgrade, TARGET)
        r = (
            await rows(eng, "SELECT phone, hashed_password, username, phone_verified_at FROM users")
        )[0]
        assert r["phone"] == "0901112233" and r["hashed_password"] == HASH_ADMIN
        assert r["username"] is None and r["phone_verified_at"] is not None


async def test_ac33_admin_with_unusable_phone_receives_the_configured_one(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    seed = f"""
    INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
     (1, 'owner@x.vn', 'khong-ro', 'Chủ Sân', '{HASH_ADMIN}', 'admin', true)
    """
    async with legacy_db(seed) as eng:
        await run_alembic(command.upgrade, TARGET)
        r = (await rows(eng, "SELECT phone, hashed_password FROM users"))[0]
        assert r["phone"] == "0912345678" and r["hashed_password"] == HASH_ADMIN


async def test_ac32_database_without_admin_needs_no_first_admin_phone(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "")
    seed = f"""
    INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
     (1, 'c@x.vn', '0987654321', 'Chỉ Khách', '{HASH_CUSTOMER}', 'customer', true)
    """
    async with legacy_db(seed) as eng:
        await run_alembic(command.upgrade, TARGET)
        assert (await rows(eng, "SELECT phone FROM users"))[0]["phone"] == "0987654321"


async def test_ac34_migrated_accounts_keep_their_old_passwords_for_sign_in(monkeypatch):
    """Dùng bcrypt/argon thật: Admin cũ vào bằng SĐT mới + mật khẩu cũ, NV cũ vào bằng ``nv001``."""
    from app.core.security import hash_password

    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    seed = f"""
    INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
     (1, 'admin@gmail.com', NULL, 'Admin', '{hash_password("OldAdmin#1")}', 'admin', true);
    INSERT INTO users (id, email, phone, full_name, hashed_password, role, is_active) VALUES
     (2, 'counter@x.vn', NULL, 'Tài khoản tại máy', '{hash_password("oldcounter")}', 'staff', true)
    """
    async with legacy_db(seed) as eng:
        await run_alembic(command.upgrade, TARGET)
        from app.core.security import verify_password

        rs = await rows(eng, "SELECT phone, username, hashed_password FROM users ORDER BY id")
        assert rs[0]["phone"] == "0912345678" and verify_password(
            "OldAdmin#1", rs[0]["hashed_password"]
        )
        assert rs[1]["username"] == "nv001" and verify_password(
            "oldcounter", rs[1]["hashed_password"]
        )
        # mật khẩu cũ yếu (không in hoa/chữ số) vẫn đăng nhập được = chỉ kiểm hash, không ép đổi
        assert verify_password("oldcounter", rs[1]["hashed_password"])


async def test_ac32_reupgrade_after_downgrade_with_two_email_only_admins(monkeypatch):
    monkeypatch.setattr(settings, "FIRST_ADMIN_PHONE", "0912345678")
    async with legacy_db(LEGACY) as eng:
        await run_alembic(command.upgrade, TARGET)
        await run_alembic(command.downgrade, BEFORE)
        await run_alembic(command.upgrade, TARGET)  # Admin thứ hai: phải đi theo bước 3, không dừng
        rs = await rows(
            eng, "SELECT email, phone, username FROM users WHERE role='admin' ORDER BY id"
        )
        assert rs[0]["phone"] == "0912345678" and rs[1]["phone"] is None and rs[1]["username"]

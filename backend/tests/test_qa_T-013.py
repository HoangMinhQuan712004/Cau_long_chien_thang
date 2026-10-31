"""QA T-013 mốc 1: đăng nhập, phiên Admin/NV, quản lý nhân viên (AC1–AC13, AC18–AC19, AC33, SEC).

Viết theo spec ``board/tasks/T-013-dang-nhap-nhan-vien.md`` và ADR-008, không theo code BE.
Đặt tên test theo số tiêu chí; phần mốc 2 (OTP, Google, phone_token) nằm ở file riêng.
"""

import asyncio
import hashlib
import re
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from app.scripts import seed
from tests.conftest import (
    API,
    CUSTOMER_PASSWORD,
    _client,
    age_otp_codes,
    new_registered,
    register,
    sign_in,
    unique_phone,
)
from tests.qa_accounts import db_account

EVIL = "https://evil.example"
ADMIN_LOGIN = settings.FIRST_ADMIN_PHONE
ADMIN_PW = settings.FIRST_ADMIN_PASSWORD


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def err(r) -> dict:
    return r.json()["detail"]


async def new_staff(admin: AsyncClient, name: str = "Trần Thị Bích", password: str = "Password123"):
    r = await admin.post(f"{API}/admin/staff", json={"full_name": name, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


async def staff_client(username: str, password: str = "Password123") -> AsyncClient:
    c = _client()
    r = await sign_in(c, username, password)
    assert r.status_code == 200, r.text
    return c


def cookie_lines(r) -> list[str]:
    return r.headers.get_list("set-cookie")


# ---------------------------------------- AC1 đăng nhập một ô


@pytest.mark.parametrize("style", ["plain", "plus84", "plus84_spaces", "dots", "dashes", "padded"])
async def test_ac1_phone_formats_find_the_same_admin(anon, style):
    p = ADMIN_LOGIN  # 0912345678
    login = {
        "plain": p,
        "plus84": "+84" + p[1:],
        "plus84_spaces": f"+84 {p[1:4]} {p[4:7]} {p[7:]}",
        "dots": f"{p[:4]}.{p[4:7]}.{p[7:]}",
        "dashes": f"{p[:4]}-{p[4:7]}-{p[7:]}",
        "padded": f"  {p}  ",
    }[style]
    r = await sign_in(anon, login, ADMIN_PW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "admin"
    assert body["account"] == {
        "kind": "admin",
        "display_name": "Admin",
        "role_label": "Chủ sân",
        "staff_code": None,
    }


async def test_ac1_username_is_case_insensitive_and_returns_staff_card(admin, anon):
    s = await new_staff(admin, "Nguyễn Văn An")
    for login in (s["username"], s["username"].upper(), f" {s['username'].title()} "):
        async with _client() as c:
            r = await sign_in(c, login, "Password123")
            assert r.status_code == 200, (login, r.text)
            body = r.json()
            assert body["kind"] == "admin" and body["account"]["kind"] == "staff"
            assert body["account"]["staff_code"] == s["staff_code"]
            assert body["account"]["display_name"] == "Nguyễn Văn An"


async def test_ac1_customer_gets_customer_kind_with_own_full_phone(anon):
    phone = unique_phone()
    await db_account(None, phone, "Khách Đăng Nhập")  # T-021: /auth/register đóng, tạo qua DB
    async with _client() as c:
        r = await sign_in(c, phone, CUSTOMER_PASSWORD)
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "member" and body["account"]["phone"] == phone
        assert body["account"]["role"] == "member" and "email" not in body["account"]
        assert (await c.get(f"{API}/auth/me")).status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {"login": "", "password": "x"},
        {"login": "x", "password": ""},
        {"login": "x" * 51, "password": "x"},
        {"login": "x", "password": "p" * 129},
        {"login": "x", "password": "y", "email": "a@b.c"},
        {"login": "x"},
        {},
    ],
)
async def test_ac1_bad_shape_is_422(anon, body):
    r = await anon.post(f"{API}/auth/sign-in", json=body)
    assert r.status_code == 422


async def test_ac1_old_endpoints_are_gone(admin, anon):
    r = await anon.post(f"{API}/auth/login", json={"email": "a@b.vn", "password": "x"})
    assert r.status_code in (404, 405)
    assert (await admin.get(f"{API}/admin/users")).status_code in (404, 405)


# ---------------------------------------- AC2 sai thông tin, khóa tài khoản


async def test_ac2_unknown_and_wrong_password_look_identical(anon, customer):
    me = (await customer.get(f"{API}/auth/me")).json()
    wrong = await sign_in(anon, me["phone"], "Wrong-Pass1")
    unknown = await sign_in(anon, unique_phone(), "Wrong-Pass1")
    unknown_user = await sign_in(anon, "khong.co.nv999", "Wrong-Pass1")
    for r in (wrong, unknown, unknown_user):
        assert r.status_code == 401 and err(r)["code"] == "E-AUTH-10"
    assert err(wrong) == err(unknown) == err(unknown_user)
    assert err(wrong)["message"] == "Số điện thoại, tên đăng nhập hoặc mật khẩu không đúng."


async def test_ac2_unknown_account_never_locks_or_counts(anon):
    ghost = unique_phone()
    codes = [(await sign_in(anon, ghost, "Wrong-Pass1")).status_code for _ in range(8)]
    assert codes == [401] * 8, "a non-existing account must not turn into 423"


async def test_ac2_five_wrong_locks_for_15_minutes(anon, admin):
    s = await new_staff(admin)
    codes = []
    for _ in range(5):
        codes.append(await sign_in(anon, s["username"], "Wrong-Pass1"))
    assert [c.status_code for c in codes] == [401, 401, 401, 401, 423]
    locked = codes[-1]
    d = err(locked)
    assert d["code"] == "E-AUTH-11" and d["retry_after"] > 0
    assert 800 <= d["retry_after"] <= 900
    assert "5 lần" in d["message"] and "15 phút" in d["message"]
    assert locked.headers.get("retry-after") == str(d["retry_after"])
    # Đúng mật khẩu trong lúc khóa vẫn bị từ chối
    again = await sign_in(anon, s["username"], "Password123")
    assert again.status_code == 423 and err(again)["code"] == "E-AUTH-11"
    rows = await q(
        "SELECT 1 FROM audit_log WHERE action='auth.login_locked' AND entity_code=:i",
        i=str(s["id"]),
    )
    assert len(rows) == 1, "one auth.login_locked audit row"


async def test_ac2_lock_expires_and_counter_restarts_from_zero(anon, admin):
    s = await new_staff(admin)
    for _ in range(5):
        await sign_in(anon, s["username"], "Wrong-Pass1")
    await x("UPDATE users SET locked_until = now() - interval '1 minute' WHERE id=:i", i=s["id"])
    # sau khi hết khóa: 4 lần sai chưa khóa lại
    codes = [(await sign_in(anon, s["username"], "Wrong-Pass1")).status_code for _ in range(4)]
    assert codes == [401] * 4
    ok = await sign_in(anon, s["username"], "Password123")
    assert ok.status_code == 200


async def test_ac2_success_resets_the_counter(anon, admin):
    s = await new_staff(admin)
    for _ in range(4):
        assert (await sign_in(anon, s["username"], "Wrong-Pass1")).status_code == 401
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 200
    for _ in range(4):
        assert (await sign_in(anon, s["username"], "Wrong-Pass1")).status_code == 401
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 200


async def test_ac2_concurrent_wrong_attempts_lock_exactly_at_five(anon, admin):
    s = await new_staff(admin)

    async def one():
        async with _client() as c:
            return (await sign_in(c, s["username"], "Wrong-Pass1")).status_code

    codes = await asyncio.gather(*[one() for _ in range(12)])
    assert codes.count(401) == 4, codes
    assert codes.count(423) == 8, codes
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 423


async def test_ac2_disabled_account_cannot_sign_in(anon, admin):
    s = await new_staff(admin)
    r = await admin.patch(f"{API}/admin/staff/{s['id']}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = await sign_in(anon, s["username"], "Password123")
    assert r.status_code == 401 and err(r)["code"] == "E-AUTH-10"


# ---------------------------------------- AC3 giới hạn theo IP


async def test_ac3_twenty_failures_from_one_ip_block_even_valid_logins(anon):
    for i in range(20):
        r = await sign_in(anon, unique_phone(), "Wrong-Pass1")
        assert r.status_code == 401, (i, r.text)
    r = await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)
    assert r.status_code == 429, r.text
    d = err(r)
    assert d["code"] == "E-AUTH-12" and d["retry_after"] > 0
    assert "15 phút" in d["message"] and r.headers.get("retry-after")


async def test_ac3_nineteen_failures_still_allow_a_valid_login(anon):
    for _ in range(19):
        await sign_in(anon, unique_phone(), "Wrong-Pass1")
    assert (await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)).status_code == 200


@pytest.mark.parametrize("trusted", [0, 1])
async def test_sec4_spoofed_x_forwarded_for_does_not_escape_the_ip_limit(
    anon, monkeypatch, trusted
):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", trusted)
    for i in range(20):
        # trusted=0: header bị bỏ qua; trusted=1: chỉ phần tử cuối (do proxy ghi) được tin
        xff = f"1.1.1.{i}" if trusted == 0 else f"1.1.1.{i}, 10.9.9.9"
        r = await anon.post(
            f"{API}/auth/sign-in",
            json={"login": unique_phone(), "password": "Wrong-Pass1"},
            headers={"X-Forwarded-For": xff},
        )
        assert r.status_code == 401
    xff = "2.2.2.2" if trusted == 0 else "2.2.2.2, 10.9.9.9"
    r = await anon.post(
        f"{API}/auth/sign-in",
        json={"login": ADMIN_LOGIN, "password": ADMIN_PW},
        headers={"X-Forwarded-For": xff},
    )
    assert r.status_code == 429 and err(r)["code"] == "E-AUTH-12"


# ---------------------------------------- AC4 phiên Admin/NV


async def test_ac4_admin_cookie_attributes_and_hashed_token(anon):
    r = await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)
    assert r.status_code == 200
    line = next(c for c in cookie_lines(r) if c.startswith("admin_session="))
    low = line.lower()
    assert "httponly" in low and "samesite=lax" in low and "path=/" in low
    assert f"max-age={settings.ADMIN_SESSION_HOURS * 3600}" in low
    assert settings.ADMIN_SESSION_HOURS == 12
    token = line.split(";")[0].split("=", 1)[1]
    assert len(token) >= 43
    digest = hashlib.sha256(token.encode()).hexdigest()
    rows = await q(
        "SELECT token_hash, expires_at, created_at FROM admin_sessions WHERE token_hash=:h",
        h=digest,
    )
    assert len(rows) == 1, "DB stores SHA-256 of the cookie token"
    hours = (rows[0]["expires_at"] - rows[0]["created_at"]).total_seconds() / 3600
    assert 11.9 < hours < 12.1, hours
    assert not await q("SELECT 1 FROM admin_sessions WHERE token_hash=:t", t=token), "no raw token"
    leaked = await q("SELECT 1 FROM audit_log WHERE detail::text LIKE :p", p=f"%{token}%")
    assert not leaked, "token must never appear in audit"
    me = await anon.get(f"{API}/admin/auth/me")
    assert me.status_code == 200 and me.json()["account"]["kind"] == "admin"


async def test_ac4_hard_expiry_is_not_extended_by_use(anon):
    await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)
    first = (await anon.get(f"{API}/admin/auth/me")).json()["expires_at"]
    for _ in range(3):
        await anon.get(f"{API}/admin/auth/me")
    assert (await anon.get(f"{API}/admin/auth/me")).json()["expires_at"] == first


async def test_ac4_login_audits_success_and_each_session_is_separate(admin):
    rows = await q("SELECT actor_label FROM audit_log WHERE action='auth.login_success'")
    assert rows and all(
        r["actor_label"] in ("Admin",) or r["actor_label"].startswith("NV") for r in rows
    )
    other = _client()
    await sign_in(other, ADMIN_LOGIN, ADMIN_PW)
    assert (await other.get(f"{API}/admin/auth/me")).status_code == 200
    assert (await admin.get(f"{API}/admin/auth/me")).status_code == 200


async def test_ac4_one_session_kind_per_browser(anon):
    phone = unique_phone()
    await db_account(anon, phone, "Khách Hai Vai")
    assert (await anon.get(f"{API}/auth/me")).status_code == 200
    r = await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)
    assert r.status_code == 200
    names = [c.split("=")[0] for c in cookie_lines(r)]
    assert "admin_session" in names and "access_token" in names, "JWT cookie is cleared"
    assert (await anon.get(f"{API}/auth/me")).status_code == 401, "admin browser is not a customer"
    assert (await anon.get(f"{API}/admin/auth/me")).status_code == 200
    r = await sign_in(anon, phone, CUSTOMER_PASSWORD)
    assert r.status_code == 200 and r.json()["kind"] == "member"
    assert (await anon.get(f"{API}/admin/auth/me")).status_code == 401
    assert (await anon.get(f"{API}/auth/me")).status_code == 200


# ---------------------------------------- AC5 phiên hết hạn / thu hồi


async def test_ac5_unauthenticated_reasons(anon):
    r = await anon.get(f"{API}/admin/auth/me")
    assert (
        r.status_code == 401
        and err(r)["code"] == "E-AUTH-1"
        and err(r)["reason"] == "unauthenticated"
    )
    anon.cookies.set("admin_session", "not-a-real-token")
    r = await anon.get(f"{API}/admin/auth/me")
    assert r.status_code == 401 and err(r)["reason"] == "unauthenticated"
    anon.cookies.set("admin_session", "x" * 500)
    assert (await anon.get(f"{API}/admin/staff")).status_code == 401


async def test_ac5_expired_session_reports_expired_on_every_admin_route(anon):
    await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)
    await x(
        "UPDATE admin_sessions SET expires_at = now() - interval '1 second' WHERE token_hash = :h",
        h=hashlib.sha256(anon.cookies["admin_session"].encode()).hexdigest(),
    )
    for path in ("/admin/auth/me", "/admin/staff", "/payments/settings"):
        r = await anon.get(f"{API}{path}")
        assert r.status_code == 401, path
        assert err(r)["code"] == "E-AUTH-1" and err(r)["reason"] == "expired", path


async def test_ac5_password_reset_revokes_with_password_changed(admin):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    assert (await c.get(f"{API}/admin/auth/me")).status_code == 200
    r = await admin.post(f"{API}/admin/staff/{s['id']}/password", json={"password": "NewPass456"})
    assert r.status_code == 204
    r = await c.get(f"{API}/admin/auth/me")  # SEC6: ngay request kế tiếp
    assert r.status_code == 401 and err(r)["reason"] == "password_changed"


async def test_ac5_disable_revokes_with_account_disabled(admin):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    r = await admin.patch(f"{API}/admin/staff/{s['id']}", json={"is_active": False})
    assert r.status_code == 200
    r = await c.get(f"{API}/admin/auth/me")
    assert r.status_code == 401 and err(r)["reason"] == "account_disabled"
    r = await c.get(f"{API}/booking/calendar?date=2026-11-01")
    assert r.status_code == 401 and err(r)["reason"] == "account_disabled"


async def test_ac5_deactivating_directly_in_db_also_kills_the_session(admin):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    await x("UPDATE users SET is_active = false WHERE id = :i", i=s["id"])
    r = await c.get(f"{API}/admin/auth/me")
    assert r.status_code == 401 and err(r)["reason"] == "account_disabled"


# ---------------------------------------- AC6 token_version của JWT khách


async def test_ac6_bumping_token_version_rejects_old_access_and_refresh_tokens(customer):
    me = await customer.get(f"{API}/auth/me")
    assert me.status_code == 200
    ref = await customer.post(f"{API}/auth/refresh")
    assert ref.status_code == 200
    await x("UPDATE users SET token_version = token_version + 1 WHERE id = :i", i=me.json()["id"])
    assert (await customer.get(f"{API}/auth/me")).status_code == 401
    r = await customer.post(f"{API}/auth/refresh")
    assert r.status_code == 401 and err(r)["code"] == "E-AUTH-1"


# ---------------------------------------- AC7 đăng xuất


async def test_ac7_admin_logout_revokes_this_session_only(admin):
    other = _client()
    await sign_in(other, ADMIN_LOGIN, ADMIN_PW)
    token = admin.cookies["admin_session"]
    r = await admin.post(f"{API}/admin/auth/logout")
    assert r.status_code == 204
    row = (
        await q(
            "SELECT revoked_reason, revoked_at FROM admin_sessions WHERE token_hash=:h",
            h=hashlib.sha256(token.encode()).hexdigest(),
        )
    )[0]
    assert row["revoked_reason"] == "logout" and row["revoked_at"] is not None
    stale = _client()
    stale.cookies.set("admin_session", token)
    assert (await stale.get(f"{API}/admin/auth/me")).status_code == 401, "revoked token is dead"
    assert (await other.get(f"{API}/admin/auth/me")).status_code == 200, "other machine unaffected"
    assert await q("SELECT 1 FROM audit_log WHERE action='auth.logout'")


async def test_ac7_logout_is_idempotent_and_customer_logout_works(anon, customer):
    assert (await anon.post(f"{API}/admin/auth/logout")).status_code == 204
    assert (await customer.post(f"{API}/auth/logout")).status_code == 204
    assert (await customer.get(f"{API}/auth/me")).status_code == 401


# ---------------------------------------- AC8 / SEC5 tách quyền


async def test_ac8_customer_jwt_cannot_use_admin_routes_and_admin_session_is_not_a_customer(
    customer, admin
):
    for path in ("/admin/staff", "/admin/auth/me", "/payments/settings", "/booking/transactions"):
        r = await customer.get(f"{API}{path}")
        assert r.status_code in (401, 403), (path, r.status_code)
    r = await customer.post(
        f"{API}/admin/staff", json={"full_name": "Hacker", "password": "Password123"}
    )
    assert r.status_code in (401, 403)
    assert (await admin.get(f"{API}/auth/me")).status_code == 401


async def test_ac8_bearer_jwt_of_a_customer_does_not_open_admin(anon, customer):
    token = customer.cookies["access_token"]
    r = await anon.get(f"{API}/admin/staff", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403)


async def test_ac8_staff_keeps_the_previous_permission_table(admin):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    today = datetime.now(settings.tz).date().isoformat()
    assert (await c.get(f"{API}/booking/calendar?date={today}")).status_code == 200
    for path in (
        "/payments/settings",
        "/payments/bank-transactions",
        "/booking/transactions",
        "/admin/staff",
    ):
        r = await c.get(f"{API}{path}")
        assert r.status_code == 403 and err(r)["code"] == "E-AUTH-2", path
    assert (await admin.get(f"{API}/payments/settings")).status_code == 200


# ---------------------------------------- AC9–AC10 danh sách + tạo nhân viên


async def test_ac10_create_staff_generates_code_and_username(admin):
    a = await new_staff(admin, "Nguyễn Văn An")
    b = await new_staff(admin, "  Đặng   Thị  Bé ")
    assert re.fullmatch(r"NV\d{3}", a["staff_code"]) and re.fullmatch(r"NV\d{3}", b["staff_code"])
    assert int(b["staff_code"][2:]) > int(a["staff_code"][2:]), "codes only go up"
    assert a["username"] == f"an.{a['staff_code'].lower()}"
    assert b["username"] == f"be.{b['staff_code'].lower()}"
    assert b["full_name"] == "Đặng Thị Bé", "whitespace normalised"
    assert a["is_active"] is True and a["active_sessions"] == 0 and a["last_login_at"] is None
    assert set(a) == {
        "id", "staff_code", "full_name", "username", "is_active",
        "created_at", "last_login_at", "active_sessions",
    }  # fmt: skip
    assert "password" not in str(a).lower() and "hash" not in str(a).lower()


async def test_ac10_codes_are_unique_under_concurrent_creation(admin):
    rs = await asyncio.gather(
        *[
            admin.post(
                f"{API}/admin/staff",
                json={"full_name": f"Song Song {i}", "password": "Password123"},
            )
            for i in range(6)
        ]
    )
    assert all(r.status_code == 201 for r in rs), [r.text for r in rs]
    codes = [r.json()["staff_code"] for r in rs]
    names = [r.json()["username"] for r in rs]
    assert len(set(codes)) == 6 and len(set(names)) == 6


async def test_ac10_username_is_at_most_30_chars(admin):
    s = await new_staff(admin, "Nguyễn " + "Rấtrấtrấtrấtrấtrấtrấtrấtrấtdài" * 3)
    assert len(s["username"]) <= 30 and re.fullmatch(r"[a-z0-9]+\.nv\d{3}", s["username"])


async def test_ac10_client_cannot_choose_username_or_code(admin):
    for extra in (
        {"username": "hacker"},
        {"staff_code": "NV999"},
        {"role": "admin"},
        {"phone": "0911111111"},
    ):
        r = await admin.post(
            f"{API}/admin/staff", json={"full_name": "Gian Lận", "password": "Password123", **extra}
        )
        assert r.status_code == 422, extra


@pytest.mark.parametrize(
    ("password", "needs"),
    [
        ("Short1", "ít nhất 8 ký tự"),
        ("password123", "1 chữ in hoa"),
        ("Passwordabc", "1 chữ số hoặc ký tự đặc biệt"),
        ("abc", "ít nhất 8 ký tự"),
        ("a" * 129, None),
    ],
)
async def test_ac18_weak_passwords_are_422_with_the_pr_wording(admin, password, needs):
    r = await admin.post(
        f"{API}/admin/staff", json={"full_name": "Mật Khẩu Yếu", "password": password}
    )
    assert r.status_code == 422
    if needs:
        msgs = [e["msg"] for e in r.json()["detail"]]
        assert any(m.startswith("Mật khẩu cần") and needs in m and m.endswith(".") for m in msgs), (
            msgs
        )


async def test_ac18_special_character_counts_instead_of_a_digit(admin):
    r = await admin.post(
        f"{API}/admin/staff", json={"full_name": "Ký Tự Đặc Biệt", "password": "Password!"}
    )
    assert r.status_code == 201


async def test_ac10_empty_or_blank_name_is_rejected(admin):
    for name in ("", "   "):
        r = await admin.post(
            f"{API}/admin/staff", json={"full_name": name, "password": "Password123"}
        )
        assert r.status_code == 422, repr(name)


async def test_ac9_list_shows_sessions_and_last_login(admin):
    s = await new_staff(admin)
    c1 = await staff_client(s["username"])
    c2 = await staff_client(s["username"])
    rows = (await admin.get(f"{API}/admin/staff")).json()
    me = next(r for r in rows if r["id"] == s["id"])
    assert me["active_sessions"] == 2 and me["last_login_at"] is not None
    await c1.post(f"{API}/admin/auth/logout")
    me = next(r for r in (await admin.get(f"{API}/admin/staff")).json() if r["id"] == s["id"])
    assert me["active_sessions"] == 1
    # Only the row this test created: other tests may leave staff with any code (or none).
    assert re.fullmatch(r"NV\d{3,}", me["staff_code"])
    assert all("hashed_password" not in r and "phone" not in r for r in rows)
    del c2


# ---------------------------------------- AC11 sửa, khóa, đặt lại mật khẩu


async def test_ac11_rename_staff_and_audit(admin):
    s = await new_staff(admin, "Tên Cũ")
    r = await admin.patch(f"{API}/admin/staff/{s['id']}", json={"full_name": "  Tên   Mới "})
    assert r.status_code == 200 and r.json()["full_name"] == "Tên Mới"
    assert r.json()["username"] == s["username"], "username does not change with the name"
    assert await q(
        "SELECT 1 FROM audit_log WHERE action='staff.update' AND entity_code=:c", c=s["staff_code"]
    )
    assert (
        await admin.patch(f"{API}/admin/staff/{s['id']}", json={"full_name": ""})
    ).status_code == 422
    assert (
        await admin.patch(f"{API}/admin/staff/{s['id']}", json={"role": "admin"})
    ).status_code == 422


async def test_ac11_disable_then_enable_round_trip(admin, anon):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    r = await admin.patch(f"{API}/admin/staff/{s['id']}", json={"is_active": False})
    assert r.json()["is_active"] is False and r.json()["active_sessions"] == 0
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 401
    r = await admin.patch(f"{API}/admin/staff/{s['id']}", json={"is_active": True})
    assert r.json()["is_active"] is True
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 200
    assert (await c.get(f"{API}/admin/auth/me")).status_code == 401, "old session stays dead"
    for action in ("staff.disable", "staff.enable"):
        assert await q(
            "SELECT 1 FROM audit_log WHERE action=:a AND entity_code=:c",
            a=action,
            c=s["staff_code"],
        )


async def test_ac11_reset_password_changes_credentials_and_clears_lock(admin, anon):
    s = await new_staff(admin)
    for _ in range(5):
        await sign_in(anon, s["username"], "Wrong-Pass1")
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 423
    r = await admin.post(f"{API}/admin/staff/{s['id']}/password", json={"password": "Brand-New9"})
    assert r.status_code == 204
    assert (await sign_in(anon, s["username"], "Password123")).status_code == 401
    assert (await sign_in(anon, s["username"], "Brand-New9")).status_code == 200
    assert await q(
        "SELECT 1 FROM audit_log WHERE action='staff.password_reset' AND entity_code=:c",
        c=s["staff_code"],
    )
    r = await admin.post(f"{API}/admin/staff/{s['id']}/password", json={"password": "weak"})
    assert r.status_code == 422


async def test_ac11_audit_never_stores_passwords(admin):
    s = await new_staff(admin, password="Zz-Secret-777")
    await admin.post(f"{API}/admin/staff/{s['id']}/password", json={"password": "Yy-Secret-888"})
    rows = await q(
        "SELECT detail::text AS d FROM audit_log WHERE entity_code=:c", c=s["staff_code"]
    )
    assert rows and not any("Secret" in r["d"] for r in rows)
    hashed = await q("SELECT hashed_password FROM users WHERE id=:i", i=s["id"])
    assert hashed[0]["hashed_password"] != "Yy-Secret-888" and hashed[0][
        "hashed_password"
    ].startswith("$")


# ---------------------------------------- AC12 phiên của nhân viên


async def test_ac12_list_and_remote_logout_a_session(admin):
    s = await new_staff(admin)
    c1 = await staff_client(s["username"])
    c2 = await staff_client(s["username"])
    r = await admin.get(f"{API}/admin/staff/{s['id']}/sessions")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    for row in rows:
        assert set(row) == {"id", "created_at", "expires_at", "user_agent", "ip_masked"}
        assert row["ip_masked"] is None or "xxx" in row["ip_masked"], row["ip_masked"]
    sid = rows[0]["id"]  # mới nhất = c2
    assert (await admin.delete(f"{API}/admin/staff/{s['id']}/sessions/{sid}")).status_code == 204
    assert (await c2.get(f"{API}/admin/auth/me")).status_code == 401
    assert (await c1.get(f"{API}/admin/auth/me")).status_code == 200
    assert len((await admin.get(f"{API}/admin/staff/{s['id']}/sessions")).json()) == 1
    reason = (await q("SELECT revoked_reason FROM admin_sessions WHERE id=:i", i=sid))[0][
        "revoked_reason"
    ]
    assert reason == "revoked_by_admin"
    assert await q("SELECT 1 FROM audit_log WHERE action='auth.session_revoked'")
    again = await admin.delete(f"{API}/admin/staff/{s['id']}/sessions/{sid}")
    assert again.status_code == 404 and err(again)["code"] == "E-STAFF-2"


# ---------------------------------------- AC13 chỉ Admin, mã lỗi


async def test_ac13_staff_cannot_touch_staff_api(admin):
    s = await new_staff(admin)
    c = await staff_client(s["username"])
    calls = [
        ("GET", "/admin/staff", None),
        ("POST", "/admin/staff", {"full_name": "X", "password": "Password123"}),
        ("PATCH", f"/admin/staff/{s['id']}", {"is_active": False}),
        ("POST", f"/admin/staff/{s['id']}/password", {"password": "Password123"}),
        ("GET", f"/admin/staff/{s['id']}/sessions", None),
        ("DELETE", f"/admin/staff/{s['id']}/sessions/1", None),
    ]
    for method, path, body in calls:
        r = await c.request(method, f"{API}{path}", json=body)
        assert r.status_code == 403 and err(r)["code"] == "E-AUTH-2", (method, path, r.text)
    assert (await c.get(f"{API}/admin/auth/me")).status_code == 200, "own session intact"


async def test_ac13_ids_that_are_not_staff_are_e_staff_1(admin, customer):
    admin_id = (await q("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"))[0]["id"]
    cust_id = (await customer.get(f"{API}/auth/me")).json()["id"]
    for sid in (admin_id, cust_id, 99999999):
        for method, path, body in (
            ("PATCH", f"/admin/staff/{sid}", {"is_active": False}),
            ("POST", f"/admin/staff/{sid}/password", {"password": "Password123"}),
            ("GET", f"/admin/staff/{sid}/sessions", None),
            ("DELETE", f"/admin/staff/{sid}/sessions/1", None),
        ):
            r = await admin.request(method, f"{API}{path}", json=body)
            assert r.status_code == 404 and err(r)["code"] == "E-STAFF-1", (sid, method, path)
    assert (await admin.get(f"{API}/admin/auth/me")).status_code == 200, (
        "admin must not lock itself"
    )


async def test_ac13_session_of_another_staff_is_e_staff_2(admin):
    a, b = await new_staff(admin), await new_staff(admin)
    await staff_client(a["username"])
    sid_a = (await admin.get(f"{API}/admin/staff/{a['id']}/sessions")).json()[0]["id"]
    r = await admin.delete(f"{API}/admin/staff/{b['id']}/sessions/{sid_a}")
    assert r.status_code == 404 and err(r)["code"] == "E-STAFF-2"


# ---------------------------------------- AC19 đăng ký khách (T-021: 2 bước OTP, thành hội viên)

REG = f"{API}/auth/register"


async def reg_request(client, phone, name="Khách Mới", password="Password123", **extra):
    return await client.post(
        f"{REG}/request", json={"full_name": name, "phone": phone, "password": password, **extra}
    )


async def test_ac19_old_register_endpoint_is_closed_410(anon):
    r = await anon.post(
        REG, json={"full_name": "Cũ", "phone": unique_phone(), "password": "Password123"}
    )
    assert r.status_code == 410 and err(r)["code"] == "E-AUTH-32"
    assert not any(c.startswith("access_token=") for c in cookie_lines(r))


async def test_ac19_register_by_otp_verifies_the_phone_and_makes_a_member(anon):
    phone = unique_phone()
    r = await register(anon, phone, "  Khách   Mới ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"HV\d{4,5}", body["member_code"]) and body["upgraded_from_temp"] is False
    acc = body["account"]
    assert acc["phone"] == phone and acc["phone_verified"] is True and acc["role"] == "member"
    assert (
        acc["full_name"] == "Khách Mới"
        and "email" not in acc
        and "hashed_password" not in str(body)
    )
    assert any(c.startswith("access_token=") for c in cookie_lines(r))
    row = (await q("SELECT phone_verified_at FROM users WHERE phone=:p", p=phone))[0]
    assert row["phone_verified_at"] is not None
    assert (await anon.get(f"{API}/auth/me")).json()["phone_verified"] is True


async def test_ac19_duplicate_phone_in_any_format_is_e_auth_22_only_after_otp(anon):
    async with new_registered() as owner:
        phone = (await owner.get(f"{API}/auth/me")).json()["phone"]
    for variant in (phone, "+84" + phone[1:], f"{phone[:4]} {phone[4:7]} {phone[7:]}"):
        async with _client() as c:
            r = await register(c, variant, "Trùng Số")
            assert r.status_code == 409 and err(r)["code"] == "E-AUTH-22", variant
    async with _client() as c:
        admin_dup = await register(c, ADMIN_LOGIN, "Trùng Admin")
        assert admin_dup.status_code == 409 and err(admin_dup)["code"] == "E-AUTH-22"


async def test_ac19_concurrent_verify_of_one_phone_creates_one_account_and_one_member(anon):
    phone = unique_phone()
    async with _client() as c0:
        await age_otp_codes(phone)
        r = await reg_request(c0, phone, "Song Song")
        assert r.status_code == 202, r.text
        otp = r.json()["test_otp"]

    async def one():
        async with _client() as c:
            return (await c.post(f"{REG}/verify", json={"phone": phone, "otp": otp})).status_code

    codes = sorted(await asyncio.gather(*[one() for _ in range(4)]))
    assert codes.count(201) == 1 and set(codes) <= {201, 400, 409}, codes
    assert len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1
    assert len(await q("SELECT 1 FROM customer WHERE phone=:p AND kind='member'", p=phone)) == 1


@pytest.mark.parametrize(
    "phone", ["", "123", "0123456789012", "abc", "09123456", "+1 202 555 0100"]
)
async def test_ac19_invalid_phone_is_422(anon, phone):
    r = await reg_request(anon, phone, "Số Sai")
    assert r.status_code == 422


async def test_ac19_register_request_is_limited_to_10_per_hour_per_ip(anon):
    for i in range(10):
        async with _client() as c:
            r = await reg_request(c, unique_phone(), f"Hàng Loạt {i}")
            assert r.status_code == 202, (i, r.text)
    async with _client() as c:
        r = await reg_request(c, unique_phone(), "Thứ Mười Một")
        assert r.status_code == 429 and err(r)["code"] == "E-SEC-5"


async def test_ac19_register_rejects_weak_password_extra_fields_and_email(anon):
    phone = unique_phone()
    assert (await reg_request(anon, phone, password="weakpass")).status_code == 422
    assert (await reg_request(anon, phone, email="a@b.vn")).status_code == 422
    assert (await reg_request(anon, phone, role="admin")).status_code == 422


# ---------------------------------------- AC33 seed không ghi đè Admin


async def test_ac33_reseeding_never_overwrites_the_admin(anon):
    before = await q("SELECT id, phone, hashed_password FROM users WHERE role='admin' ORDER BY id")
    uncoded_before = (
        await q("SELECT count(*) AS n FROM users WHERE role='staff' AND staff_code IS NULL")
    )[0]["n"]
    await seed.main()
    after = await q("SELECT id, phone, hashed_password FROM users WHERE role='admin' ORDER BY id")
    assert [dict(r) for r in before] == [dict(r) for r in after]
    assert (await sign_in(anon, ADMIN_LOGIN, ADMIN_PW)).status_code == 200
    assert (await q("SELECT count(*) AS n FROM users WHERE role='staff' AND staff_code IS NULL"))[
        0
    ]["n"] == uncoded_before, "seed adds no staff"


# ---------------------------------------- SEC9 Origin, SEC2 bí mật


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/auth/sign-in", {"login": ADMIN_LOGIN, "password": ADMIN_PW}),
        (
            "/auth/register/request",
            {"full_name": "Evil", "phone": "0911222333", "password": "Password123"},
        ),
        ("/auth/refresh", None),
        ("/auth/logout", None),
    ],
)
async def test_sec9_foreign_origin_is_rejected_even_without_a_cookie(path, body):
    async with _client() as c:
        r = await c.post(f"{API}{path}", json=body, headers={"Origin": EVIL})
        assert r.status_code == 403 and err(r)["code"] == "E-SEC-1", path
        r = await c.post(f"{API}{path}", json=body, headers={"Origin": ""})
        assert r.status_code == 403, "empty Origin is not an allowed Origin"


async def test_sec9_foreign_origin_cannot_use_admin_cookie_for_staff_writes(admin):
    s = await new_staff(admin)
    h = {"Origin": EVIL}
    for method, path, body in (
        ("POST", "/admin/staff", {"full_name": "Evil", "password": "Password123"}),
        ("PATCH", f"/admin/staff/{s['id']}", {"is_active": False}),
        ("POST", f"/admin/staff/{s['id']}/password", {"password": "Evil-Pass1"}),
        ("POST", "/admin/auth/logout", None),
    ):
        r = await admin.request(method, f"{API}{path}", json=body, headers=h)
        assert r.status_code == 403 and err(r)["code"] == "E-SEC-1", (method, path)
    me = await admin.get(f"{API}/admin/auth/me")
    assert me.status_code == 200, "forged logout must not have ended the session"


async def test_sec2_no_password_or_token_in_logs_audit_or_responses(anon, admin, caplog):
    caplog.set_level("DEBUG")
    pw = "Log-Check-Pw-9"
    s = await new_staff(admin, "Kiểm Log", pw)
    r = await sign_in(anon, s["username"], pw)
    token = anon.cookies["admin_session"]
    await sign_in(_client(), s["username"], "Wrong-Pass1")
    assert pw not in r.text and token not in r.text
    assert pw not in caplog.text and token not in caplog.text and "Wrong-Pass1" not in caplog.text
    assert not await q(
        "SELECT 1 FROM audit_log WHERE detail::text LIKE :p OR actor_label LIKE :p", p=f"%{pw}%"
    )


async def test_sec1_unknown_and_wrong_password_take_comparable_time(anon, customer):
    import time

    phone = (await customer.get(f"{API}/auth/me")).json()["phone"]

    async def timed(login):
        t = time.perf_counter()
        await sign_in(anon, login, "Wrong-Pass1")
        return time.perf_counter() - t

    known, unknown = [], []
    for _ in range(4):  # tối đa 4 + 4 < 20 lần sai/IP và < 5 lần sai/tài khoản
        known.append(await timed(phone))
        unknown.append(await timed(unique_phone()))
    # min (not median): a busy CI box inflates single samples, a hash-less path stays ~ms
    km, um = min(known), min(unknown)
    assert um > km * 0.4, (
        f"unknown account answers far faster ({um:.3f}s vs {km:.3f}s): hash-less path"
    )

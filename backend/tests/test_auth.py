"""T-013 mốc 1: đăng nhập, khóa, phiên quản trị, JWT khách, quản lý nhân viên (AC1–AC13)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import create_token
from app.modules.auth.models import AdminSession, User
from app.modules.auth.utils import normalize_phone, staff_username
from tests.conftest import API, _client, sign_in, unique_phone

STAFF = f"{API}/admin/staff"
PASSWORD = "Password123"


async def create_staff(admin, name: str = "Nguyễn Văn An") -> dict:
    r = await admin.post(STAFF, json={"full_name": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


async def audit_count(action: str, code: str | None = None) -> int:
    async with SessionLocal() as s:
        q = select(AuditLog).where(AuditLog.action == action)
        if code:
            q = q.where(AuditLog.entity_code == code)
        return len(list(await s.scalars(q)))


# ------------------------------------------------------------------ đăng nhập (AC1–AC4)


def test_normalize_and_username_helpers():
    assert normalize_phone("+84 912.345-678") == "0912345678"
    assert normalize_phone("84912345678") == "0912345678"
    assert normalize_phone("0912 345 67") is None and normalize_phone("an.nv001") is None
    assert staff_username("Nguyễn Văn Đạt", "NV007") == "dat.nv007"
    assert staff_username("  ", "NV008") == "nv008"


@pytest.mark.parametrize("login", ["0912345678", "+84 912 345 678", "0912.345.678"])
async def test_admin_signs_in_by_phone(login):
    async with _client() as c:
        r = await sign_in(c, login, settings.FIRST_ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "admin"
        assert body["account"] == {
            "kind": "admin",
            "display_name": "Admin",
            "role_label": "Chủ sân",
            "staff_code": None,
        }
        cookie = r.headers.get("set-cookie", "")
        assert "admin_session=" in cookie and "HttpOnly" in cookie
        assert "samesite=lax" in cookie.lower()
        me = await c.get(f"{API}/admin/auth/me")
        assert me.status_code == 200 and me.json()["account"]["kind"] == "admin"
        expires = datetime.fromisoformat(me.json()["expires_at"])
        assert timedelta(hours=11, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=12)


async def test_customer_register_sign_in_me_logout(anon):
    phone = unique_phone()
    r = await anon.post(
        f"{API}/auth/register",
        json={"full_name": " Lê  Thị Lan ", "phone": f"+84{phone[1:]}", "password": PASSWORD},
    )
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == phone and r.json()["phone_verified"] is False
    assert r.json()["full_name"] == "Lê Thị Lan" and "email" not in r.json()
    dup = await anon.post(
        f"{API}/auth/register", json={"full_name": "X", "phone": phone, "password": PASSWORD}
    )
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "E-AUTH-22"

    async with _client() as c:
        r = await sign_in(c, phone, PASSWORD)
        assert r.status_code == 200 and r.json()["kind"] == "customer"
        assert (await c.get(f"{API}/auth/me")).json()["phone"] == phone
        # Khách không vào khu quản trị
        assert (await c.get(f"{API}/admin/auth/me")).status_code == 401
        assert (
            await c.get(f"{API}/booking/calendar", params={"date": "2030-01-01"})
        ).status_code == 403
        await c.post(f"{API}/auth/logout")
        c.cookies.clear()
        assert (await c.get(f"{API}/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "A", "phone": "12345", "password": PASSWORD},
        {"full_name": "A", "phone": unique_phone(), "password": "password123"},  # thiếu in hoa
        {"full_name": "A", "phone": unique_phone(), "password": "Short1"},
        {"full_name": "A", "phone": unique_phone(), "password": PASSWORD, "email": "a@b.vn"},
    ],
)
async def test_register_validation(anon, body):
    r = await anon.post(f"{API}/auth/register", json=body)
    assert r.status_code == 422


async def test_register_rate_limited_per_ip(anon, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_IP_MAX_PER_HOUR", 2)
    for _ in range(2):
        r = await anon.post(
            f"{API}/auth/register",
            json={"full_name": "A", "phone": unique_phone(), "password": PASSWORD},
        )
        assert r.status_code == 201
    r = await anon.post(
        f"{API}/auth/register",
        json={"full_name": "A", "phone": unique_phone(), "password": PASSWORD},
    )
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"


async def test_old_endpoints_removed(anon, admin):
    r = await anon.post(f"{API}/auth/login", json={"email": "a@b.vn", "password": "x"})
    assert r.status_code in (404, 405)
    assert (await admin.get(f"{API}/admin/users")).status_code == 404


async def test_unknown_and_wrong_look_the_same(anon, admin):
    expected = {
        "code": "E-AUTH-10",
        "message": "Số điện thoại, tên đăng nhập hoặc mật khẩu không đúng.",
    }
    r1 = await sign_in(anon, "khong.ton.tai", "Whatever1")
    r2 = await sign_in(anon, settings.FIRST_ADMIN_PHONE, "Sai-mat-khau1")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"] == expected
    # Admin không bị đếm sai sang khóa vì 1 lần; tài khoản lạ không đếm
    async with SessionLocal() as s:
        admin_user = await s.scalar(select(User).where(User.phone == settings.FIRST_ADMIN_PHONE))
        assert admin_user.failed_login_count == 1
        await s.execute(update(User).where(User.id == admin_user.id).values(failed_login_count=0))
        await s.commit()


async def test_lock_after_five_wrong_then_unlock(admin):
    nv = await create_staff(admin, "Trần Khóa")
    async with _client() as c:
        for _ in range(4):
            r = await sign_in(c, nv["username"], "Wrong-pass1")
            assert r.status_code == 401
        r = await sign_in(c, nv["username"], "Wrong-pass1")
        assert r.status_code == 423
        detail = r.json()["detail"]
        assert detail["code"] == "E-AUTH-11" and 1 <= detail["retry_after"] <= 900
        assert detail["message"] == "Bạn đã nhập sai 5 lần. Vui lòng thử lại sau 15 phút."
        r = await sign_in(c, nv["username"], PASSWORD)  # đúng nhưng đang khóa
        assert r.status_code == 423
    assert await audit_count("auth.login_locked") >= 1
    # Hết khóa -> đếm lại từ 0, đăng nhập đúng được
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == nv["id"])
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    async with _client() as c:
        r = await sign_in(c, nv["username"].upper(), PASSWORD)  # tên không phân biệt hoa thường
        assert r.status_code == 200
        assert r.json()["account"]["kind"] == "staff"
        assert r.json()["account"]["staff_code"] == nv["staff_code"]


async def test_concurrent_wrong_passwords_still_lock(admin):
    nv = await create_staff(admin, "Song Song")
    async with _client() as c:
        results = await asyncio.gather(
            *(sign_in(c, nv["username"], "Wrong-pass1") for _ in range(8))
        )
    assert 423 in [r.status_code for r in results]
    async with SessionLocal() as s:
        row = await s.get(User, nv["id"])
        assert row.locked_until is not None


async def test_ip_limit(anon, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 3)
    for _ in range(3):
        assert (await sign_in(anon, "khong.co", "Whatever1")).status_code == 401
    r = await sign_in(anon, settings.FIRST_ADMIN_PHONE, settings.FIRST_ADMIN_PASSWORD)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-AUTH-12"
    assert r.json()["detail"]["retry_after"] >= 1 and r.headers["retry-after"]


async def test_old_weak_password_still_signs_in():
    phone = unique_phone()
    from app.core.security import hash_password

    async with SessionLocal() as s:
        s.add(
            User(phone=phone, full_name="Cũ", hashed_password=hash_password("yeu"), role="customer")
        )
        await s.commit()
    async with _client() as c:
        assert (await sign_in(c, phone, "yeu")).status_code == 200


async def test_one_session_kind_per_browser(customer):
    """Khách đăng nhập Admin trên cùng trình duyệt -> JWT bị xóa, chỉ còn phiên quản trị."""
    r = await sign_in(customer, settings.FIRST_ADMIN_PHONE, settings.FIRST_ADMIN_PASSWORD)
    assert r.status_code == 200
    set_cookie = r.headers.get_list("set-cookie")
    assert any(c.startswith("access_token=") and "Max-Age=0" in c for c in set_cookie)
    assert (await customer.get(f"{API}/auth/me")).status_code == 401  # phiên Admin không làm khách


# ------------------------------------------------------------------ phiên (AC5–AC8)


async def test_admin_session_reasons(admin):
    nv = await create_staff(admin, "Lý Do")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        assert (await c.get(f"{API}/admin/auth/me")).status_code == 200
        # hết hạn
        async with SessionLocal() as s:
            await s.execute(
                update(AdminSession)
                .where(AdminSession.user_id == nv["id"])
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await s.commit()
        r = await c.get(f"{API}/booking/calendar", params={"date": "2030-01-01"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "E-AUTH-1"
        assert r.json()["detail"]["reason"] == "expired"

    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        r = await admin.post(f"{STAFF}/{nv['id']}/password", json={"password": "NewPass123"})
        assert r.status_code == 204
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401 and r.json()["detail"]["reason"] == "password_changed"

    async with _client() as c:
        await sign_in(c, nv["username"], "NewPass123")
        r = await admin.patch(f"{STAFF}/{nv['id']}", json={"is_active": False})
        assert r.status_code == 200 and r.json()["active_sessions"] == 0
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401 and r.json()["detail"]["reason"] == "account_disabled"
        assert (await sign_in(c, nv["username"], "NewPass123")).status_code == 401

    async with _client() as c:
        r = await c.get(f"{API}/admin/auth/me")
        assert r.json()["detail"]["reason"] == "unauthenticated"


async def test_admin_logout_only_this_device(admin):
    nv = await create_staff(admin, "Hai Máy")
    async with _client() as a, _client() as b:
        await sign_in(a, nv["username"], PASSWORD)
        await sign_in(b, nv["username"], PASSWORD)
        r = await a.post(f"{API}/admin/auth/logout")
        assert r.status_code == 204 and "admin_session=" in r.headers.get("set-cookie", "")
        assert (await a.get(f"{API}/admin/auth/me")).status_code == 401
        assert (await b.get(f"{API}/admin/auth/me")).status_code == 200
    assert await audit_count("auth.logout") >= 1


async def test_customer_jwt_versioned_and_not_admin(customer):
    me = (await customer.get(f"{API}/auth/me")).json()
    stale = create_token(str(me["id"]), "access", version=5)  # token_version hiện tại = 0
    async with _client() as c:
        c.cookies.set("access_token", stale)
        assert (await c.get(f"{API}/auth/me")).status_code == 401
    # JWT của tài khoản Admin (luồng cũ) không còn hợp lệ
    async with SessionLocal() as s:
        admin_id = await s.scalar(select(User.id).where(User.phone == settings.FIRST_ADMIN_PHONE))
    async with _client() as c:
        c.cookies.set("access_token", create_token(str(admin_id), "access"))
        assert (await c.get(f"{API}/admin/staff")).status_code == 401


async def test_staff_permissions(staff):
    assert (await staff.get(STAFF)).status_code == 403
    r = await staff.get(f"{API}/booking/calendar", params={"date": "2030-01-01"})
    assert r.status_code == 200  # quyền NV giữ như "Tài khoản tại máy"
    assert (await staff.get(f"{API}/booking/transactions")).status_code == 403


async def test_staff_label_in_audit(admin):
    nv = await create_staff(admin, "Phạm Nhãn")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        async with SessionLocal() as s:
            row = await s.scalar(
                select(AuditLog).where(
                    AuditLog.action == "auth.login_success", AuditLog.actor_id == nv["id"]
                )
            )
    assert row.actor_label == f"{nv['staff_code']} · Phạm Nhãn"


# ------------------------------------------------------------------ nhân viên (AC9–AC13)


async def test_create_staff_and_list(admin):
    nv = await create_staff(admin, "Nguyễn Văn Đạt")
    assert nv["staff_code"].startswith("NV") and nv["username"] == f"dat.{nv['staff_code'].lower()}"
    assert nv["is_active"] is True and nv["active_sessions"] == 0 and nv["last_login_at"] is None
    rows = (await admin.get(STAFF)).json()
    assert nv["id"] in [x["id"] for x in rows]
    assert await audit_count("staff.create", nv["staff_code"]) == 1
    # Client không gửi được username / mã
    r = await admin.post(
        STAFF,
        json={"full_name": "X", "password": PASSWORD, "username": "hack", "staff_code": "NV1"},
    )
    assert r.status_code == 422
    for bad in ({"full_name": "", "password": PASSWORD}, {"full_name": "A", "password": "weak"}):
        assert (await admin.post(STAFF, json=bad)).status_code == 422


async def test_staff_codes_unique_and_never_reused(admin):
    results = await asyncio.gather(*(create_staff(admin, f"Song {i}") for i in range(5)))
    codes = [r["staff_code"] for r in results]
    assert len(set(codes)) == 5
    last = max(int(c[2:]) for c in codes)
    nxt = await create_staff(admin, "Tiếp Theo")
    assert int(nxt["staff_code"][2:]) > last


async def test_update_and_reset_password(admin):
    nv = await create_staff(admin, "Đổi Tên")
    r = await admin.patch(f"{STAFF}/{nv['id']}", json={"full_name": "  Tên   Mới "})
    assert r.status_code == 200 and r.json()["full_name"] == "Tên Mới"
    assert r.json()["username"] == nv["username"]  # tên đăng nhập không đổi
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == nv["id"])
            .values(locked_until=datetime.now(UTC) + timedelta(minutes=10), failed_login_count=3)
        )
        await s.commit()
    assert (
        await admin.post(f"{STAFF}/{nv['id']}/password", json={"password": "weak"})
    ).status_code == 422
    r = await admin.post(f"{STAFF}/{nv['id']}/password", json={"password": "Fresh-pass1"})
    assert r.status_code == 204
    async with _client() as c:
        assert (await sign_in(c, nv["username"], "Fresh-pass1")).status_code == 200  # gỡ khóa
    r = await admin.patch(f"{STAFF}/{nv['id']}", json={"is_active": False})
    r = await admin.patch(f"{STAFF}/{nv['id']}", json={"is_active": True})
    assert r.json()["is_active"] is True
    for action in ("staff.update", "staff.password_reset", "staff.disable", "staff.enable"):
        assert await audit_count(action, nv["staff_code"]) >= 1


async def test_list_and_revoke_sessions(admin):
    nv = await create_staff(admin, "Phiên Từ Xa")
    async with _client() as a, _client() as b:
        await a.post(
            f"{API}/auth/sign-in",
            json={"login": nv["username"], "password": PASSWORD},
            headers={"User-Agent": "MayA"},
        )
        await sign_in(b, nv["username"], PASSWORD)
        rows = (await admin.get(f"{STAFF}/{nv['id']}/sessions")).json()
        assert len(rows) == 2
        for row in rows:
            assert set(row) == {"id", "created_at", "expires_at", "user_agent", "ip_masked"}
        target = next(x for x in rows if x["user_agent"] == "MayA")
        r = await admin.delete(f"{STAFF}/{nv['id']}/sessions/{target['id']}")
        assert r.status_code == 204
        assert (await a.get(f"{API}/admin/auth/me")).status_code == 401
        assert (await b.get(f"{API}/admin/auth/me")).status_code == 200
        r = await admin.delete(f"{STAFF}/{nv['id']}/sessions/{target['id']}")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "E-STAFF-2"
    assert await audit_count("auth.session_revoked", nv["staff_code"]) == 1


async def test_staff_api_not_staff_id_404(admin, customer):
    me = (await customer.get(f"{API}/auth/me")).json()
    for method, path, body in (
        ("PATCH", f"{STAFF}/{me['id']}", {"full_name": "X"}),
        ("POST", f"{STAFF}/{me['id']}/password", {"password": PASSWORD}),
        ("GET", f"{STAFF}/{me['id']}/sessions", None),
        ("GET", f"{STAFF}/999999/sessions", None),
    ):
        r = await admin.request(method, path, json=body)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "E-STAFF-1", path


async def test_origin_required_for_auth_writes(admin):
    async with _client() as c:
        c.headers["Origin"] = "https://evil.example"
        c.cookies.update(admin.cookies)
        r = await c.post(STAFF, json={"full_name": "Evil", "password": PASSWORD})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"

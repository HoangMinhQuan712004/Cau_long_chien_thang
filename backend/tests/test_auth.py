"""T-013 mốc 1: đăng nhập, khóa, phiên quản trị, JWT khách, quản lý nhân viên (AC1–AC13)."""

import asyncio
import io
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import create_token
from app.core.settings_store import AppSetting, SiteLogo
from app.modules.auth import site_map
from app.modules.auth.models import AdminSession, RolePermission, User
from app.modules.auth.utils import normalize_phone, staff_username
from app.modules.members.models import Customer
from tests.conftest import API, _client, register, sign_in, unique_phone

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
    # Người dùng chốt 2026-11-05: cả họ tên liền không dấu + "." + 4 ký tự ngẫu nhiên
    assert re.fullmatch(r"nguyenvandat\.[a-z2-9]{4}", staff_username("Nguyễn Văn Đạt"))
    long_name = staff_username("Nguyễn " + "a" * 40)
    assert len(long_name) == 30 and long_name.startswith("nguyen" + "a" * 19 + ".")
    assert re.fullmatch(r"nv\.[a-z2-9]{4}", staff_username("  "))
    assert staff_username("Lê Văn Cường", "k7q2") == "levancuong.k7q2"
    tails = {staff_username("An").split(".")[1] for _ in range(200)}
    assert len(tails) > 150 and not set("".join(tails)) & set("0o1li")


@pytest.mark.parametrize("login", ["0912345678", "+84 912 345 678", "0912.345.678"])
async def test_admin_signs_in_by_phone(login):
    async with _client() as c:
        r = await sign_in(c, login, settings.FIRST_ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "admin"
        assert body["account"] == {
            "kind": "admin",
            "display_name": "Chủ sân",  # full_name của Admin trong seed
            "role_label": "Admin",
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
    # Đăng ký 2 bước bằng OTP (T-021): SĐT nhập dạng +84 được chuẩn hóa
    r = await register(anon, f"+84{phone[1:]}", " Lê  Thị Lan ", PASSWORD)
    assert r.status_code == 201, r.text
    account = r.json()["account"]
    assert account["phone"] == phone and account["phone_verified"] is True
    assert account["full_name"] == "Lê Thị Lan" and "email" not in account
    async with _client() as other:
        dup = await register(other, phone, "X", PASSWORD)
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "E-AUTH-22"
    anon.cookies.clear()

    async with _client() as c:
        r = await sign_in(c, phone, PASSWORD)
        assert r.status_code == 200 and r.json()["kind"] == "member"
        assert (await c.get(f"{API}/auth/me")).json()["phone"] == phone
        # Khách không vào khu quản trị
        assert (await c.get(f"{API}/admin/auth/me")).status_code == 401
        assert (
            await c.get(f"{API}/booking/calendar", params={"date": "2030-01-01"})
        ).status_code == 403
        await c.post(f"{API}/auth/logout")
        c.cookies.clear()
        assert (await c.get(f"{API}/auth/me")).status_code == 401
    # Đăng ký tạo cả hội viên (R1): dọn để test chạy sau không thấy "Lê Thị Lan"
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone == phone))
        await s.execute(delete(User).where(User.phone == phone))
        await s.commit()


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "A", "phone": "12345", "password": PASSWORD},
        {"full_name": "A", "phone": unique_phone(), "password": "password123"},  # thiếu in hoa
        {"full_name": "A", "phone": unique_phone(), "password": "Short1"},
        {"full_name": "A", "phone": unique_phone(), "password": PASSWORD, "email": "a@b.vn"},
        {"full_name": " 	 ", "phone": unique_phone(), "password": PASSWORD},  # T-21-2
    ],
)
async def test_register_validation(anon, body):
    r = await anon.post(f"{API}/auth/register/request", json=body)
    assert r.status_code == 422


async def test_register_rate_limited_per_ip(anon, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_IP_MAX_PER_HOUR", 2)
    for _ in range(2):
        r = await anon.post(
            f"{API}/auth/register/request",
            json={"full_name": "A", "phone": unique_phone(), "password": PASSWORD},
        )
        assert r.status_code == 202
    r = await anon.post(
        f"{API}/auth/register/request",
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
            User(phone=phone, full_name="Cũ", hashed_password=hash_password("yeu"), role="member")
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
    # NV mặc định xem được Lịch sử giao dịch (người dùng chốt 2026-11-05)
    assert (await staff.get(f"{API}/booking/transactions")).status_code == 200


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
    # Tên đăng nhập: họ tên liền + đuôi ngẫu nhiên, không chứa mã NV (người dùng chốt 2026-11-05)
    assert nv["staff_code"].startswith("NV")
    assert re.fullmatch(r"nguyenvandat\.[a-z2-9]{4}", nv["username"])
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


IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def test_list_and_revoke_sessions(admin):
    nv = await create_staff(admin, "Phiên Từ Xa")
    async with _client() as a, _client() as b:
        await a.post(
            f"{API}/auth/sign-in",
            json={"login": nv["username"], "password": PASSWORD},
            headers={"User-Agent": IPHONE_UA},
        )
        await sign_in(b, nv["username"], PASSWORD)
        rows = (await admin.get(f"{STAFF}/{nv['id']}/sessions")).json()
        assert len(rows) == 2
        for row in rows:
            # Người dùng chốt 2026-11-05: không trả IP, thêm loại máy / HĐH / trình duyệt
            assert set(row) == {"id", "device_type", "os", "browser", "created_at", "expires_at"}
        target = next(x for x in rows if x["device_type"] == "mobile")
        assert (target["os"], target["browser"]) == ("iOS", "Safari")
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


# ------------------------------------------------------------------ ảnh đại diện Admin / NV

AVATAR = f"{API}/admin/auth/me/avatar"


def _png(size: tuple[int, int] = (600, 400), color: tuple[int, int, int] = (9, 99, 199)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


async def _upload_avatar(c, data: bytes, size: int = 300, headers: dict | None = None):
    return await c.put(
        AVATAR,
        files={"file": ("a.png", data, "image/png")},
        data={"crop_x": 0, "crop_y": 0, "crop_size": size},
        headers=headers,
    )


async def test_admin_avatar_upload_serve_and_delete(admin):
    r = await _upload_avatar(admin, _png((800, 600)), size=600)
    assert r.status_code == 200, r.text
    assert "no-store" in r.headers["cache-control"]
    url = r.json()["avatar_url"]
    assert re.fullmatch(r"/api/v1/admin/auth/avatars/\d+\?v=[0-9a-f]{16}", url), url
    assert (await admin.get(f"{API}/admin/auth/me")).json()["avatar_url"] == url
    assert (await admin.get(f"{API}/admin/account")).json()["avatar_url"] == url

    img = await admin.get(url)
    assert img.status_code == 200 and img.headers["content-type"] == "image/webp"
    assert img.headers["x-content-type-options"] == "nosniff"
    # Ảnh chỉ phiên quản trị xem được -> không cho proxy dùng chung lưu
    assert img.headers["cache-control"].startswith("private")
    assert Image.open(io.BytesIO(img.content)).size == (512, 512), "cắt vuông, thu về 512 px"
    again = await admin.get(url, headers={"If-None-Match": img.headers["etag"]})
    assert again.status_code == 304 and not again.content
    async with _client() as anon:
        assert (await anon.get(url)).status_code == 401
    assert await audit_count("account.avatar_update") >= 1

    assert (await admin.delete(AVATAR)).status_code == 204
    assert (await admin.get(f"{API}/admin/auth/me")).json()["avatar_url"] is None
    assert (await admin.get(url)).status_code == 404
    assert await audit_count("account.avatar_delete") >= 1
    before = await audit_count("account.avatar_delete")
    assert (await admin.delete(AVATAR)).status_code == 204, "chưa có ảnh vẫn 204"
    assert await audit_count("account.avatar_delete") == before


async def test_admin_avatar_only_touches_own_account(admin):
    nv = await create_staff(admin, "Ảnh Riêng")
    assert (await _upload_avatar(admin, _png())).status_code == 200
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        r = await _upload_avatar(c, _png(color=(200, 10, 10)))
        assert r.status_code == 200, r.text
        url = r.json()["avatar_url"]
        assert f"/avatars/{nv['id']}?" in url
        row = next(x for x in (await admin.get(STAFF)).json() if x["id"] == nv["id"])
        assert row["avatar_url"] == url, "bảng Nhân viên có ảnh của NV"
        assert (await admin.get(url)).status_code == 200, "Admin xem được ảnh NV"
        # NV xóa ảnh của mình, ảnh Admin còn nguyên
        assert (await c.delete(AVATAR)).status_code == 204
        assert (await admin.get(f"{API}/admin/auth/me")).json()["avatar_url"] is not None
    assert (await admin.delete(AVATAR)).status_code == 204


async def test_admin_avatar_rejects_bad_files_and_customer(admin, customer):
    fake = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    bad = await _upload_avatar(admin, fake)
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "E-HV-13"
    assert bad.json()["detail"]["message"] == "Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB."
    bad = await _upload_avatar(admin, _png((100, 100)), size=300)
    assert (
        bad.status_code == 422 and bad.json()["detail"]["message"] == "Vùng cắt ảnh không hợp lệ."
    )
    evil = await _upload_avatar(admin, _png(), headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert (await admin.get(f"{API}/admin/auth/me")).json()["avatar_url"] is None
    # Khách không có phiên quản trị
    assert (await _upload_avatar(customer, _png())).status_code == 401
    assert (await customer.delete(AVATAR)).status_code == 401
    assert (await customer.get(f"{API}/admin/auth/avatars/1")).status_code == 401


async def test_admin_avatar_body_limit_allows_large_image_blocks_oversize(admin, monkeypatch):
    # Lớn hơn giới hạn body chung vẫn vào được; quá giới hạn ảnh -> cùng mã với ảnh hội viên
    monkeypatch.setattr(settings, "MAX_BODY_BYTES", 1_000)
    monkeypatch.setattr(settings, "AVATAR_MAX_BYTES", 500_000)
    noisy = io.BytesIO()
    Image.effect_noise((300, 300), 100).convert("RGB").save(noisy, "PNG")
    assert 1_000 < len(noisy.getvalue()) < 500_000
    assert (await _upload_avatar(admin, noisy.getvalue())).status_code == 200
    monkeypatch.setattr(settings, "AVATAR_MAX_BYTES", 2_000)
    r = await _upload_avatar(admin, noisy.getvalue())
    assert r.status_code in (413, 422) and r.json()["detail"]["code"] == "E-HV-13"
    assert (await admin.delete(AVATAR)).status_code == 204


# ------------------------------------------------------------------ logo web

LOGO = f"{API}/admin/site/logo"
BRANDING = f"{API}/site/branding"


def _transparent_png(size: int = 800, **save) -> bytes:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste((200, 30, 30, 255), (size // 4, size // 4, size // 2, size // 2))
    buf = io.BytesIO()
    img.save(buf, "PNG", **save)
    return buf.getvalue()


async def _upload_logo(c, data: bytes, size: int = 800, headers: dict | None = None):
    return await c.put(
        LOGO,
        files={"file": ("logo.png", data, "image/png")},
        data={"crop_x": 0, "crop_y": 0, "crop_size": size},
        headers=headers,
    )


async def test_logo_public_urls_alpha_cache_and_delete(admin, anon):
    before = (await anon.get(BRANDING)).json()
    assert before["logo_url"] is None and before["favicon_url"] is None
    icc = b"\0" * 128  # ảnh gốc mang metadata: ảnh ra không được giữ
    r = await _upload_logo(admin, _transparent_png(icc_profile=icc))
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["cache_tag"] == "site-branding"
    assert re.fullmatch(r"/api/v1/site/logo\?v=[0-9a-f]{16}", saved["logo_url"])
    assert re.fullmatch(r"/api/v1/site/favicon\?v=[0-9a-f]{16}", saved["favicon_url"])

    # Công khai: không cần phiên, trang khách đọc được
    branding = await anon.get(BRANDING)
    assert branding.json()["logo_url"] == saved["logo_url"]
    assert branding.json()["favicon_url"] == saved["favicon_url"]
    logo = await anon.get(saved["logo_url"])
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/webp"
    assert "immutable" in logo.headers["cache-control"]
    img = Image.open(io.BytesIO(logo.content))
    assert img.size == (512, 512) and img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0, "giữ nền trong suốt"
    assert "icc_profile" not in img.info

    favicon = await anon.get(saved["favicon_url"])
    assert favicon.status_code == 200 and favicon.headers["content-type"] == "image/png"
    small = Image.open(io.BytesIO(favicon.content))
    assert small.size == (64, 64) and small.getpixel((0, 0))[3] == 0
    assert "icc_profile" not in small.info

    again = await anon.get(saved["logo_url"], headers={"If-None-Match": logo.headers["etag"]})
    assert again.status_code == 304
    # Link không có ?v= đúng: cache ngắn, đổi logo là thấy
    assert "immutable" not in (await anon.get(f"{API}/site/logo")).headers["cache-control"]

    assert (await _upload_logo(admin, _transparent_png(400), size=400)).status_code == 200
    async with SessionLocal() as s:
        rows = await s.scalar(select(func.count()).select_from(SiteLogo))
    assert rows == 1, "chỉ một dòng logo"

    r = await admin.delete(LOGO)
    assert r.status_code == 200
    assert r.json() == {"logo_url": None, "favicon_url": None, "cache_tag": "site-branding"}
    assert (await anon.get(BRANDING)).json()["logo_url"] is None
    assert (await anon.get(saved["logo_url"])).status_code == 404
    assert (await anon.get(saved["favicon_url"])).status_code == 404
    assert (await admin.delete(LOGO)).status_code == 200, "chưa có logo vẫn 200"


async def test_logo_keeps_alpha_of_palette_png(admin, anon):
    img = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    img.paste((10, 200, 10, 255), (0, 0, 300, 300))
    buf = io.BytesIO()
    img.convert("P", palette=Image.Palette.ADAPTIVE).save(buf, "PNG", transparency=0)
    r = await _upload_logo(admin, buf.getvalue(), size=600)
    assert r.status_code == 200, r.text
    logo = await anon.get(r.json()["logo_url"])
    assert Image.open(io.BytesIO(logo.content)).convert("RGBA").getchannel("A").getextrema()[0] == 0
    assert (await admin.delete(LOGO)).status_code == 200


async def test_logo_admin_only_and_rejects_bad_files(admin, staff, anon, customer):
    # NV không làm được dù dòng quyền bị thêm tay vào bảng Phân quyền
    async with SessionLocal() as s:
        s.add(RolePermission(role="staff", perm="settings.site"))
        await s.commit()
    try:
        assert (await _upload_logo(staff, _transparent_png())).status_code == 403
        assert (await staff.delete(LOGO)).status_code == 403
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(RolePermission).where(RolePermission.perm == "settings.site"))
            await s.commit()
    assert (await _upload_logo(anon, _transparent_png())).status_code == 401
    assert (await _upload_logo(customer, _transparent_png())).status_code in (401, 403)

    svg = await _upload_logo(admin, b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    assert svg.status_code == 422 and svg.json()["detail"]["code"] == "E-HV-13"
    assert svg.json()["detail"]["message"] == "Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB."
    crop = await _upload_logo(admin, _transparent_png(100), size=300)
    assert crop.status_code == 422 and crop.json()["detail"]["code"] == "E-HV-13"
    evil = await _upload_logo(admin, _transparent_png(), headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert (await anon.get(BRANDING)).json()["logo_url"] is None


async def test_logo_body_limit_allows_large_image(admin, monkeypatch):
    monkeypatch.setattr(settings, "MAX_BODY_BYTES", 1_000)
    noisy = io.BytesIO()
    Image.effect_noise((300, 300), 100).convert("RGB").save(noisy, "PNG")
    assert len(noisy.getvalue()) > 1_000
    assert (await _upload_logo(admin, noisy.getvalue(), size=300)).status_code == 200
    assert (await admin.delete(LOGO)).status_code == 200


# ------------------------------------------------------------------ thông tin web

SITE_INFO = f"{API}/admin/site/info"
INFO_DEFAULT = {
    "name": "Sân Cầu Lông ABC",
    "address": "123 Đường ABC, Phường XYZ, Quận Cầu Giấy, Hà Nội",
    "phone": "0900 000 000",
    "email": "lienhe@example.com",
    "map_url": None,
    "lat": None,
    "lng": None,
}


@pytest.fixture
async def clean_site_info():
    """Mỗi test bắt đầu + kết thúc khi chưa lưu thông tin web (các test khác dùng mặc định)."""

    async def clear() -> None:
        async with SessionLocal() as s:
            await s.execute(delete(AppSetting).where(AppSetting.key == "site_info"))
            await s.commit()

    await clear()
    yield
    await clear()


async def test_site_info_defaults_save_and_public(admin, anon, clean_site_info):
    # Chưa lưu: đúng thông tin đang có ở frontend/src/lib/site.ts
    current = (await admin.get(SITE_INFO)).json()
    assert current == {**INFO_DEFAULT, "version": 0}
    public = (await anon.get(BRANDING)).json()
    assert {k: public[k] for k in INFO_DEFAULT} == INFO_DEFAULT and "version" not in public

    body = {
        "name": "  Sân   Mới ",
        "address": "1 Đường A,\n Quận B",
        "phone": "0912345678",
        "email": "Lien.He@Example.com",
        "version": 0,
    }
    r = await admin.put(SITE_INFO, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["cache_tag"] == "site-branding" and out["version"] == 1
    assert out["name"] == "Sân Mới" and out["address"] == "1 Đường A, Quận B", "trim, một dòng"
    assert out["phone"] == "0912 345 678", "server tách 4-3-3"
    public = (await anon.get(BRANDING)).json()
    assert public["name"] == "Sân Mới" and "short_name" not in public
    assert (await admin.get(SITE_INFO)).json()["version"] == 1

    # Không đổi gì: không tăng version, vẫn trả tag
    same = await admin.put(SITE_INFO, json={**body, "version": 1})
    assert same.status_code == 200 and same.json()["version"] == 1
    # Version cũ -> không ghi đè
    stale = await admin.put(SITE_INFO, json={**body, "name": "Ghi Đè", "version": 0})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "E-012"
    assert (await anon.get(BRANDING)).json()["name"] == "Sân Mới"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "   ", "Vui lòng nhập Tên sân."),
        ("name", "x" * 101, "Tên sân tối đa 100 ký tự."),
        ("address", "", "Vui lòng nhập Địa chỉ."),
        ("phone", "   ", "Vui lòng nhập Hotline."),
        ("email", "khong-phai-email", "Email không hợp lệ."),
    ],
)
async def test_site_info_validation(admin, clean_site_info, field, value, message):
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "version": 0, field: value})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "E-001" and r.json()["detail"]["message"] == message
    assert (await admin.get(SITE_INFO)).json()["version"] == 0


# Người dùng chốt 2026-11-06: chỉ di động 10 số; server tách 4-3-3, nhập số liền vẫn được
@pytest.mark.parametrize(
    ("phone", "saved"),
    [
        ("0912345678", "0912 345 678"),
        ("09 12 34 56 78", "0912 345 678"),
        ("0312345678", "0312 345 678"),
        ("0512345678", "0512 345 678"),
        ("0712345678", "0712 345 678"),
        ("0812345678", "0812 345 678"),
        ("0912 345 678", "0912 345 678"),
    ],
)
async def test_site_info_formats_hotline(admin, anon, clean_site_info, phone, saved):
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "phone": phone, "version": 0})
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == saved
    assert (await anon.get(BRANDING)).json()["phone"] == saved


@pytest.mark.parametrize(
    ("phone", "message"),
    [
        ("+84 912 345 678", "Hotline chỉ gồm chữ số."),
        ("0912.345.678", "Hotline chỉ gồm chữ số."),
        ("0912-345-678", "Hotline chỉ gồm chữ số."),
        ("abc", "Hotline chỉ gồm chữ số."),
        ("٠٩١٢٣٤٥٦٧٨", "Hotline chỉ gồm chữ số."),  # chữ số không phải ASCII
        ("091234567", "Hotline phải là số di động 10 số."),  # thiếu số
        ("09123456789", "Hotline phải là số di động 10 số."),  # thừa số
        ("0112345678", "Hotline phải là số di động 10 số."),  # đầu số lạ
        ("0612345678", "Hotline phải là số di động 10 số."),
        ("02431234567", "Hotline phải là số di động 10 số."),  # máy bàn
        ("0243 123 4567", "Hotline phải là số di động 10 số."),
        ("19001234", "Hotline phải là số di động 10 số."),  # tổng đài
        ("1800 1234", "Hotline phải là số di động 10 số."),
        ("1900123456", "Hotline phải là số di động 10 số."),
        ("1" * 30, "Hotline phải là số di động 10 số."),
    ],
)
async def test_site_info_rejects_bad_hotline(admin, clean_site_info, phone, message):
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "phone": phone, "version": 0})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "E-001" and r.json()["detail"]["message"] == message


async def test_site_info_same_hotline_written_differently_is_no_change(admin, clean_site_info):
    # Mặc định "0900 000 000" hợp lệ: gửi lại kiểu số liền -> không đổi
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "phone": "0900000000", "version": 0})
    assert r.status_code == 200 and r.json()["version"] == 0
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "phone": "0912345678", "version": 0})
    assert r.json()["version"] == 1
    before = await audit_count("settings.site_info")
    r = await admin.put(SITE_INFO, json={**INFO_DEFAULT, "phone": "0912 34 56 78", "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 1, "không tăng version"
    assert r.json()["phone"] == "0912 345 678"
    assert await audit_count("settings.site_info") == before, "không ghi nhật ký"


SHORT_LINK = "https://maps.app.goo.gl/AYnKCiQugfAs5ro87"
PLACE_LINK = (
    "https://www.google.com/maps/place/B%E1%BB%87nh+vi%E1%BB%87n+E/@21.045782,105.7904939,16.51z"
    "/data=!4m6!3m5!1s0x3135ab!8m2!3d21.0503396!4d105.7888586!16s"
)
RESOLVE = f"{API}/admin/site/map/resolve"


@pytest.fixture
def google(monkeypatch):
    """Giả Google, KHÔNG gọi mạng: ``routes`` = URL -> phản hồi; ghi lại mọi URL đã gọi."""
    routes: dict[str, httpx.Response | Exception] = {}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        answer = routes[str(request.url)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(
        site_map,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    return SimpleNamespace(routes=routes, seen=seen)


def _redirect(to: str) -> httpx.Response:
    return httpx.Response(302, headers={"location": to})


@pytest.mark.parametrize(
    ("link", "coords"),
    [
        (PLACE_LINK, (21.0503396, 105.7888586)),  # !3d!4d thắng @ (tâm khung nhìn)
        ("https://www.google.com/maps/search/21.046572,+105.790910", (21.046572, 105.79091)),
        (
            "https://www.google.com/maps/search/21.046572,%20105.790910?hl=vi",
            (21.046572, 105.79091),
        ),
        ("https://maps.google.com/?q=21.5,105.25", (21.5, 105.25)),
        ("https://www.google.com/maps?q=21.5,105.25&z=16", (21.5, 105.25)),
        ("https://www.google.com/maps/@21.5,105.25,16z", (21.5, 105.25)),
        ("https://www.google.com/maps/place/San+ABC", None),
        ("https://www.google.com/maps?q=San+ABC", None),
        ("https://www.google.com/maps/@91.5,105.25,16z", None),  # ngoài khoảng
    ],
)
def test_map_coords_in_link(link, coords):
    assert site_map.coords_in_link(link) == coords


async def test_map_resolve_short_link_writes_nothing(admin, google, clean_site_info):
    google.routes[SHORT_LINK] = _redirect(PLACE_LINK)
    google.routes[PLACE_LINK] = httpx.Response(200, text="<html>")
    r = await admin.post(RESOLVE, json={"input": f"  {SHORT_LINK} "})
    assert r.status_code == 200, r.text
    assert r.json() == {"map_url": SHORT_LINK, "lat": 21.0503396, "lng": 105.7888586}
    assert (await admin.get(SITE_INFO)).json()["map_url"] is None, "không ghi DB"

    # Link dài đã có tọa độ: không cần gọi mạng
    google.seen.clear()
    r = await admin.post(RESOLVE, json={"input": PLACE_LINK})
    assert r.json()["lat"] == 21.0503396 and google.seen == []
    # Link hợp lệ, không có tọa độ: giữ link
    r = await admin.post(RESOLVE, json={"input": "https://www.google.com/maps/place/San+ABC"})
    assert r.status_code == 200
    assert r.json() == {
        "map_url": "https://www.google.com/maps/place/San+ABC",
        "lat": None,
        "lng": None,
    }


@pytest.mark.parametrize(
    "text",
    [
        "",
        "khong phai link",
        "http://maps.app.goo.gl/abc",
        "https://evil.example/maps",
        "https://maps.app.goo.gl.evil.example/abc",
        "https://www.google.com@evil.example/maps",
        "https://user:pw@maps.google.com/maps",
        "https://www.google.com:8443/maps",
        "https://www.google.com/search?q=1",
        "https://www.google.com/maps/../url?q=https://evil.example",
        "https://www.google.com\\@evil.example/maps",
        "https://169.254.169.254/latest/meta-data",
        "javascript:alert(1)",
        # Không nhận mã nhúng (người dùng chốt 2026-11-06)
        "https://www.google.com/maps/embed?pb=!1m18!2d105.7!3d21.0",
        '<iframe src="https://www.google.com/maps/embed?pb=!1m18"></iframe>',
        "<script>alert(1)</script>",
    ],
)
async def test_map_resolve_rejects_without_network(admin, google, text):
    r = await admin.post(RESOLVE, json={"input": text})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "E-001"
    assert r.json()["detail"]["message"] == "Link Google Maps không hợp lệ."
    assert google.seen == [], "không gọi mạng khi link không qua allowlist"


@pytest.mark.parametrize(
    "target",
    ["https://evil.example/x", "http://www.google.com/maps/x", "http://169.254.169.254/latest"],
)
async def test_map_resolve_redirect_to_foreign_host_is_not_followed(admin, google, target):
    google.routes[SHORT_LINK] = _redirect(target)
    r = await admin.post(RESOLVE, json={"input": SHORT_LINK})
    assert r.status_code == 422
    assert r.json()["detail"]["message"] == "Link Google Maps không hợp lệ."
    assert google.seen == [SHORT_LINK], "kiểm allowlist trước khi đi tiếp"


async def test_map_resolve_google_failures_ask_to_retry(admin, google):
    retry = "Chưa đọc được link, hãy thử lại."

    async def expect_retry() -> None:
        r = await admin.post(RESOLVE, json={"input": SHORT_LINK})
        assert r.status_code == 422 and r.json()["detail"]["message"] == retry, r.text

    google.routes[SHORT_LINK] = httpx.ConnectTimeout("hết giờ")
    await expect_retry()
    google.routes[SHORT_LINK] = httpx.ConnectError("mạng lỗi")
    await expect_retry()
    google.routes[SHORT_LINK] = httpx.Response(500)
    await expect_retry()
    # Chuyển hướng quá 3 lần: dừng, không gọi lần thứ 5
    hops = [f"https://maps.google.com/maps/{i}" for i in range(5)]
    google.routes[SHORT_LINK] = _redirect(hops[0])
    for here, there in zip(hops, hops[1:], strict=False):
        google.routes[here] = _redirect(there)
    google.seen.clear()
    await expect_retry()
    assert len(google.seen) == 4, google.seen


async def test_map_resolve_admin_only(admin, staff, anon, google):
    body = {"input": PLACE_LINK}
    assert (await anon.post(RESOLVE, json=body)).status_code == 401
    assert (await staff.post(RESOLVE, json=body)).status_code == 403
    evil = await admin.post(RESOLVE, json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403


async def test_site_info_saves_map_with_server_side_checks(admin, anon, google, clean_site_info):
    body = {**INFO_DEFAULT, "version": 0}
    assert (await anon.get(BRANDING)).json()["map_url"] is None, "mặc định không có bản đồ"
    saved = {"map_url": SHORT_LINK, "lat": 21.03334567891, "lng": 105.8}
    r = await admin.put(SITE_INFO, json={**body, **saved})
    assert r.status_code == 200, r.text
    assert r.json()["lat"] == 21.0333457, "làm tròn 7 chữ số"
    public = (await anon.get(BRANDING)).json()
    assert public["map_url"] == SHORT_LINK and public["lng"] == 105.8
    assert "embed_url" not in public
    assert google.seen == [], "lưu không gọi mạng"
    # Link không có tọa độ vẫn lưu được
    r = await admin.put(SITE_INFO, json={**body, "version": 1, "map_url": SHORT_LINK})
    assert r.status_code == 200 and r.json()["lat"] is None
    # Không gửi = bỏ bản đồ
    r = await admin.put(SITE_INFO, json={**body, "version": 2})
    assert r.status_code == 200 and r.json()["map_url"] is None and r.json()["version"] == 3

    for bad in (
        {"map_url": "https://evil.example/maps"},
        {"map_url": "http://maps.app.goo.gl/abc"},
        {"map_url": "https://www.google.com/maps/embed?pb=!1m18"},
        {"lat": 21.0, "lng": 105.0},  # tọa độ không kèm link
        {"map_url": SHORT_LINK, "lat": 21.0},  # thiếu một trong hai
        {"map_url": SHORT_LINK, "lat": 90.1, "lng": 0},
        {"map_url": SHORT_LINK, "lat": 0, "lng": -180.1},
    ):
        r = await admin.put(SITE_INFO, json={**body, "version": 3, **bad})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001", bad
    extra = await admin.put(SITE_INFO, json={**body, "version": 3, "embed_url": "x"})
    assert extra.status_code == 422, "không còn trường embed_url"


async def test_site_info_admin_only_and_origin(admin, staff, anon, clean_site_info):
    body = {**INFO_DEFAULT, "name": "Sân Khác", "version": 0}
    assert (await anon.get(SITE_INFO)).status_code == 401
    assert (await anon.put(SITE_INFO, json=body)).status_code == 401
    assert (await staff.get(SITE_INFO)).status_code == 403
    assert (await staff.put(SITE_INFO, json=body)).status_code == 403
    evil = await admin.put(SITE_INFO, json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    assert (await admin.put(SITE_INFO, json={**body, "hack": 1})).status_code == 422
    # Chỉ dùng một tên (người dùng chốt 2026-11-06): short_name là trường lạ
    assert (await admin.put(SITE_INFO, json={**body, "short_name": "A"})).status_code == 422
    assert (await admin.get(SITE_INFO)).json()["version"] == 0


async def test_site_info_concurrent_first_save_one_wins(admin, clean_site_info):
    """Chưa có dòng để khóa: UNIQUE key của ``app_setting`` chặn người sau."""
    rs = await asyncio.gather(
        *[
            admin.put(SITE_INFO, json={**INFO_DEFAULT, "name": f"Sân {i}", "version": 0})
            for i in range(4)
        ]
    )
    codes = sorted(r.status_code for r in rs)
    assert codes == [200, 409, 409, 409], [r.text for r in rs]
    winner = next(r for r in rs if r.status_code == 200).json()
    assert (await admin.get(SITE_INFO)).json()["name"] == winner["name"]

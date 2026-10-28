import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import (
    hash_password,
)
from app.modules.auth.models import (
    AuditAction,
    LoginFailure,
    User,
)
from app.modules.auth.service import login as login_service
from app.modules.auth.utils import (
    parse_login,
)
from tests.client import API, make_client
from tests.helpers import (
    ADMIN,
    SIGN_IN,
    STAFF_PASSWORD,
    anon_post,
    audit_count,
    new_phone,
    staff_login,
)


async def test_register_sign_in_me_logout(anon):
    payload = {"phone": "0987 654 321", "password": "Password@123", "full_name": "Test"}
    r = await anon.post(f"{API}/auth/register", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "customer"
    assert body["phone"] == "0987654321"
    assert "email" not in body

    # Cùng SĐT viết dạng khác vẫn là một số (BR-002)
    r = await anon.post(f"{API}/auth/register", json={**payload, "phone": "+84987654321"})
    assert r.status_code == 409

    assert (await anon.get(f"{API}/auth/me")).status_code == 200
    assert (await anon.post(f"{API}/auth/refresh")).status_code == 200

    await anon.post(f"{API}/auth/logout")
    anon.cookies.clear()
    assert (await anon.get(f"{API}/auth/me")).status_code == 401

    # Lỗi của khách cũng trả {code, message} như khu quản trị
    r = await anon.post(SIGN_IN, json={"login": "0987654321", "password": "wrong-pass"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "E-001"
    assert r.json()["detail"]["message"]

    r = await anon.post(SIGN_IN, json={"login": "+84 987 654 321", "password": "Password@123"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "customer"
    assert body["account"]["phone"] == "0987654321"
    assert "access_token" in anon.cookies
    assert "admin_session" not in anon.cookies
    assert (await anon.get(f"{API}/admin/auth/me")).status_code == 401


async def test_register_rejects_invalid_phone_and_email_field(anon):
    r = await anon.post(
        f"{API}/auth/register",
        json={"phone": "abc", "password": "Password@123", "full_name": "Test"},
    )
    assert r.status_code == 422
    # Không còn đăng nhập bằng email
    r = await anon.post(SIGN_IN, json={"email": "a@b.vn", "password": "x"})
    assert r.status_code == 422


async def test_old_login_endpoints_removed(anon):
    for path in ["/auth/login", "/admin/auth/login"]:
        r = await anon.post(f"{API}{path}", json=ADMIN)
        assert r.status_code in (404, 405), path


async def test_customer_typing_unknown_username_is_e001(anon):
    """Khách không có tên đăng nhập ⇒ nhập tên (không phải SĐT) luôn E-001."""
    r = await anon.post(SIGN_IN, json={"login": "khach.hang", "password": "Password@123"})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "E-001"


async def test_successful_customer_sign_in_not_counted_for_ip(customer, anon, monkeypatch):
    """Nhiều khách đăng nhập đúng từ cùng IP sân không bị E-008 (lý do có endpoint chung)."""
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 3)
    phone = (await customer.get(f"{API}/auth/me")).json()["phone"]
    venue = {"X-Forwarded-For": "192.0.2.10"}
    for _ in range(settings.LOGIN_IP_MAX_ATTEMPTS + 2):
        r = await anon.post(
            SIGN_IN, json={"login": phone, "password": "Password@123"}, headers=venue
        )
        assert r.status_code == 200, r.text
    r = await anon.post(SIGN_IN, json=ADMIN, headers=venue)
    assert r.status_code == 200
    async with SessionLocal() as s:
        assert not (
            await s.scalars(select(LoginFailure).where(LoginFailure.ip == "192.0.2.10"))
        ).all()


@pytest.mark.parametrize("login", ["0912345678", "0912 345 678", "+84912345678"])
async def test_admin_sign_in_phone_formats(login):
    async with make_client() as c:
        r = await c.post(SIGN_IN, json={**ADMIN, "login": login})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "admin"
        assert body["account"] == {
            "kind": "admin",
            "display_name": "Admin",
            "role_label": "Chủ sân",
        }
        assert "admin_session" in c.cookies
        # Admin chỉ nhận phiên quản trị, không nhận JWT khách (bỏ BR-006)
        assert "access_token" not in c.cookies
        assert (await c.get(f"{API}/auth/me")).status_code == 401

        me = await c.get(f"{API}/admin/auth/me")
        assert me.status_code == 200
        # Hết hạn cứng 12 giờ sau đăng nhập
        expires = datetime.fromisoformat(me.json()["expires_at"])
        assert timedelta(hours=11, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=12)


async def test_sign_in_switches_session_kind(customer):
    """Trình duyệt chỉ giữ một loại phiên: đăng nhập Admin xóa JWT khách và ngược lại."""
    assert "access_token" in customer.cookies
    phone = (await customer.get(f"{API}/auth/me")).json()["phone"]

    r = await customer.post(SIGN_IN, json=ADMIN)
    assert r.json()["kind"] == "admin"
    assert "access_token" not in customer.cookies
    assert "admin_session" in customer.cookies

    r = await customer.post(SIGN_IN, json={"login": phone, "password": "Password@123"})
    assert r.json()["kind"] == "customer"
    assert "admin_session" not in customer.cookies
    assert "access_token" in customer.cookies


async def test_unknown_login_is_e001_without_locking(anon, monkeypatch):
    # Tên không tồn tại vẫn so mật khẩu (hash giả) ⇒ không dò được tài khoản qua thời gian phản hồi
    calls: list[str] = []
    real_verify = login_service.verify_password
    monkeypatch.setattr(
        login_service, "verify_password", lambda pw, h: calls.append(pw) or real_verify(pw, h)
    )
    for _ in range(settings.LOGIN_MAX_ATTEMPTS + 1):
        r = await anon.post(SIGN_IN, json={"login": "khong-ton-tai", "password": "x"})
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "E-001"
    assert len(calls) == settings.LOGIN_MAX_ATTEMPTS + 1


async def test_customer_has_no_admin_area(customer):
    me = (await customer.get(f"{API}/auth/me")).json()
    r = await customer.post(SIGN_IN, json={"login": me["phone"], "password": "Password@123"})
    assert r.json()["kind"] == "customer"
    assert (await customer.get(f"{API}/admin/auth/me")).status_code == 401


def test_parse_login_username_lowercase():
    assert parse_login("  NV.Le_01 ") == ("username", "nv.le_01")
    assert parse_login("0912 345 678") == ("phone", "0912345678")


async def test_staff_sign_in_by_username_any_case(staff):
    for login in [staff["username"], staff["username"].upper(), f"  {staff['username']} "]:
        async with make_client() as c:
            r = await c.post(SIGN_IN, json={"login": login, "password": STAFF_PASSWORD})
            assert r.status_code == 200, (login, r.text)
            body = r.json()
            assert body["kind"] == "admin"
            assert body["account"] == {
                "kind": "counter",
                "display_name": "Lê Văn Nhân",
                "role_label": "Nhân viên",
            }
            assert "admin_session" in c.cookies
            assert "access_token" not in c.cookies


async def test_lock_after_five_wrong_then_unlock(anon, staff):
    locked_before = await audit_count(AuditAction.LOGIN_LOCKED)
    wrong = staff_login(staff, "sai-mat-khau")
    for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
        r = await anon.post(SIGN_IN, json=wrong)
        assert r.json()["detail"]["code"] == "E-001"

    r = await anon.post(SIGN_IN, json=wrong)
    assert r.status_code == 423
    assert r.json()["detail"]["code"] == "E-002"
    # Câu thông báo theo cấu hình, không viết cứng
    assert f"sai {settings.LOGIN_MAX_ATTEMPTS} lần" in r.json()["detail"]["message"]
    assert f"sau {settings.LOGIN_LOCK_MINUTES} phút" in r.json()["detail"]["message"]
    # Số giây còn khóa để frontend đếm ngược
    lock_seconds = settings.LOGIN_LOCK_MINUTES * 60
    assert lock_seconds - 5 <= r.json()["detail"]["retry_after"] <= lock_seconds
    assert r.headers["retry-after"] == str(r.json()["detail"]["retry_after"])
    assert await audit_count(AuditAction.LOGIN_LOCKED) == locked_before + 1

    # Đang khóa: đúng mật khẩu vẫn E-002, không kéo dài khóa
    async with SessionLocal() as s:
        until = await s.scalar(select(User.locked_until).where(User.id == staff["id"]))
    r = await anon.post(SIGN_IN, json=staff_login(staff))
    assert r.json()["detail"]["code"] == "E-002"
    assert 0 < r.json()["detail"]["retry_after"] <= lock_seconds
    async with SessionLocal() as s:
        assert await s.scalar(select(User.locked_until).where(User.id == staff["id"])) == until

    # Hết 15 phút ⇒ đăng nhập được
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == staff["id"])
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert (await anon.post(SIGN_IN, json=staff_login(staff))).status_code == 200


async def test_concurrent_wrong_passwords_still_lock(staff):
    """5 lần sai gửi cùng lúc vẫn khóa: đếm dưới `SELECT … FOR UPDATE`, không mất lượt cộng."""
    wrong = staff_login(staff, "sai-mat-khau")

    async def attempt() -> int:
        async with make_client() as c:
            return (await c.post(SIGN_IN, json=wrong)).status_code

    codes = await asyncio.gather(*(attempt() for _ in range(settings.LOGIN_MAX_ATTEMPTS)))
    assert sorted(codes) == [401] * (settings.LOGIN_MAX_ATTEMPTS - 1) + [423]
    async with SessionLocal() as s:
        until = await s.scalar(select(User.locked_until).where(User.id == staff["id"]))
    assert until is not None and until > datetime.now(UTC)


async def test_ip_limit_blocks_after_too_many_failures(anon, monkeypatch):
    """IP sai quá N lần (mọi tài khoản) ⇒ 429 E-008, kể cả đúng mật khẩu; IP khác vẫn vào được."""
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 3)
    attacker = {"X-Forwarded-For": "203.0.113.7"}
    for login in ["khong-ton-tai", "0911111111", "ai-do"]:
        r = await anon.post(SIGN_IN, json={"login": login, "password": "x"}, headers=attacker)
        assert r.json()["detail"]["code"] == "E-001"

    r = await anon.post(SIGN_IN, json=ADMIN, headers=attacker)
    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["code"] == "E-008"
    window = settings.LOGIN_IP_WINDOW_MINUTES * 60
    assert window - 5 <= body["retry_after"] <= window
    assert r.headers["retry-after"] == str(body["retry_after"])

    # IP khác vẫn đăng nhập được; tài khoản không bị khóa vì lần sai của IP kia
    r = await anon.post(SIGN_IN, json=ADMIN, headers={"X-Forwarded-For": "203.0.113.8"})
    assert r.status_code == 200


async def test_ip_from_proxy_cannot_be_spoofed(anon, monkeypatch):
    """Lấy IP cuối của X-Forwarded-For (reverse proxy thêm); phần client tự ghi phía trước bị bỏ."""
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 3)
    for fake in ["1.1.1.1", "2.2.2.2", "3.3.3.3"]:
        await anon.post(
            SIGN_IN,
            json={"login": "khong-ton-tai", "password": "x"},
            headers={"X-Forwarded-For": f"{fake}, 198.51.100.9"},
        )
    r = await anon.post(SIGN_IN, json=ADMIN, headers={"X-Forwarded-For": "4.4.4.4, 198.51.100.9"})
    assert r.status_code == 429


async def test_old_weak_password_still_signs_in():
    """Luật chỉ áp khi đặt mật khẩu mới: tài khoản có mật khẩu yếu từ trước vẫn đăng nhập được."""
    phone = new_phone()
    async with SessionLocal() as s:
        s.add(User(phone=phone, full_name="Cũ", hashed_password=hash_password("yeu12345")))
        await s.commit()
    r = await anon_post(SIGN_IN, {"login": phone, "password": "yeu12345"})
    assert r.status_code == 200, r.text

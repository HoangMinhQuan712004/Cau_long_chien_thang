import asyncio

from httpx import Response
from sqlalchemy import delete

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import (
    LoginFailure,
)
from tests.client import API, make_client
from tests.helpers import (
    ADMIN,
    IPS,
    SIGN_IN,
    STAFF,
    new_phone,
)


async def test_xff_ignored_when_not_from_trusted_proxy(anon, monkeypatch):
    """Kết nối thẳng (không qua proxy tin cậy) tự đặt XFF ⇒ bỏ qua, dùng IP kết nối."""
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.0/8")
    async with SessionLocal() as s:
        await s.execute(delete(LoginFailure).where(LoginFailure.ip == "127.0.0.1"))
        await s.commit()
    try:
        for fake in ["1.1.1.1", "2.2.2.2"]:
            r = await anon.post(
                SIGN_IN,
                json={"login": "khong-ton-tai", "password": "x"},
                headers={"X-Forwarded-For": fake},
            )
            assert r.status_code == 401
        # Đổi XFF không thoát được: cả 2 lần đều tính cho 127.0.0.1
        r = await anon.post(SIGN_IN, json=ADMIN, headers={"X-Forwarded-For": "3.3.3.3"})
        assert r.status_code == 429
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(LoginFailure).where(LoginFailure.ip == "127.0.0.1"))
            await s.commit()


def test_client_ip_trusted_proxy_cidr(monkeypatch):
    from starlette.requests import Request

    from app.modules.auth.deps import client_ip

    def request(host: str) -> Request:
        headers = [(b"x-forwarded-for", b"9.9.9.9, 203.0.113.7")]
        return Request({"type": "http", "headers": headers, "client": (host, 1234)})

    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "172.16.0.0/12, ::1")
    assert client_ip(request("172.18.0.5")) == "203.0.113.7"  # web container trong mạng compose
    assert client_ip(request("::1")) == "203.0.113.7"
    assert client_ip(request("8.8.8.8")) == "8.8.8.8"
    assert client_ip(request("khong-phai-ip")) == "khong-phai-ip"


async def test_origin_forbidden_for_cookie_requests_from_other_site(customer, admin):
    evil = {"Origin": "https://evil.example.com"}
    # Có cookie phiên + Origin lạ ⇒ 403, kể cả route module khác
    for c, method, url in [
        (customer, "POST", f"{API}/auth/refresh"),
        (customer, "POST", f"{API}/bookings"),
        (admin, "POST", STAFF),
        (admin, "DELETE", f"{STAFF}/1/sessions/1"),
    ]:
        r = await c.request(method, url, json={}, headers=evil)
        assert r.status_code == 403, (method, url, r.text)
        assert r.json()["detail"]["code"] == "origin_forbidden"
    # Origin trong CORS_ORIGINS, cùng host (Next rewrite), hoặc không có Origin ⇒ qua
    for headers in [
        {"Origin": settings.CORS_ORIGINS[0]},
        {"Origin": "http://testserver"},
        {"Origin": "https://san.vn", "X-Forwarded-Host": "san.vn"},
        {},
    ]:
        assert (await customer.post(f"{API}/auth/refresh", headers=headers)).status_code == 200
    # GET hoặc không có cookie phiên ⇒ không chặn
    assert (await customer.get(f"{API}/auth/me", headers=evil)).status_code == 200
    async with make_client() as anon:
        r = await anon.post(SIGN_IN, json={"login": "khong-ton-tai", "password": "x"}, headers=evil)
        assert r.status_code == 401


async def test_forwarded_host_ignored_from_untrusted_client(customer, monkeypatch):
    """Không qua proxy tin cậy thì không tin X-Forwarded-Host (so với Host thật)."""
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", "10.0.0.0/8")
    headers = {"Origin": "https://evil.example.com", "X-Forwarded-Host": "evil.example.com"}
    r = await customer.post(f"{API}/auth/refresh", headers=headers)
    assert r.status_code == 403


async def test_register_rate_limited_per_ip(anon, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_IP_MAX_PER_HOUR", 3)
    headers = {"X-Forwarded-For": f"198.18.{next(IPS)}.1"}

    async def register(phone: str) -> Response:
        body = {"full_name": "Khách", "phone": phone, "password": "Password@123"}
        return await anon.post(f"{API}/auth/register", json=body, headers=headers)

    phone = new_phone()
    assert (await register(phone)).status_code == 201
    # Lần SĐT đã có (409) cũng tính ⇒ không dò SĐT hàng loạt; câu 409 giữ nguyên
    r = await register(phone)
    assert r.status_code == 409 and r.json()["detail"] == "Số điện thoại đã được sử dụng"
    assert (await register(new_phone())).status_code == 201
    r = await register(new_phone())
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "register_rate_limited"
    assert 0 < r.json()["detail"]["retry_after"] <= 3600
    assert r.headers["Retry-After"] == str(r.json()["detail"]["retry_after"])
    # IP khác không bị ảnh hưởng
    r = await anon.post(
        f"{API}/auth/register",
        json={"full_name": "Khách", "phone": new_phone(), "password": "Password@123"},
        headers={"X-Forwarded-For": f"198.18.{next(IPS)}.1"},
    )
    assert r.status_code == 201


async def test_register_concurrent_requests_respect_limit(monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_IP_MAX_PER_HOUR", 2)
    headers = {"X-Forwarded-For": f"198.18.{next(IPS)}.1"}
    async with make_client() as c:
        results = await asyncio.gather(
            *[
                c.post(
                    f"{API}/auth/register",
                    json={"full_name": "Khách", "phone": new_phone(), "password": "Password@123"},
                    headers=headers,
                )
                for _ in range(5)
            ]
        )
    assert sorted(r.status_code for r in results) == [201, 201, 429, 429, 429]

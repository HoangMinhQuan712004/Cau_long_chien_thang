import asyncio
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import service, utils
from app.modules.auth.models import (
    LoginFailure,
    User,
)
from tests.client import API, make_client
from tests.helpers import (
    CLIENT_ID,
    GOOGLE,
    GOOGLE_KEY,
    OTHER_KEY,
    SIGN_IN,
    FakeJwksClient,
    admin_user,
    get_me,
    google_client,
    google_id_token,
    new_ip,
    new_phone,
    pause_commit,
    request_and_verify_phone,
)


async def test_google_sign_in_creates_then_reuses_customer():
    sub = f"g-reuse-{datetime.now(UTC).timestamp()}"
    async with make_client() as c:
        r = await c.post(GOOGLE, json={"credential": google_id_token(sub)}, headers=new_ip())
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["kind"] == "customer"
        account = body["account"]
        assert account["phone"] is None and account["username"] is None
        assert account["full_name"] == "Nguyễn Google"
        assert account["google_email"] == "khach@gmail.com"
        assert account["role"] == "customer"
        assert (await get_me(c))["id"] == account["id"]
        assert (await c.post(f"{API}/auth/refresh")).status_code == 200

        # Lần sau: cùng tài khoản; email cập nhật theo Google, email chưa xác minh không ghi đè
        token = google_id_token(sub, email="moi@gmail.com")
        r = await c.post(GOOGLE, json={"credential": token}, headers=new_ip())
        assert r.json()["account"]["id"] == account["id"]
        assert r.json()["account"]["google_email"] == "moi@gmail.com"
        token = google_id_token(sub, email="la@gmail.com", email_verified=False)
        r = await c.post(GOOGLE, json={"credential": token}, headers=new_ip())
        assert r.json()["account"]["google_email"] == "moi@gmail.com"

    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.google_sub == sub))
        assert user is not None and user.hashed_password is None


async def test_google_unverified_email_not_stored():
    async with google_client(email="chua@gmail.com", email_verified=False) as c:
        assert (await get_me(c))["google_email"] is None


@pytest.mark.parametrize(
    ("claims", "key"),
    [
        ({"aud": "client-khac.apps.googleusercontent.com"}, GOOGLE_KEY),
        ({"iss": "https://evil.example.com"}, GOOGLE_KEY),
        ({"exp": datetime.now(UTC) - timedelta(minutes=1)}, GOOGLE_KEY),
        ({}, OTHER_KEY),  # chữ ký không phải của Google
        ({"sub": ""}, GOOGLE_KEY),
    ],
    ids=["aud", "iss", "exp", "signature", "sub"],
)
async def test_google_invalid_token_401_and_counts_for_ip(anon, claims, key):
    headers = new_ip()
    r = await anon.post(
        GOOGLE, json={"credential": google_id_token(key=key, **claims)}, headers=headers
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "google_invalid"
    assert "access_token" not in anon.cookies
    async with SessionLocal() as s:
        ip = headers["X-Forwarded-For"]
        assert await s.scalar(select(func.count()).where(LoginFailure.ip == ip)) == 1


async def test_google_garbage_and_hs256_token_401(anon):
    hs256 = jwt.encode(
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "x", "exp": 9999999999},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    for credential in ["khong-phai-jwt", hs256]:
        r = await anon.post(GOOGLE, json={"credential": credential}, headers=new_ip())
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "google_invalid"


async def test_google_ip_limit(anon, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 2)
    headers = new_ip()
    for _ in range(2):
        r = await anon.post(
            GOOGLE, json={"credential": google_id_token(key=OTHER_KEY)}, headers=headers
        )
        assert r.status_code == 401
    # IP bị chặn ⇒ token đúng cũng 429 (như đăng nhập mật khẩu)
    r = await anon.post(GOOGLE, json={"credential": google_id_token()}, headers=headers)
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "E-008"


async def test_google_disabled_without_client_id_404(anon, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = await anon.post(GOOGLE, json={"credential": google_id_token()})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "google_disabled"


async def test_google_jwks_unreachable_503(anon, monkeypatch):
    error = jwt.PyJWKClientConnectionError("timeout")
    monkeypatch.setattr(utils, "_jwks_client", lambda: FakeJwksClient(error))
    r = await anon.post(GOOGLE, json={"credential": google_id_token()}, headers=new_ip())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "google_unavailable"


async def test_google_sub_of_admin_or_staff_not_usable(anon, staff):
    """`google_sub` chỉ gắn cho khách – gắn tay cho Admin/nhân viên vẫn không vào được."""
    for user_id in [staff["id"], (await admin_user()).id]:
        sub = f"g-staff-{user_id}-{datetime.now(UTC).timestamp()}"
        async with SessionLocal() as s:
            await s.execute(update(User).where(User.id == user_id).values(google_sub=sub))
            await s.commit()
        try:
            r = await anon.post(GOOGLE, json={"credential": google_id_token(sub)}, headers=new_ip())
            assert r.status_code == 401
            assert "access_token" not in anon.cookies and "admin_session" not in anon.cookies
        finally:
            async with SessionLocal() as s:
                await s.execute(update(User).where(User.id == user_id).values(google_sub=None))
                await s.commit()


async def test_google_concurrent_first_sign_in_one_account():
    """Hai lần đăng nhập Google đầu tiên cùng lúc ⇒ một tài khoản."""
    sub = f"g-race-{datetime.now(UTC).timestamp()}"
    token = google_id_token(sub)
    release = asyncio.Event()
    async with SessionLocal() as first, SessionLocal() as second:
        pause_commit(first, release)
        task = asyncio.create_task(service.google_sign_in(first, token, None))
        await asyncio.sleep(0.2)  # lần 1 đã INSERT, chưa commit
        racing = asyncio.create_task(service.google_sign_in(second, token, None))
        await asyncio.sleep(0.2)  # lần 2 chờ unique index
        release.set()
        a, b = await task, await racing
        assert a.id == b.id
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).where(User.google_sub == sub)) == 1


async def test_google_account_password_sign_in_e001(sent_otps):
    """Tài khoản Google (không mật khẩu) đã có SĐT: đăng nhập mật khẩu luôn E-001 như sai."""
    phone = new_phone()
    async with google_client() as c:
        assert (await request_and_verify_phone(c, sent_otps, phone)).status_code == 200
    async with make_client() as anon:
        for password in ["", "x", "Password@123"]:
            r = await anon.post(
                SIGN_IN, json={"login": phone, "password": password or "a"}, headers=new_ip()
            )
            assert r.status_code == 401
            assert r.json()["detail"]["code"] == "E-001"

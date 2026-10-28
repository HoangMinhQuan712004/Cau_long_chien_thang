"""T-013 mốc 2: tài khoản khách – Google (AC20, SEC7), xác minh / gộp SĐT (AC22)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth import google
from app.modules.auth.models import Role, User
from tests.conftest import API, CUSTOMER_PASSWORD, _client, new_customer, sign_in, unique_phone

CLIENT_ID = "test-client.apps.googleusercontent.com"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
GOOGLE = f"{API}/auth/google"
PHONE = f"{API}/auth/phone"


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(google, "_signing_key", lambda _credential: _KEY.public_key())


def id_token(sub: str | None = None, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": sub or str(uuid.uuid4().int)[:21],
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "name": "Trần  Thị Google",
        "email": "khach@gmail.com",
        "email_verified": True,
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "k1"})


@asynccontextmanager
async def google_customer(sub: str | None = None) -> AsyncIterator[AsyncClient]:
    async with _client() as c:
        r = await c.post(GOOGLE, json={"credential": id_token(sub)})
        assert r.status_code == 200, r.text
        yield c


async def user_by(**where) -> User | None:
    async with SessionLocal() as s:
        q = select(User)
        for k, v in where.items():
            q = q.where(getattr(User, k) == v)
        return await s.scalar(q)


async def audit_actions(user_id: int) -> set[str]:
    async with SessionLocal() as s:
        return set(
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_code == str(user_id)))
        )


# ------------------------------------------------------------------ Google


async def test_google_creates_customer_once(anon):
    sub = str(uuid.uuid4().int)[:21]
    r = await anon.post(GOOGLE, json={"credential": id_token(sub)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "customer"
    account = body["account"]
    assert account["phone"] is None and account["phone_verified"] is False
    assert account["full_name"] == "Trần Thị Google"
    assert account["google_email"] == "khach@gmail.com" and account["role"] == "customer"
    assert "access_token=" in r.headers.get("set-cookie", "")
    assert (await anon.get(f"{API}/auth/me")).json()["id"] == account["id"]

    async with _client() as c:
        r = await c.post(GOOGLE, json={"credential": id_token(sub, email_verified=False)})
        assert r.json()["account"]["id"] == account["id"]
    user = await user_by(id=account["id"])
    assert user.hashed_password is None and user.phone is None


async def test_google_never_links_by_email(anon):
    email = f"{uuid.uuid4().hex[:10]}@gmail.com"
    async with SessionLocal() as s:
        old = User(
            email=email,
            username=f"u{uuid.uuid4().hex[:10]}",
            full_name="Khách cũ",
            hashed_password=hash_password(CUSTOMER_PASSWORD),
            role=Role.CUSTOMER,
        )
        s.add(old)
        await s.commit()
    r = await anon.post(GOOGLE, json={"credential": id_token(email=email)})
    assert r.status_code == 200
    assert r.json()["account"]["id"] != old.id


async def test_google_concurrent_first_sign_in_makes_one_account():
    sub = str(uuid.uuid4().int)[:21]

    async def once():
        async with _client() as c:
            r = await c.post(GOOGLE, json={"credential": id_token(sub)})
            assert r.status_code == 200, r.text
            return r.json()["account"]["id"]

    ids = await asyncio.gather(*(once() for _ in range(4)))
    assert len(set(ids)) == 1
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).where(User.google_sub == sub)) == 1


@pytest.mark.parametrize(
    "credential",
    [
        pytest.param(
            lambda: jwt.encode({"sub": "1", "aud": CLIENT_ID}, "s" * 32, algorithm="HS256"),
            id="hs256",
        ),
        pytest.param(lambda: id_token(aud="other-client"), id="aud"),
        pytest.param(lambda: id_token(iss="https://evil.example"), id="iss"),
        pytest.param(lambda: id_token(exp=datetime.now(UTC) - timedelta(minutes=1)), id="expired"),
        pytest.param(lambda: "khong-phai-jwt", id="garbage"),
    ],
)
async def test_google_rejects_bad_tokens(anon, credential):
    # HS256 bị chặn vì thuật toán cố định RS256 (không dùng khóa công khai làm HMAC secret)
    r = await anon.post(GOOGLE, json={"credential": credential()})
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "E-AUTH-20"


async def test_google_bad_tokens_count_toward_ip_limit(anon, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_IP_MAX_ATTEMPTS", 2)
    for _ in range(2):
        r = await anon.post(GOOGLE, json={"credential": id_token(aud="other")})
        assert r.status_code == 401
    r = await anon.post(GOOGLE, json={"credential": id_token()})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-AUTH-12"


async def test_google_disabled_and_unavailable(anon, monkeypatch):
    def down(_credential):
        raise jwt.PyJWKClientConnectionError("down")

    monkeypatch.setattr(google, "_signing_key", down)
    r = await anon.post(GOOGLE, json={"credential": id_token()})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-AUTH-21"

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = await anon.post(GOOGLE, json={"credential": id_token()})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-AUTH-19"


async def test_google_sub_of_staff_or_inactive_is_rejected(anon):
    sub = str(uuid.uuid4().int)[:21]
    async with SessionLocal() as s:
        s.add(
            User(
                username=f"nv{uuid.uuid4().hex[:8]}",
                full_name="NV có Google",
                hashed_password=hash_password(CUSTOMER_PASSWORD),
                role=Role.STAFF,
                google_sub=sub,
            )
        )
        await s.commit()
    r = await anon.post(GOOGLE, json={"credential": id_token(sub)})
    assert r.status_code == 401 and r.json()["detail"]["code"] == "E-AUTH-20"

    sub2 = str(uuid.uuid4().int)[:21]
    async with google_customer(sub2):
        pass
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.google_sub == sub2))
        user.is_active = False
        await s.commit()
    r = await anon.post(GOOGLE, json={"credential": id_token(sub2)})
    assert r.status_code == 401


async def test_google_credential_too_long(anon):
    r = await anon.post(GOOGLE, json={"credential": "a" * 4097})
    assert r.status_code == 422


# ------------------------------------------------------------------ xác minh SĐT


async def phone_code(client, phone: str) -> str:
    r = await client.post(f"{PHONE}/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    return r.json()["test_otp"]


async def test_google_customer_attaches_free_phone():
    phone = unique_phone()
    async with google_customer() as c:
        otp = await phone_code(c, phone)
        r = await c.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["merged"] is False and body["password_cleared"] is False
        assert body["account"]["phone"] == phone and body["account"]["phone_verified"] is True
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["phone"] == phone
        assert "auth.phone_verified" in await audit_actions(me["id"])

        # Đã có SĐT
        r = await c.post(f"{PHONE}/request", json={"phone": unique_phone()})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-AUTH-17"


async def test_merge_google_into_phone_owner():
    phone = unique_phone()
    sub = str(uuid.uuid4().int)[:21]
    async with new_customer(phone) as owner_client:
        owner_id = (await owner_client.get(f"{API}/auth/me")).json()["id"]
        async with google_customer(sub) as c:
            google_id = (await c.get(f"{API}/auth/me")).json()["id"]
            otp = await phone_code(c, phone)
            r = await c.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["merged"] is True and body["password_cleared"] is True
            assert body["account"]["id"] == owner_id
            assert body["account"]["google_email"] == "khach@gmail.com"
            assert body["account"]["phone_verified"] is True
            # JWT mới là của chủ SĐT
            assert (await c.get(f"{API}/auth/me")).json()["id"] == owner_id
        # JWT cũ của chủ SĐT hết hiệu lực (mật khẩu bị hủy -> token_version tăng)
        assert (await owner_client.get(f"{API}/auth/me")).status_code == 401

    assert await user_by(id=google_id) is None
    async with _client() as c:
        assert (await sign_in(c, phone, CUSTOMER_PASSWORD)).status_code == 401
        r = await c.post(GOOGLE, json={"credential": id_token(sub)})
        assert r.json()["account"]["id"] == owner_id
    assert "auth.account_merged" in await audit_actions(owner_id)


async def test_phone_of_admin_or_google_owner_is_unusable(monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
    # Chủ SĐT là Admin
    async with google_customer() as c:
        otp = await phone_code(c, settings.FIRST_ADMIN_PHONE)
        r = await c.post(f"{PHONE}/verify", json={"phone": settings.FIRST_ADMIN_PHONE, "otp": otp})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-AUTH-18"

    # Chủ SĐT đã có Google khác
    phone = unique_phone()
    async with google_customer() as first:
        otp = await phone_code(first, phone)
        r = await first.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 200
    async with google_customer() as second:
        otp = await phone_code(second, phone)
        r = await second.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-AUTH-18"
    assert (await user_by(phone=phone)).google_sub is not None


async def test_code_is_bound_to_requesting_account():
    phone = unique_phone()
    async with google_customer() as a, google_customer() as b:
        otp = await phone_code(a, phone)
        r = await b.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-15"
        r = await a.post(
            f"{PHONE}/verify", json={"phone": phone, "otp": f"{(int(otp) + 1) % 10**6:06d}"}
        )
        assert r.status_code == 400 and r.json()["detail"]["attempts_left"] == 4
        r = await a.post(f"{PHONE}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 200


async def test_phone_endpoints_need_customer(anon, admin, monkeypatch):
    for client in (anon, admin):
        r = await client.post(f"{PHONE}/request", json={"phone": unique_phone()})
        assert r.status_code == 401
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    async with google_customer() as c:
        r = await c.post(f"{PHONE}/request", json={"phone": unique_phone()})
        assert r.status_code == 503 and r.json()["detail"]["code"] == "E-AUTH-24"

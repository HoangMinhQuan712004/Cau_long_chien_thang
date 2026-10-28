"""Hằng số + hàm dùng chung cho test auth/staff."""

import asyncio
import itertools
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient, Response
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import (
    AuditAction,
    AuditLog,
    LoginFailure,
    PasswordResetCode,
    PasswordResetRequest,
    Role,
    User,
)
from tests.client import API, make_client

SIGN_IN = f"{API}/auth/sign-in"


STAFF = f"{API}/admin/staff"


ADMIN = {"login": settings.FIRST_ADMIN_PHONE, "password": settings.FIRST_ADMIN_PASSWORD}


STAFF_PASSWORD = "NhanVien@123"


RESET_REQUEST = f"{API}/auth/password-reset/request"


RESET_VERIFY = f"{API}/auth/password-reset/verify"


RESET_CONFIRM = f"{API}/auth/password-reset/confirm"


GOOGLE = f"{API}/auth/google"


PHONE_REQUEST = f"{API}/auth/phone/request"


PHONE_VERIFY = f"{API}/auth/phone/verify"


CLIENT_ID = "test-client.apps.googleusercontent.com"


GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


_google_subs = itertools.count(1)


IPS = itertools.count(1)


_phones = itertools.count(1)


async def reset_state() -> None:
    """Mỗi test bắt đầu với Admin không bị khóa và IP chưa bị chặn."""
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.role == Role.ADMIN)
            .values(failed_login_count=0, locked_until=None)
        )
        # Lần sai theo IP / yêu cầu gửi mã của test trước không làm test sau bị chặn
        await s.execute(delete(LoginFailure))
        await s.execute(delete(PasswordResetRequest))
        await s.execute(delete(PasswordResetCode))
        await s.commit()


async def new_staff(admin: AsyncClient, full_name: str = "Lê Văn Nhân") -> dict:
    r = await admin.post(STAFF, json={"full_name": full_name, "password": STAFF_PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


async def anon_post(url: str, payload: dict) -> Response:
    """POST bằng client mới (không cookie)."""
    async with make_client() as c:
        return await c.post(url, json=payload)


def staff_login(staff: dict, password: str = STAFF_PASSWORD) -> dict:
    return {"login": staff["username"], "password": password}


async def audit_count(action: AuditAction, target_user_id: int | None = None) -> int:
    query = select(AuditLog).where(AuditLog.action == action)
    if target_user_id is not None:
        query = query.where(AuditLog.target_user_id == target_user_id)
    async with SessionLocal() as s:
        return len((await s.scalars(query)).all())


async def get_me(client: AsyncClient) -> dict:
    return (await client.get(f"{API}/auth/me")).json()


async def get_reset_token(anon: AsyncClient, phone: str, otp: str) -> str:
    r = await anon.post(RESET_VERIFY, json={"phone": phone, "otp": otp})
    assert r.status_code == 200, r.text
    return r.json()["reset_token"]


async def request_otp(anon: AsyncClient, sent: dict[int, str], user: dict) -> str:
    r = await anon.post(RESET_REQUEST, json={"phone": user["phone"]})
    assert r.status_code == 202, r.text
    return sent[user["id"]]


async def rewind_requests(seconds: int) -> None:
    """Giả như các yêu cầu gửi mã đã cách đây `seconds` giây (qua giới hạn gửi lại)."""
    async with SessionLocal() as s:
        await s.execute(
            update(PasswordResetRequest).values(
                created_at=PasswordResetRequest.created_at - timedelta(seconds=seconds)
            )
        )
        await s.commit()


async def code_count(user_id: int) -> int:
    async with SessionLocal() as s:
        return len(
            (
                await s.scalars(
                    select(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
                )
            ).all()
        )


class FakeJwksClient:
    """Thay PyJWKClient: không tải JWKS thật của Google, khóa công khai là khóa test."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if self.error is not None:
            raise self.error
        jwt.get_unverified_header(token)  # token rác ⇒ DecodeError như client thật
        return jwt.PyJWK.from_dict(
            {**json.loads(RSAAlgorithm.to_jwk(GOOGLE_KEY.public_key())), "alg": "RS256"}
        )


def google_id_token(sub: str | None = None, *, key=GOOGLE_KEY, **claims) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": f"g-{next(_google_subs)}-{now.timestamp()}" if sub is None else sub,
        "iat": now,
        "exp": now + timedelta(hours=1),
        "name": "Nguyễn Google",
        "email": "khach@gmail.com",
        "email_verified": True,
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})


def new_ip() -> dict[str, str]:
    """IP riêng mỗi test (giới hạn IP dùng chung bảng `login_failures`)."""
    return {"X-Forwarded-For": f"10.77.{next(IPS)}.1"}


@asynccontextmanager
async def google_client(sub: str | None = None, **claims) -> AsyncIterator[AsyncClient]:
    """Client đã đăng nhập bằng một tài khoản Google (mới nếu `sub` chưa có)."""
    async with make_client() as c:
        r = await c.post(
            GOOGLE, json={"credential": google_id_token(sub, **claims)}, headers=new_ip()
        )
        assert r.status_code == 200, r.text
        yield c


async def request_and_verify_phone(c: AsyncClient, sent: dict[int, str], phone: str) -> Response:
    me = await get_me(c)
    r = await c.post(PHONE_REQUEST, json={"phone": phone})
    assert r.status_code == 202, r.text
    return await c.post(PHONE_VERIFY, json={"phone": phone, "otp": sent[me["id"]]})


async def admin_user() -> User:
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.phone == settings.FIRST_ADMIN_PHONE))
        assert user is not None
        return user


def new_phone() -> str:
    return f"0388{next(_phones):06d}"


def pause_commit(session, release: asyncio.Event) -> None:
    """Cho transaction dừng ngay trước commit tới khi `release` (ép hai request xen kẽ)."""
    commit = session.commit

    async def paused() -> None:
        await release.wait()
        await commit()

    session.commit = paused

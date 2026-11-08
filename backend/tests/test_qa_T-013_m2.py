# ruff: noqa: E501
"""QA T-013 mốc 2: OTP + quên mật khẩu, Google, xác minh/gộp SĐT, phone_token đặt online, lệnh cứu Admin.

Viết theo spec ``board/tasks/T-013-dang-nhap-nhan-vien.md`` (AC14–AC31, SEC1–SEC8), không theo code BE.
"""

import asyncio
import hashlib
import hmac
import re
import time
import uuid
from datetime import datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import Settings, settings
from app.core.db import engine
from app.core.security import hash_password
from app.modules.auth import google
from app.scripts import reset_admin_password as cli
from tests.conftest import (
    API,
    CUSTOMER_PASSWORD,
    ENQUEUED_JOBS,
    _client,
    idem,
    sign_in,
    unique_phone,
    vn_today,
)
from tests.helpers_booking import safe_hour
from tests.qa_accounts import db_account

WEB = f"{API}/web/booking"
PR = f"{API}/auth/password-reset"
ADMIN_PHONE = settings.FIRST_ADMIN_PHONE
ADMIN_PW = settings.FIRST_ADMIN_PASSWORD
EVIL = "https://evil.example"
CLIENT_ID = "qa-client-id.apps.googleusercontent.com"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def err(r) -> dict:
    return r.json()["detail"]


async def age_codes(phone: str, seconds: int = 120) -> None:
    """Đẩy thời điểm tạo mã lùi lại để qua giới hạn gửi lại 60 giây (không đụng giới hạn theo giờ)."""
    await x(
        "UPDATE otp_codes SET created_at = created_at - make_interval(secs => :s) WHERE phone = :p",
        s=seconds,
        p=phone,
    )


async def clean_otps() -> None:
    """Giới hạn gửi mã đếm trên bảng ``otp_codes`` theo SĐT / IP: test cần giới hạn bắt đầu từ 0."""
    await x("DELETE FROM otp_codes")


def sha256(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def hmac_otp(otp: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), otp.encode(), hashlib.sha256).hexdigest()


async def register(anon: AsyncClient, phone: str | None = None, password: str = CUSTOMER_PASSWORD):
    """Tài khoản khách chưa xác minh SĐT, đã đăng nhập trên ``anon`` (T-021: /auth/register đóng, tạo qua DB)."""
    phone = phone or unique_phone()
    return await db_account(anon, phone, "Khách OTP", password)


# ---------------------------------------------------------------- Google (khóa RSA thử)

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def gsetup(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(google, "_signing_key", lambda credential: _KEY.public_key())


def gtoken(sub=None, **over) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": sub if sub is not None else f"g-{uuid.uuid4().hex}",
        "iat": now,
        "exp": now + 3600,
        "name": "Người Dùng Google",
        "email": f"{uuid.uuid4().hex[:8]}@gmail.com",
        "email_verified": True,
        **over,
    }
    claims = {k: v for k, v in claims.items() if v is not ...}
    return jwt.encode(claims, _KEY, algorithm="RS256")


async def google_login(client: AsyncClient, token: str):
    return await client.post(f"{API}/auth/google", json={"credential": token})


async def google_customer(sub=None, **over) -> AsyncClient:
    c = _client()
    r = await google_login(c, gtoken(sub, **over))
    assert r.status_code == 200, r.text
    return c


# ================================================================ AC14–AC17 quên mật khẩu (OTP)


async def test_ac14_full_reset_flow_for_a_customer(anon):
    phone = await register(anon, password="Old-Pass-1")
    old_jwt = anon.cookies["access_token"]
    async with _client() as c:
        r = await c.post(f"{PR}/request", json={"phone": phone})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["resend_after"] == 60 and re.fullmatch(r"\d{6}", body["test_otp"])
        v = await c.post(f"{PR}/verify", json={"phone": phone, "otp": body["test_otp"]})
        assert v.status_code == 200 and v.json()["reset_token"]
        weak = await c.post(
            f"{PR}/confirm", json={"reset_token": v.json()["reset_token"], "password": "weakpass"}
        )
        assert weak.status_code == 422
        ok = await c.post(
            f"{PR}/confirm", json={"reset_token": v.json()["reset_token"], "password": "New-Pass-2"}
        )
        assert ok.status_code == 204
        assert (await sign_in(c, phone, "Old-Pass-1")).status_code == 401
        assert (await sign_in(c, phone, "New-Pass-2")).status_code == 200
    stale = _client()
    stale.cookies.set("access_token", old_jwt)
    assert (await stale.get(f"{API}/auth/me")).status_code == 401, "AC6: old JWT dies after reset"
    row = (await q("SELECT phone_verified_at FROM users WHERE phone=:p", p=phone))[0]
    assert row["phone_verified_at"] is not None, "receiving the code proves the phone"
    assert await q("SELECT 1 FROM audit_log WHERE action='auth.password_reset_done'")


async def test_ac15_unknown_phone_gets_the_same_202_and_same_failures(anon):
    known = await register(anon)
    ghost = unique_phone()
    async with _client() as c:
        a = await c.post(f"{PR}/request", json={"phone": known})
        b = await c.post(f"{PR}/request", json={"phone": ghost})
    assert a.status_code == b.status_code == 202
    assert set(a.json()) - {"test_otp"} == set(b.json()) - {"test_otp"}
    assert a.json()["resend_after"] == b.json()["resend_after"]
    # xác minh với SĐT không có tài khoản: lỗi y hệt mã sai, có đếm lượt, rồi "hết hiệu lực"
    seen_known, seen_ghost = [], []
    for phone, seen in ((known, seen_known), (ghost, seen_ghost)):
        for _ in range(5):
            async with _client() as c:
                r = await c.post(f"{PR}/verify", json={"phone": phone, "otp": "000000"})
            seen.append((r.status_code, err(r)["code"], err(r).get("attempts_left")))
        async with _client() as c:
            r = await c.post(f"{PR}/verify", json={"phone": phone, "otp": "000000"})
        seen.append((r.status_code, err(r)["code"], err(r).get("attempts_left")))
    assert seen_known == seen_ghost, (seen_known, seen_ghost)
    assert seen_known[0] == (400, "E-AUTH-14", 4) and seen_known[4] == (400, "E-AUTH-14", 0)
    assert seen_known[5][1] == "E-AUTH-15"


async def test_ac15_verify_without_any_request_is_same_for_known_and_unknown(anon):
    known = await register(anon)
    outs = []
    for phone in (known, unique_phone()):
        async with _client() as c:
            r = await c.post(f"{PR}/verify", json={"phone": phone, "otp": "123456"})
        outs.append((r.status_code, err(r)["code"], err(r)["message"]))
    assert outs[0] == outs[1] and outs[0][1] == "E-AUTH-15"


async def test_ac16_five_wrong_codes_kill_the_code_and_new_code_replaces_old(anon):
    phone = await register(anon)
    async with _client() as c:
        first = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        for i in range(5):
            r = await c.post(
                f"{PR}/verify",
                json={"phone": phone, "otp": "999999" if first != "999999" else "888888"},
            )
            assert err(r)["code"] == "E-AUTH-14" and err(r)["attempts_left"] == 4 - i
        dead = await c.post(f"{PR}/verify", json={"phone": phone, "otp": first})
        assert dead.status_code == 400 and err(dead)["code"] == "E-AUTH-15", (
            "right code after 5 misses is dead"
        )
        await age_codes(phone)
        second = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        await age_codes(phone)
        third = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        if second != third:
            old = await c.post(f"{PR}/verify", json={"phone": phone, "otp": second})
            assert old.status_code == 400, "a newer code invalidates the previous one"
        ok = await c.post(f"{PR}/verify", json={"phone": phone, "otp": third})
        assert ok.status_code == 200, ok.text


async def test_ac16_code_expires_after_ttl(anon):
    phone = await register(anon)
    async with _client() as c:
        otp = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        await x(
            "UPDATE otp_codes SET expires_at = now() - interval '1 second' WHERE phone=:p", p=phone
        )
        r = await c.post(f"{PR}/verify", json={"phone": phone, "otp": otp})
        assert r.status_code == 400 and err(r)["code"] == "E-AUTH-15"


async def test_ac16_ttl_is_five_minutes(anon):
    phone = await register(anon)
    async with _client() as c:
        await c.post(f"{PR}/request", json={"phone": phone})
    row = (
        await q(
            "SELECT created_at, expires_at FROM otp_codes WHERE phone=:p ORDER BY id DESC LIMIT 1",
            p=phone,
        )
    )[0]
    assert 290 <= (row["expires_at"] - row["created_at"]).total_seconds() <= 310


async def test_ac16_resend_only_after_60_seconds(anon):
    phone = await register(anon)
    async with _client() as c:
        assert (await c.post(f"{PR}/request", json={"phone": phone})).status_code == 202
        r = await c.post(f"{PR}/request", json={"phone": phone})
        assert r.status_code == 429 and err(r)["code"] == "E-AUTH-13"
        assert 0 < err(r)["retry_after"] <= 60 and r.headers.get("retry-after")
        await age_codes(phone, 61)
        assert (await c.post(f"{PR}/request", json={"phone": phone})).status_code == 202


async def test_ac16_five_codes_per_hour_per_phone(anon):
    phone = await register(anon)
    async with _client() as c:
        for _ in range(5):
            assert (await c.post(f"{PR}/request", json={"phone": phone})).status_code == 202
            await age_codes(phone, 61)
        r = await c.post(f"{PR}/request", json={"phone": phone})
        assert r.status_code == 429 and err(r)["code"] == "E-AUTH-13"
        assert err(r)["retry_after"] > 600, "wait until the hour window frees a slot, not just 60s"
    ghost = unique_phone()  # SĐT không tài khoản cũng bị đếm y hệt
    async with _client() as c:
        for _ in range(5):
            assert (await c.post(f"{PR}/request", json={"phone": ghost})).status_code == 202
            await age_codes(ghost, 61)
        assert (await c.post(f"{PR}/request", json={"phone": ghost})).status_code == 429


async def test_ac16_per_ip_limit_counts_unknown_phones_too(anon, monkeypatch):
    await clean_otps()
    monkeypatch.setattr(settings, "OTP_IP_MAX_PER_HOUR", 3)
    for i in range(3):
        r = await anon.post(f"{PR}/request", json={"phone": unique_phone()})
        assert r.status_code == 202, (i, r.text)
    r = await anon.post(f"{PR}/request", json={"phone": unique_phone()})
    assert r.status_code == 429 and err(r)["code"] == "E-AUTH-13"


async def test_ac16_concurrent_requests_issue_one_code(anon):
    phone = await register(anon)

    async def one():
        async with _client() as c:
            return (await c.post(f"{PR}/request", json={"phone": phone})).status_code

    codes = sorted(await asyncio.gather(*[one() for _ in range(6)]))
    assert codes == [202, 429, 429, 429, 429, 429], codes
    assert len(await q("SELECT 1 FROM otp_codes WHERE phone=:p", p=phone)) == 1


async def test_ac17_reset_token_is_single_use_and_expires(anon):
    phone = await register(anon)
    async with _client() as c:
        otp = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        token = (await c.post(f"{PR}/verify", json={"phone": phone, "otp": otp})).json()[
            "reset_token"
        ]
        row = (
            await q(
                "SELECT token_hash, token_expires_at, created_at FROM otp_codes WHERE phone=:p",
                p=phone,
            )
        )[0]
        assert row["token_hash"] == sha256(token), "only SHA-256 of the token is stored"
        assert (
            9 * 60 <= (row["token_expires_at"] - row["created_at"]).total_seconds() <= 10 * 60 + 15
        )
        assert (
            await c.post(f"{PR}/confirm", json={"reset_token": token, "password": "Next-Pass-3"})
        ).status_code == 204
        again = await c.post(
            f"{PR}/confirm", json={"reset_token": token, "password": "Other-Pass-4"}
        )
        assert again.status_code == 400 and err(again)["code"] == "E-AUTH-16"
        for bad in ("", "x" * 200, "not-a-token", token[::-1]):
            r = await c.post(f"{PR}/confirm", json={"reset_token": bad, "password": "Next-Pass-3"})
            assert r.status_code in (400, 422), bad
            if r.status_code == 400:
                assert err(r)["code"] == "E-AUTH-16"


async def test_ac17_expired_reset_token_is_e_auth_16(anon):
    phone = await register(anon)
    async with _client() as c:
        otp = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        token = (await c.post(f"{PR}/verify", json={"phone": phone, "otp": otp})).json()[
            "reset_token"
        ]
        await x(
            "UPDATE otp_codes SET token_expires_at = now() - interval '1 second' WHERE phone=:p",
            p=phone,
        )
        r = await c.post(f"{PR}/confirm", json={"reset_token": token, "password": "Next-Pass-3"})
        assert r.status_code == 400 and err(r)["code"] == "E-AUTH-16"


async def test_ac17_other_purpose_tokens_are_not_reset_tokens(anon):
    phone = unique_phone()
    async with _client() as c:
        otp = (await c.post(f"{WEB}/phone/request", json={"phone": phone})).json()["test_otp"]
        ptoken = (await c.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": otp})).json()[
            "phone_token"
        ]
        r = await c.post(f"{PR}/confirm", json={"reset_token": ptoken, "password": "Next-Pass-3"})
        assert r.status_code == 400 and err(r)["code"] == "E-AUTH-16", (
            "booking token must not reset passwords"
        )


async def test_ac17_reset_unlocks_account_and_revokes_admin_sessions(anon, admin, caplog):
    await clean_otps()
    caplog.set_level("WARNING")
    # NV không có SĐT -> dùng Admin: quên MK của Admin, mã chỉ ở log server (AC29)
    for _ in range(5):
        await sign_in(anon, ADMIN_PHONE, "Wrong-Pass1")
    assert (await sign_in(anon, ADMIN_PHONE, ADMIN_PW)).status_code == 423, "locked"
    admin_before = (await admin.get(f"{API}/admin/auth/me")).status_code
    assert admin_before == 200
    async with _client() as c:
        r = await c.post(f"{PR}/request", json={"phone": ADMIN_PHONE})
        assert r.status_code == 202 and not r.json().get("test_otp"), (
            "Admin OTP never in the response"
        )
        m = re.search(r"quản trị [^:]*: (\d{6})", caplog.text)
        assert m, "test mode logs the Admin code on the server"
        otp = m.group(1)
        token = (await c.post(f"{PR}/verify", json={"phone": ADMIN_PHONE, "otp": otp})).json()[
            "reset_token"
        ]
        new_pw = "Admin-New-Pass9"
        assert (
            await c.post(f"{PR}/confirm", json={"reset_token": token, "password": new_pw})
        ).status_code == 204
        try:
            assert (await sign_in(c, ADMIN_PHONE, new_pw)).status_code == 200, (
                "lock cleared by the reset"
            )
            r = await admin.get(f"{API}/admin/auth/me")
            assert r.status_code == 401 and err(r)["reason"] == "password_changed"
        finally:  # trả mật khẩu Admin về như cũ cho các test sau
            await x(
                "UPDATE users SET hashed_password=:h, token_version=token_version+1, failed_login_count=0, locked_until=NULL WHERE phone=:p",
                h=hash_password(ADMIN_PW),
                p=ADMIN_PHONE,
            )


# ================================================================ AC18 / SEC2 OTP và token không ở dạng rõ


async def test_sec2_otp_and_tokens_are_never_stored_or_logged_in_plain(anon, caplog):
    caplog.set_level("DEBUG")
    phone = await register(anon)
    async with _client() as c:
        otp = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        token = (await c.post(f"{PR}/verify", json={"phone": phone, "otp": otp})).json()[
            "reset_token"
        ]
        await c.post(f"{PR}/confirm", json={"reset_token": token, "password": "Next-Pass-3"})
    row = (await q("SELECT code_hash, token_hash FROM otp_codes WHERE phone=:p", p=phone))[0]
    assert row["code_hash"] == hmac_otp(otp) and otp not in row["code_hash"]
    assert row["token_hash"] == sha256(token)
    assert not await q(
        "SELECT 1 FROM audit_log WHERE detail::text LIKE :a OR detail::text LIKE :b",
        a=f"%{otp}%",
        b=f"%{token}%",
    )
    assert token not in caplog.text
    assert f": {otp}" not in caplog.text, "customer OTP is never logged"
    assert "Next-Pass-3" not in caplog.text


# ================================================================ AC29 chế độ thử, AC30 Zalo, SEC3


async def test_ac29_with_test_mode_off_no_otp_in_response_or_log_and_job_is_queued(
    anon, monkeypatch, caplog
):
    caplog.set_level("DEBUG")
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "qa-zalo")
    phone = await register(anon)
    ENQUEUED_JOBS.clear()
    async with _client() as c:
        r = await c.post(f"{PR}/request", json={"phone": phone})
        assert r.status_code == 202 and not r.json().get("test_otp")
        r2 = await c.post(f"{WEB}/phone/request", json={"phone": unique_phone()})
        assert r2.status_code == 202 and not r2.json().get("test_otp")
    jobs = [j for j in ENQUEUED_JOBS if j[0] == "send_zalo_otp"]
    assert len(jobs) >= 1, ENQUEUED_JOBS
    row = (await q("SELECT code_hash FROM otp_codes WHERE phone=:p", p=phone))[0]
    assert all(row["code_hash"] not in repr(j) for j in jobs)
    for job in jobs:
        assert not re.search(r"\b\d{6}\b", repr(job)), (
            f"OTP value must be masked in job repr: {job!r}"
        )
    assert not re.search(r"(?i)otp[^\n]*\b\d{6}\b", caplog.text), (
        "no OTP in logs when test mode is off"
    )


async def test_ac29_admin_code_never_reaches_the_response(anon):
    await clean_otps()
    r = await anon.post(f"{PR}/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 202
    assert not r.json().get("test_otp")
    assert "otp" not in {k for k, v in r.json().items() if v}


async def test_sec3_test_mode_refuses_to_start_in_production():
    base = {
        "_env_file": None,
        "SECRET_KEY": "x" * 48,
        "PAYMENTS_ENCRYPTION_KEY": "dGVzdC1rZXktZm9yLXBheW1lbnRzLWVuY3J5cHRpb24=",
        "FIRST_ADMIN_PASSWORD": "Str0ng-Prod-Password!",
        "FIRST_ADMIN_PHONE": "0912345678",
    }
    for env in ("production",):
        with pytest.raises(Exception) as exc:
            Settings(**base, ENV=env, OTP_TEST_MODE=True)
        assert "OTP_TEST_MODE" in str(exc.value), exc.value
    # dev/staging vẫn bật được
    assert Settings(**base, ENV="development", OTP_TEST_MODE=True).OTP_TEST_MODE is True


async def test_ac30_forgot_password_is_503_without_any_otp_channel(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "")
    r = await anon.post(f"{PR}/request", json={"phone": ADMIN_PHONE})
    assert r.status_code == 503 and err(r)["code"] == "E-AUTH-23"
    assert err(r)["message"] == "Chức năng quên mật khẩu đang tạm ngưng. Vui lòng liên hệ chủ sân."


# ================================================================ AC20 Google, SEC7


async def test_ac20_google_creates_a_customer_without_password_or_phone(gsetup, anon):
    sub = f"g-{uuid.uuid4().hex}"
    r = await google_login(anon, gtoken(sub, name="  Trần   Văn Gu  ", email="gu@gmail.com"))
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "member"
    acc = body["account"]
    assert acc["phone"] is None and acc["phone_verified"] is False and acc["role"] == "member"
    assert acc["google_email"] == "gu@gmail.com" and acc["full_name"] == "Trần Văn Gu"
    assert any(c.startswith("access_token=") for c in r.headers.get_list("set-cookie"))
    assert (await anon.get(f"{API}/auth/me")).status_code == 200
    row = (await q("SELECT hashed_password, phone FROM users WHERE google_sub=:s", s=sub))[0]
    assert row["hashed_password"] is None and row["phone"] is None
    # đăng nhập lần hai: cùng tài khoản
    r2 = await google_login(_client(), gtoken(sub))
    assert r2.json()["account"]["id"] == acc["id"]


async def test_ac20_google_never_links_by_email(gsetup, anon):
    phone = await register(anon)
    await x("UPDATE users SET google_email='victim@gmail.com' WHERE phone=:p", p=phone)
    me = (await anon.get(f"{API}/auth/me")).json()
    other = _client()
    r = await google_login(other, gtoken(f"g-{uuid.uuid4().hex}", email="victim@gmail.com"))
    assert r.status_code == 200 and r.json()["account"]["id"] != me["id"], (
        "same email, different account"
    )
    admin_email = (await q("SELECT email FROM users WHERE role='admin' ORDER BY id LIMIT 1"))[0][
        "email"
    ]
    r = await google_login(
        _client(), gtoken(f"g-{uuid.uuid4().hex}", email=admin_email or "a@b.vn")
    )
    assert r.json()["account"]["role"] == "member"


async def test_ac20_unverified_email_is_not_stored(gsetup, anon):
    r = await google_login(anon, gtoken(email="nv@gmail.com", email_verified=False))
    assert r.status_code == 200 and r.json()["account"]["google_email"] is None


@pytest.mark.parametrize(
    "variant",
    [
        "hs256",
        "none",
        "wrong_aud",
        "wrong_iss",
        "expired",
        "no_exp",
        "garbage",
        "other_key",
        "empty_sub",
    ],
)
async def test_sec7_bad_google_tokens_are_rejected(gsetup, anon, variant):
    now = int(time.time())
    if variant == "hs256":
        token = jwt.encode(
            {
                "iss": "accounts.google.com",
                "aud": CLIENT_ID,
                "sub": "s",
                "iat": now,
                "exp": now + 99,
            },
            "secret-secret-secret-secret-32b",
            algorithm="HS256",
        )
    elif variant == "none":
        token = jwt.encode(
            {
                "iss": "accounts.google.com",
                "aud": CLIENT_ID,
                "sub": "s",
                "iat": now,
                "exp": now + 99,
            },
            None,
            algorithm="none",
        )
    elif variant == "wrong_aud":
        token = gtoken(aud="someone-else")
    elif variant == "wrong_iss":
        token = gtoken(iss="https://evil.example")
    elif variant == "expired":
        token = gtoken(exp=now - 120, iat=now - 200)
    elif variant == "no_exp":
        token = gtoken(exp=...)
    elif variant == "garbage":
        token = "not.a.jwt"
    elif variant == "empty_sub":
        token = gtoken(
            sub="",
        )
    else:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(
            {
                "iss": "accounts.google.com",
                "aud": CLIENT_ID,
                "sub": "s",
                "iat": now,
                "exp": now + 99,
            },
            other,
            algorithm="RS256",
        )
    before = (await q("SELECT count(*) AS n FROM users"))[0]["n"]
    r = await google_login(anon, token)
    assert r.status_code == 401 and err(r)["code"] == "E-AUTH-20", (variant, r.text)
    assert (await q("SELECT count(*) AS n FROM users"))[0]["n"] == before, "no account is created"
    assert (await anon.get(f"{API}/auth/me")).status_code == 401


async def test_ac20_both_issuer_spellings_and_missing_client_id(gsetup, anon, monkeypatch):
    for iss in ("accounts.google.com", "https://accounts.google.com"):
        assert (await google_login(_client(), gtoken(iss=iss))).status_code == 200, iss
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = await google_login(anon, gtoken())
    assert r.status_code == 404 and err(r)["code"] == "E-AUTH-19"


async def test_ac20_jwks_unreachable_is_e_auth_21_and_does_not_count_as_a_failure(
    anon, monkeypatch
):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)

    def boom(_credential):
        raise jwt.PyJWKClientConnectionError("no network")

    monkeypatch.setattr(google, "_signing_key", boom)
    for _ in range(25):
        r = await google_login(anon, "a.b.c")
        assert r.status_code == 503 and err(r)["code"] == "E-AUTH-21"
    monkeypatch.setattr(google, "_signing_key", lambda c: _KEY.public_key())
    assert (await google_login(anon, gtoken())).status_code == 200, "no IP lockout from outages"


async def test_ac3_bad_google_tokens_count_towards_the_ip_limit(gsetup, anon):
    for _ in range(20):
        assert (await google_login(anon, "bad.token.value")).status_code == 401
    r = await google_login(anon, gtoken())
    assert r.status_code == 429 and err(r)["code"] == "E-AUTH-12"
    r = await sign_in(anon, ADMIN_PHONE, ADMIN_PW)
    assert r.status_code == 429, "the same IP budget covers password sign-in"


async def test_ac20_staff_or_admin_google_sub_is_refused(gsetup, anon, admin):
    sub = f"g-{uuid.uuid4().hex}"
    await x("UPDATE users SET google_sub=:s WHERE phone=:p", s=sub, p=ADMIN_PHONE)
    try:
        r = await google_login(anon, gtoken(sub))
        assert r.status_code == 401 and err(r)["code"] == "E-AUTH-20"
        assert (await anon.get(f"{API}/admin/auth/me")).status_code == 401, (
            "no Admin session via Google"
        )
    finally:
        await x("UPDATE users SET google_sub=NULL WHERE phone=:p", p=ADMIN_PHONE)


async def test_ac20_concurrent_first_google_logins_create_one_account(gsetup):
    sub = f"g-{uuid.uuid4().hex}"

    async def one():
        r = await google_login(_client(), gtoken(sub))
        return r.status_code

    assert await asyncio.gather(*[one() for _ in range(6)]) == [200] * 6
    assert len(await q("SELECT 1 FROM users WHERE google_sub=:s", s=sub)) == 1


async def test_ac20_google_account_cannot_sign_in_with_a_password(gsetup, anon):
    r = await google_login(anon, gtoken(f"g-{uuid.uuid4().hex}"))
    uid = r.json()["account"]["id"]
    await x("UPDATE users SET username=:u WHERE id=:i", u=f"gg{uid}", i=uid)
    for pw in ("", "x", "Password123", "None"):
        if pw:
            assert (await sign_in(_client(), f"gg{uid}", pw)).status_code == 401


# ================================================================ AC21–AC22 xác minh / gộp SĐT


async def test_ac22_verify_a_free_phone_attaches_it(gsetup):
    c = await google_customer()
    phone = unique_phone()
    r = await c.post(f"{API}/auth/phone/request", json={"phone": phone})
    assert r.status_code == 202 and re.fullmatch(r"\d{6}", r.json()["test_otp"])
    v = await c.post(f"{API}/auth/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert v.status_code == 200
    body = v.json()
    assert body["merged"] is False and body["password_cleared"] is False
    assert body["account"]["phone"] == phone and body["account"]["phone_verified"] is True
    me = (await c.get(f"{API}/auth/me")).json()
    assert me["phone"] == phone and me["phone_verified"] is True
    assert await q("SELECT 1 FROM audit_log WHERE action='auth.phone_verified'")
    again = await c.post(f"{API}/auth/phone/request", json={"phone": unique_phone()})
    assert again.status_code == 409 and err(again)["code"] == "E-AUTH-17"


async def test_ac22_requires_login_and_origin(gsetup, anon):
    for path, body in (
        ("/auth/phone/request", {"phone": unique_phone()}),
        ("/auth/phone/verify", {"phone": unique_phone(), "otp": "123456"}),
    ):
        assert (await anon.post(f"{API}{path}", json=body)).status_code == 401, path
    c = await google_customer()
    for path, body in (
        ("/auth/phone/request", {"phone": unique_phone()}),
        ("/auth/phone/verify", {"phone": unique_phone(), "otp": "123456"}),
    ):
        r = await c.post(f"{API}{path}", json=body, headers={"Origin": EVIL})
        assert r.status_code == 403 and err(r)["code"] == "E-SEC-1", path


async def test_ac22_merge_google_account_into_phone_owner(gsetup, anon):
    owner_phone = await register(anon, password="Owner-Pass-1")
    owner_id = (await q("SELECT id FROM users WHERE phone=:p", p=owner_phone))[0]["id"]
    owner_old_jwt = anon.cookies["access_token"]
    sub = f"g-{uuid.uuid4().hex}"
    c = await google_customer(sub, email="merge@gmail.com")
    g_id = (await c.get(f"{API}/auth/me")).json()["id"]
    otp = (await c.post(f"{API}/auth/phone/request", json={"phone": owner_phone})).json()[
        "test_otp"
    ]
    v = await c.post(f"{API}/auth/phone/verify", json={"phone": owner_phone, "otp": otp})
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["merged"] is True and body["password_cleared"] is True
    assert (
        body["account"]["id"] == owner_id and body["account"]["google_email"] == "merge@gmail.com"
    )
    assert (await c.get(f"{API}/auth/me")).json()["id"] == owner_id, (
        "JWT re-issued for the phone owner"
    )
    assert not await q("SELECT 1 FROM users WHERE id=:i", i=g_id), (
        "the Google-only account is deleted"
    )
    row = (
        await q(
            "SELECT google_sub, hashed_password, phone_verified_at FROM users WHERE id=:i",
            i=owner_id,
        )
    )[0]
    assert (
        row["google_sub"] == sub
        and row["hashed_password"] is None
        and row["phone_verified_at"] is not None
    )
    assert (await sign_in(_client(), owner_phone, "Owner-Pass-1")).status_code == 401, (
        "password was cleared"
    )
    stale = _client()
    stale.cookies.set("access_token", owner_old_jwt)
    assert (await stale.get(f"{API}/auth/me")).status_code == 401, (
        "old sessions of the owner are dead"
    )
    # đăng nhập Google lần sau vào đúng chủ SĐT
    assert (await google_login(_client(), gtoken(sub))).json()["account"]["id"] == owner_id
    audit = await q(
        "SELECT detail FROM audit_log WHERE action='auth.account_merged' AND entity_code=:i",
        i=str(owner_id),
    )
    assert len(audit) == 1 and audit[0]["detail"]["merged_from_user_id"] == g_id


async def test_ac22_merge_never_when_the_phone_owner_cannot_be_merged(gsetup, anon):
    await clean_otps()
    # chủ SĐT là Admin
    c = await google_customer()
    otp = (await c.post(f"{API}/auth/phone/request", json={"phone": ADMIN_PHONE})).json()[
        "test_otp"
    ]
    r = await c.post(f"{API}/auth/phone/verify", json={"phone": ADMIN_PHONE, "otp": otp})
    assert r.status_code == 409 and err(r)["code"] == "E-AUTH-18"
    assert (await sign_in(_client(), ADMIN_PHONE, ADMIN_PW)).status_code == 200, "Admin untouched"
    # chủ SĐT bị khóa
    p = await register(anon)
    await x("UPDATE users SET is_active=false WHERE phone=:p", p=p)
    c = await google_customer()
    otp = (await c.post(f"{API}/auth/phone/request", json={"phone": p})).json()["test_otp"]
    r = await c.post(f"{API}/auth/phone/verify", json={"phone": p, "otp": otp})
    assert r.status_code == 409 and err(r)["code"] == "E-AUTH-18"
    # chủ SĐT đã có Google khác
    p2 = await register(_client())
    await x("UPDATE users SET google_sub='someone-else' WHERE phone=:p", p=p2)
    c = await google_customer()
    otp = (await c.post(f"{API}/auth/phone/request", json={"phone": p2})).json()["test_otp"]
    r = await c.post(f"{API}/auth/phone/verify", json={"phone": p2, "otp": otp})
    assert r.status_code == 409 and err(r)["code"] == "E-AUTH-18"
    assert (await c.get(f"{API}/auth/me")).status_code == 200, (
        "failed merge keeps the Google account"
    )


async def test_ac22_code_is_bound_to_the_requesting_account(gsetup):
    phone = unique_phone()
    a, b = await google_customer(), await google_customer()
    otp = (await a.post(f"{API}/auth/phone/request", json={"phone": phone})).json()["test_otp"]
    r = await b.post(f"{API}/auth/phone/verify", json={"phone": phone, "otp": otp})
    assert r.status_code == 400 and err(r)["code"] == "E-AUTH-15", "B cannot redeem A's code"
    ok = await a.post(f"{API}/auth/phone/verify", json={"phone": phone, "otp": otp})
    assert ok.status_code == 200


async def test_ac22_same_otp_limits_as_ac16(gsetup):
    c = await google_customer()
    phone = unique_phone()
    assert (await c.post(f"{API}/auth/phone/request", json={"phone": phone})).status_code == 202
    r = await c.post(f"{API}/auth/phone/request", json={"phone": phone})
    assert r.status_code == 429 and err(r)["code"] == "E-AUTH-13"
    for _ in range(5):
        r = await c.post(f"{API}/auth/phone/verify", json={"phone": phone, "otp": "000000"})
        assert err(r)["code"] == "E-AUTH-14"
    r = await c.post(f"{API}/auth/phone/verify", json={"phone": phone, "otp": "000000"})
    # đã trừ lượt: sau 5 lần sai, mã đúng cũng không còn hiệu lực
    assert err(r)["code"] == "E-AUTH-15"


# ================================================================ AC24–AC28 đặt online cần phone_token


async def make_court(admin: AsyncClient) -> str:
    r = await admin.post(
        f"{API}/booking/resources",
        json={
            "name": f"QA m2 {uuid.uuid4().hex[:5]}",
            "resource_type_code": "thuong",
            "open_time": "00:00",
            "close_time": "24:00",
            "peak_bands": [],
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()["code"]


def body_for(code: str, phone: str, hour: int = 10, **extra) -> dict:
    return {
        "date": (vn_today() + timedelta(days=23)).isoformat(),
        "slots": [{"resource_code": code, "start_hour": hour}],
        "full_name": "QA Phone Token",
        "phone": phone,
        **extra,
    }


async def booking_token(client: AsyncClient, phone: str) -> dict:
    r = await client.post(f"{WEB}/phone/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    v = await client.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert v.status_code == 200, v.text
    return v.json()


async def test_ac25_request_and_verify_phone_token(anon):
    phone = unique_phone()
    r = await anon.post(f"{WEB}/phone/request", json={"phone": phone})
    assert (
        r.status_code == 202
        and r.json()["resend_after"] == 60
        and re.fullmatch(r"\d{6}", r.json()["test_otp"])
    )
    bad = await anon.post(
        f"{WEB}/phone/verify",
        json={"phone": phone, "otp": "000000" if r.json()["test_otp"] != "000000" else "111111"},
    )
    assert (
        bad.status_code == 400
        and err(bad)["code"] == "E-AUTH-14"
        and err(bad)["attempts_left"] == 4
    )
    v = await anon.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert v.status_code == 200
    tok = v.json()
    assert len(tok["phone_token"]) >= 43 and tok["expires_at"]
    exp = datetime.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
    now = datetime.now(exp.tzinfo)
    assert 29 * 60 <= (exp - now).total_seconds() <= 30 * 60 + 15
    row = (
        await q(
            "SELECT token_hash, purpose FROM otp_codes WHERE phone=:p ORDER BY id DESC LIMIT 1",
            p=phone,
        )
    )[0]
    assert row["token_hash"] == sha256(tok["phone_token"]) and row["purpose"] == "booking_phone"


async def test_ac25_validation_limits_and_origin(anon):
    for bad in ("", "123", "abc", "+1 202 555 0100"):
        r = await anon.post(f"{WEB}/phone/request", json={"phone": bad})
        assert r.status_code == 422, bad
    phone = unique_phone()
    assert (await anon.post(f"{WEB}/phone/request", json={"phone": phone})).status_code == 202
    r = await anon.post(f"{WEB}/phone/request", json={"phone": phone})
    assert r.status_code == 429 and err(r)["code"] == "E-AUTH-13"
    for path, body in (
        ("/phone/request", {"phone": unique_phone()}),
        ("/phone/verify", {"phone": phone, "otp": "123456"}),
    ):
        r = await anon.post(f"{WEB}{path}", json=body, headers={"Origin": EVIL})
        assert r.status_code == 403 and err(r)["code"] == "E-SEC-1", path
    r = await anon.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": "12345"})
    assert r.status_code == 422, "otp must be 6 digits"


async def test_ac26_checkout_requires_a_valid_phone_token(anon, admin):
    code = await make_court(admin)
    phone, other = unique_phone(), unique_phone()
    tok_a = (await booking_token(anon, phone))["phone_token"]
    tok_b = (await booking_token(anon, other))["phone_token"]
    # thiếu
    r = await anon.post(f"{WEB}/checkouts", json=body_for(code, phone), headers=idem())
    assert r.status_code == 403 and err(r)["code"] == "E-WEB-8", r.text
    assert err(r)["message"] == "Vui lòng xác minh số điện thoại trước khi thanh toán."
    # sai / đảo ngược (giới hạn 6 lần tạo / 10 phút / IP đếm cả lần bị từ chối)
    for bad in ("x" * 43, tok_a[::-1]):
        r = await anon.post(
            f"{WEB}/checkouts", json=body_for(code, phone, phone_token=bad), headers=idem()
        )
        assert r.status_code in (403, 422), bad
        if r.status_code == 403:
            assert err(r)["code"] == "E-WEB-8"
    # SEC8: token của SĐT khác
    r = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, phone_token=tok_b), headers=idem()
    )
    assert r.status_code == 403 and err(r)["code"] == "E-WEB-8"
    # đúng
    ok = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, phone_token=tok_a), headers=idem()
    )
    assert ok.status_code == 201, ok.text


async def test_ac26_token_matches_the_normalised_phone_and_is_reusable(anon, admin):
    code = await make_court(admin)
    phone = unique_phone()
    tok = (await booking_token(anon, phone))["phone_token"]
    spaced = f"+84 {phone[1:4]} {phone[4:7]} {phone[7:]}"
    first = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, spaced, 9, phone_token=tok), headers=idem()
    )
    assert first.status_code == 201, first.text
    # dùng lại token cho cùng SĐT: qua cửa phone_token (lỗi nếu có là E-WEB-4, không phải E-WEB-8)
    second = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, 11, phone_token=tok), headers=idem()
    )
    assert second.status_code != 403, second.text
    if second.status_code != 201:
        assert err(second)["code"] == "E-WEB-4"


async def test_ac26_expired_token_is_e_web_8(anon, admin):
    code = await make_court(admin)
    phone = unique_phone()
    tok = (await booking_token(anon, phone))["phone_token"]
    await x(
        "UPDATE otp_codes SET token_expires_at = now() - interval '1 second' WHERE phone=:p",
        p=phone,
    )
    r = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, phone_token=tok), headers=idem()
    )
    assert r.status_code == 403 and err(r)["code"] == "E-WEB-8"


async def test_ac26_reset_token_is_not_a_phone_token(anon, admin):
    code = await make_court(admin)
    phone = await register(anon)
    async with _client() as c:
        otp = (await c.post(f"{PR}/request", json={"phone": phone})).json()["test_otp"]
        reset = (await c.post(f"{PR}/verify", json={"phone": phone, "otp": otp})).json()[
            "reset_token"
        ]
    r = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, phone_token=reset), headers=idem()
    )
    assert r.status_code == 403 and err(r)["code"] == "E-WEB-8"


async def test_ac26_verified_logged_in_customer_skips_the_otp_step(admin):
    code = await make_court(admin)
    async with _client() as c:
        phone = unique_phone()
        await db_account(c, phone, "Khách Xác Minh")
        # chưa xác minh -> vẫn cần token
        r = await c.post(f"{WEB}/checkouts", json=body_for(code, phone), headers=idem())
        assert r.status_code == 403 and err(r)["code"] == "E-WEB-8"
        await x("UPDATE users SET phone_verified_at = now() WHERE phone=:p", p=phone)
        # đã xác minh + SĐT trùng body -> không cần token
        ok = await c.post(f"{WEB}/checkouts", json=body_for(code, phone), headers=idem())
        assert ok.status_code == 201, ok.text
        # đã xác minh nhưng body là SĐT khác -> vẫn cần token
        r = await c.post(
            f"{WEB}/checkouts", json=body_for(code, unique_phone(), 12), headers=idem()
        )
        assert r.status_code == 403 and err(r)["code"] == "E-WEB-8"


async def test_ac26_admin_session_is_not_a_verified_customer(admin):
    code = await make_court(admin)
    r = await admin.post(f"{WEB}/checkouts", json=body_for(code, ADMIN_PHONE), headers=idem())
    assert r.status_code == 403 and err(r)["code"] == "E-WEB-8", "Admin cookie must not bypass OTP"


async def test_ac26_phone_token_is_checked_before_slots_are_held(anon, admin):
    code = await make_court(admin)
    phone = unique_phone()
    r = await anon.post(f"{WEB}/checkouts", json=body_for(code, phone), headers=idem())
    assert r.status_code == 403
    tok = (await booking_token(anon, phone))["phone_token"]
    ok = await anon.post(
        f"{WEB}/checkouts", json=body_for(code, phone, phone_token=tok), headers=idem()
    )
    assert ok.status_code == 201, "the failed attempt left nothing behind"


async def test_ac27_online_is_off_without_an_otp_channel(anon, admin, monkeypatch):
    code = await make_court(admin)
    day = (vn_today() + timedelta(days=23)).isoformat()
    assert (await anon.get(f"{WEB}/calendar", params={"date": day})).json()[
        "online_enabled"
    ] is True
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "")
    assert (await anon.get(f"{WEB}/calendar", params={"date": day})).json()[
        "online_enabled"
    ] is False
    r = await anon.post(
        f"{WEB}/checkouts",
        json=body_for(code, unique_phone(), phone_token="x" * 43),
        headers=idem(),
    )
    assert r.status_code == 503 and err(r)["code"] == "E-WEB-5"
    r = await anon.post(f"{WEB}/phone/request", json={"phone": unique_phone()})
    assert r.status_code == 503 and err(r)["code"] == "E-WEB-5"
    # tra cứu không đổi (AC27)
    lk = await anon.post(f"{WEB}/lookup", json={"code": "BK-20200101-001", "phone": "0900000000"})
    assert lk.status_code in (404, 422) and err(lk)["code"] in ("E-WEB-7", "E-WEB-1")


async def test_ac27_zalo_configured_turns_online_back_on(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "qa-zalo")
    day = (vn_today() + timedelta(days=23)).isoformat()
    assert (await anon.get(f"{WEB}/calendar", params={"date": day})).json()[
        "online_enabled"
    ] is True
    monkeypatch.setattr(settings, "ZALO_TEMPLATE_OTP", "")  # thiếu 1 trong 4 biến
    assert (await anon.get(f"{WEB}/calendar", params={"date": day})).json()[
        "online_enabled"
    ] is False


async def test_ac28_counter_booking_needs_no_otp(admin, staff):
    code = await make_court(admin)
    # Khung đang diễn ra luôn đặt được; min(giờ, 22) lúc 23h thành khung 22h đã qua -> E-004.
    # Lấy ngày SAU safe_hour (23:59 nó chờ sang ngày mới)
    hour = await safe_hour()
    today = datetime.now(settings.tz)
    r = await staff.post(
        f"{API}/front-desk/bookings",
        json={
            "resource_code": code,
            "date": today.date().isoformat(),
            "start_hour": hour,
            "end_hour": hour + 1,
            "customer": {"temp": {"full_name": "QA Quầy", "phone": unique_phone()}},
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text


# ================================================================ AC31 lệnh cứu Admin


def scripted(*answers):
    it = iter(answers)
    return lambda _prompt: next(it)


def ask_admin_phone(_prompt):
    """The CLI asks for a phone only when several Admins exist (other tests may leave one)."""
    return ADMIN_PHONE


async def test_ac31_reset_admin_password_by_cli(admin, capsys, monkeypatch):
    uid = (await q("SELECT id, token_version FROM users WHERE phone=:p", p=ADMIN_PHONE))[0]
    assert (await admin.get(f"{API}/admin/auth/me")).status_code == 200
    new_pw = "Cli-New-Pass-77"
    try:
        await x(
            "UPDATE users SET failed_login_count=3, locked_until=now()+interval '10 minutes' WHERE phone=:p",
            p=ADMIN_PHONE,
        )
        await cli.run(ask=ask_admin_phone, secret=scripted(new_pw, new_pw))
        out = capsys.readouterr()
        assert new_pw not in out.out + out.err, "the password is never printed"
        assert "xxx" in out.out.lower(), "the phone is masked in the confirmation line"
        assert ADMIN_PHONE not in out.out, "the full phone is not printed"
        r = await admin.get(f"{API}/admin/auth/me")
        assert r.status_code == 401 and err(r)["reason"] == "password_changed"
        row = (
            await q(
                "SELECT token_version, locked_until, failed_login_count FROM users WHERE phone=:p",
                p=ADMIN_PHONE,
            )
        )[0]
        assert row["token_version"] == uid["token_version"] + 1
        assert row["locked_until"] is None and row["failed_login_count"] == 0
        assert (await sign_in(_client(), ADMIN_PHONE, ADMIN_PW)).status_code == 401
        assert (await sign_in(_client(), ADMIN_PHONE, new_pw)).status_code == 200
        a = (
            await q(
                "SELECT actor_type, actor_label, detail::text AS d FROM audit_log WHERE action='auth.password_reset_cli' ORDER BY id DESC LIMIT 1"
            )
        )[0]
        assert a["actor_type"] == "system" and new_pw not in a["d"]
    finally:
        await x(
            "UPDATE users SET hashed_password=:h, token_version=token_version+1,"
            " failed_login_count=0, locked_until=NULL WHERE phone=:p",
            h=hash_password(ADMIN_PW),
            p=ADMIN_PHONE,
        )


@pytest.mark.parametrize(
    ("answers", "needle"),
    [
        (("weak", "weak"), "Mật khẩu cần"),
        (("Valid-Pass-1", "Different-Pass-2"), "không khớp"),
    ],
)
async def test_ac31_cli_rejects_weak_or_mismatched_passwords(admin, answers, needle):
    before = (
        await q("SELECT hashed_password, token_version FROM users WHERE phone=:p", p=ADMIN_PHONE)
    )[0]
    with pytest.raises(cli.ResetError, match=needle):
        await cli.run(ask=ask_admin_phone, secret=scripted(*answers))
    after = (
        await q("SELECT hashed_password, token_version FROM users WHERE phone=:p", p=ADMIN_PHONE)
    )[0]
    assert before == after
    assert (await admin.get(f"{API}/admin/auth/me")).status_code == 200


async def test_ac31_with_several_admins_it_asks_for_the_phone(admin):
    second_phone = "0900000071"
    await x("DELETE FROM users WHERE phone=:p", p=second_phone)
    await x(
        "INSERT INTO users (phone, username, full_name, hashed_password, role, is_active) VALUES (:p, 'qa.admin2', 'Admin Hai', :h, 'admin', true)",
        p=second_phone,
        h=hash_password("Second-Admin-1"),
    )
    try:
        with pytest.raises(cli.ResetError, match="Không có Admin nào"):
            await cli.run(
                ask=scripted("0911111111"), secret=scripted("Valid-Pass-1", "Valid-Pass-1")
            )
        await cli.run(
            ask=scripted("0900 000 071"), secret=scripted("Second-Reset-9", "Second-Reset-9")
        )
        assert (await sign_in(_client(), second_phone, "Second-Reset-9")).status_code == 200
        assert (await sign_in(_client(), ADMIN_PHONE, ADMIN_PW)).status_code == 200, (
            "the other Admin is untouched"
        )
    finally:
        await x("DELETE FROM users WHERE phone=:p", p=second_phone)


def test_ac31_command_takes_no_password_from_argv(monkeypatch):
    import inspect

    src = inspect.getsource(cli)
    assert "getpass" in src and "sys.argv" not in src and "argparse" not in src


async def test_ac26_empty_or_oversized_phone_token_is_rejected(anon, admin):
    code = await make_court(admin)
    for bad in ("", "A" * 500):
        r = await anon.post(
            f"{WEB}/checkouts", json=body_for(code, unique_phone(), phone_token=bad), headers=idem()
        )
        assert r.status_code in (403, 422), bad
        if r.status_code == 403:
            assert err(r)["code"] == "E-WEB-8"


async def test_ac15_disabled_account_is_indistinguishable_from_unknown(anon):
    phone = await register(anon)
    await x("UPDATE users SET is_active=false WHERE phone=:p", p=phone)
    ghost = unique_phone()
    outs = []
    for p in (phone, ghost):
        async with _client() as c:
            r = await c.post(f"{PR}/request", json={"phone": p})
            assert r.status_code == 202 and not r.json().get("test_otp"), p
            v = await c.post(f"{PR}/verify", json={"phone": p, "otp": "123456"})
            outs.append(
                (
                    r.json()["resend_after"],
                    v.status_code,
                    err(v)["code"],
                    err(v).get("attempts_left"),
                )
            )
    assert outs[0] == outs[1]


async def test_ac26_verified_customer_skips_otp_even_when_phone_is_typed_differently(admin):
    code = await make_court(admin)
    async with _client() as c:
        phone = unique_phone()
        await db_account(c, phone, "Khách Gõ Khác")
        await x("UPDATE users SET phone_verified_at = now() WHERE phone=:p", p=phone)
        spaced = f"+84 {phone[1:4]} {phone[4:7]} {phone[7:]}"
        ok = await c.post(f"{WEB}/checkouts", json=body_for(code, spaced), headers=idem())
        assert ok.status_code == 201, ok.text

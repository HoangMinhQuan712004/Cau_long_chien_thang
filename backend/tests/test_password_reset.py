"""T-013 mốc 2: quên mật khẩu bằng OTP (AC14–AC18, AC29, AC30)."""

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import OtpCode, OtpPurpose, User
from tests.conftest import (
    API,
    CUSTOMER_PASSWORD,
    ENQUEUED_JOBS,
    _client,
    extra_admin,
    new_customer,
    sign_in,
    unique_phone,
)

RESET = f"{API}/auth/password-reset"
NEW_PASSWORD = "MatKhauMoi9"


async def request_code(client, phone: str, headers: dict | None = None):
    return await client.post(f"{RESET}/request", json={"phone": phone}, headers=headers or {})


async def verify_code(client, phone: str, otp: str):
    return await client.post(f"{RESET}/verify", json={"phone": phone, "otp": otp})


def wrong(otp: str) -> str:
    return f"{(int(otp) + 1) % 10**6:06d}"


async def reset_token_for(client, phone: str) -> str:
    r = await request_code(client, phone)
    assert r.status_code == 202, r.text
    r = await verify_code(client, phone, r.json()["test_otp"])
    assert r.status_code == 200, r.text
    return r.json()["reset_token"]


# ------------------------------------------------------------------ luồng đúng


async def test_customer_resets_password_and_old_tokens_die():
    phone = unique_phone()
    async with new_customer(phone) as c:
        r = await request_code(c, phone)
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["resend_after"] == settings.OTP_RESEND_SECONDS
        assert re.fullmatch(r"\d{6}", body["test_otp"])

        r = await verify_code(c, phone, body["test_otp"])
        assert r.status_code == 200, r.text
        token = r.json()["reset_token"]

        r = await c.post(f"{RESET}/confirm", json={"reset_token": token, "password": NEW_PASSWORD})
        assert r.status_code == 204, r.text

        # JWT cũ (token_version cũ) hết hiệu lực
        r = await c.get(f"{API}/auth/me")
        assert r.status_code == 401

    async with _client() as c2:
        assert (await sign_in(c2, phone, CUSTOMER_PASSWORD)).status_code == 401
        r = await sign_in(c2, phone, NEW_PASSWORD)
        assert r.status_code == 200, r.text
        # Nhận mã ở SĐT này -> SĐT đã xác minh
        assert r.json()["account"]["phone_verified"] is True

    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.phone == phone))
        actions = set(
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_code == str(user.id)))
        )
    assert {"auth.password_reset_requested", "auth.password_reset_done"} <= actions


async def test_reset_token_is_single_use_and_checked(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    token = await reset_token_for(anon, phone)
    body = {"reset_token": token, "password": NEW_PASSWORD}
    assert (await anon.post(f"{RESET}/confirm", json=body)).status_code == 204

    r = await anon.post(f"{RESET}/confirm", json=body)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-16"
    r = await anon.post(f"{RESET}/confirm", json={**body, "reset_token": "x" * 40})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-16"


async def test_reset_token_expires(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    token = await reset_token_for(anon, phone)
    async with SessionLocal() as s:
        await s.execute(
            update(OtpCode)
            .where(OtpCode.phone == phone)
            .values(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    r = await anon.post(f"{RESET}/confirm", json={"reset_token": token, "password": NEW_PASSWORD})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-16"


async def test_confirm_rejects_weak_password(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    token = await reset_token_for(anon, phone)
    r = await anon.post(f"{RESET}/confirm", json={"reset_token": token, "password": "yeu"})
    assert r.status_code == 422
    # Token chưa bị dùng -> đặt lại với mật khẩu hợp lệ vẫn được
    r = await anon.post(f"{RESET}/confirm", json={"reset_token": token, "password": NEW_PASSWORD})
    assert r.status_code == 204


async def test_admin_otp_only_in_server_log_and_sessions_revoked(caplog):
    async with extra_admin("Admin@12345") as (_, phone), _client() as admin2:
        assert (await sign_in(admin2, phone, "Admin@12345")).status_code == 200
        async with _client() as c:
            with caplog.at_level(logging.WARNING, logger="app.modules.auth.otp"):
                r = await request_code(c, phone)
            assert r.status_code == 202, r.text
            # AC29: mã của Admin / NV không bao giờ nằm trong response
            assert r.json().get("test_otp") is None
            logged = [m for m in caplog.messages if "OTP (chế độ thử)" in m]
            assert len(logged) == 1 and phone not in logged[0]  # SĐT đã che
            otp = re.search(r"(\d{6})$", logged[0]).group(1)

            r = await verify_code(c, phone, otp)
            assert r.status_code == 200, r.text
            r = await c.post(
                f"{RESET}/confirm",
                json={"reset_token": r.json()["reset_token"], "password": NEW_PASSWORD},
            )
            assert r.status_code == 204

        r = await admin2.get(f"{API}/admin/auth/me")
        assert r.status_code == 401 and r.json()["detail"]["reason"] == "password_changed"
        async with _client() as c:
            assert (await sign_in(c, phone, NEW_PASSWORD)).status_code == 200


async def test_reset_clears_login_lock(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.phone == phone)
            .values(failed_login_count=5, locked_until=datetime.now(UTC) + timedelta(minutes=15))
        )
        await s.commit()
    assert (await sign_in(anon, phone, CUSTOMER_PASSWORD)).status_code == 423
    token = await reset_token_for(anon, phone)
    r = await anon.post(f"{RESET}/confirm", json={"reset_token": token, "password": NEW_PASSWORD})
    assert r.status_code == 204
    assert (await sign_in(anon, phone, NEW_PASSWORD)).status_code == 200


# ------------------------------------------------------------------ chống dò, sai mã


async def test_unknown_phone_looks_the_same(anon):
    phone = unique_phone()  # không có tài khoản
    r = await request_code(anon, phone)
    assert r.status_code == 202
    assert r.json() == {"resend_after": settings.OTP_RESEND_SECONDS, "test_otp": None}
    # Mã nào cũng sai, đếm lượt như mã thật
    for left in range(settings.OTP_MAX_ATTEMPTS - 1, -1, -1):
        r = await verify_code(anon, phone, "123456")
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "E-AUTH-14"
        assert r.json()["detail"]["attempts_left"] == left
    r = await verify_code(anon, phone, "123456")
    assert r.json()["detail"]["code"] == "E-AUTH-15"
    # Lại gửi quá sớm -> 429 như SĐT có tài khoản
    r = await request_code(anon, phone)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-AUTH-13"


async def test_wrong_code_attempts_then_dead(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    otp = (await request_code(anon, phone)).json()["test_otp"]
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        r = await verify_code(anon, phone, wrong(otp))
        assert r.json()["detail"]["code"] == "E-AUTH-14"
    # Hết lượt: mã đúng cũng không còn dùng được
    r = await verify_code(anon, phone, otp)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-15"


async def test_no_code_or_expired_code(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    r = await verify_code(anon, phone, "000000")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-15"

    otp = (await request_code(anon, phone)).json()["test_otp"]
    async with SessionLocal() as s:
        await s.execute(
            update(OtpCode)
            .where(OtpCode.phone == phone)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    r = await verify_code(anon, phone, otp)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-15"


async def test_new_code_replaces_old(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
    phone = unique_phone()
    async with new_customer(phone):
        pass
    first = (await request_code(anon, phone)).json()["test_otp"]
    second = (await request_code(anon, phone)).json()["test_otp"]
    if first != second:  # trùng nhau xác suất 10^-6 -> không có gì để kiểm
        r = await verify_code(anon, phone, first)
        assert r.json()["detail"]["code"] == "E-AUTH-14"
    r = await verify_code(anon, phone, second)
    assert r.status_code == 200


async def test_invalid_input_422(anon):
    assert (await request_code(anon, "12345")).status_code == 422
    r = await anon.post(f"{RESET}/verify", json={"phone": unique_phone(), "otp": "12ab56"})
    assert r.status_code == 422


# ------------------------------------------------------------------ giới hạn gửi mã


async def test_resend_too_soon(anon):
    phone = unique_phone()
    async with new_customer(phone):
        pass
    assert (await request_code(anon, phone)).status_code == 202
    r = await request_code(anon, phone)
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "E-AUTH-13"
    assert 0 < detail["retry_after"] <= settings.OTP_RESEND_SECONDS
    assert r.headers["Retry-After"] == str(detail["retry_after"])


async def test_max_codes_per_hour_per_phone(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
    monkeypatch.setattr(settings, "OTP_MAX_PER_HOUR", 2)
    phone = unique_phone()
    assert (await request_code(anon, phone)).status_code == 202
    assert (await request_code(anon, phone)).status_code == 202
    r = await request_code(anon, phone)
    assert r.status_code == 429
    assert r.json()["detail"]["retry_after"] > 3000  # chờ tới khi mã cũ nhất quá 1 giờ


async def test_max_codes_per_hour_per_ip(anon, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    monkeypatch.setattr(settings, "OTP_IP_MAX_PER_HOUR", 2)
    ip = {"X-Forwarded-For": f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.7"}
    assert (await request_code(anon, unique_phone(), ip)).status_code == 202
    assert (await request_code(anon, unique_phone(), ip)).status_code == 202
    r = await request_code(anon, unique_phone(), ip)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-AUTH-13"
    # IP khác vẫn gửi được
    other = {"X-Forwarded-For": "192.0.2.55"}
    assert (await request_code(anon, unique_phone(), other)).status_code == 202


# ------------------------------------------------------------------ kênh gửi


async def test_no_otp_channel_is_503(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    r = await request_code(anon, unique_phone())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-AUTH-23"


async def test_zalo_job_gets_masked_otp(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "x")
    phone = unique_phone()
    async with new_customer(phone):
        pass
    ENQUEUED_JOBS.clear()
    r = await request_code(anon, phone)
    assert r.status_code == 202 and r.json()["test_otp"] is None
    [(job, args)] = ENQUEUED_JOBS
    assert job == "send_zalo_otp"
    code_id, otp = args
    assert re.fullmatch(r"\d{6}", otp) and "******" in repr(otp)
    async with SessionLocal() as s:
        row = await s.get(OtpCode, code_id)
        assert row.phone == phone and row.purpose == OtpPurpose.PASSWORD_RESET
        assert row.code_hash != otp  # DB chỉ giữ HMAC
    # SĐT không có tài khoản: không gửi gì
    ENQUEUED_JOBS.clear()
    assert (await request_code(anon, unique_phone())).status_code == 202
    assert ENQUEUED_JOBS == []


async def test_request_requires_origin():
    async with _client() as c:
        c.headers.pop("Origin")
        r = await request_code(c, unique_phone())
        assert r.status_code == 403

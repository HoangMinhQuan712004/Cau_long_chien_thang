"""T-013: xác minh SĐT trước khi đặt online – ``phone_token`` (AC24–AC27, AC40, SEC8)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import google
from app.modules.auth.models import OtpCode, OtpPurpose, User
from tests.conftest import API, new_customer
from tests.helpers_booking import new_court, random_phone
from tests.helpers_web import WEB, checkout, phone_token, web_calendar
from tests.test_customer_accounts import _KEY, CLIENT_ID, google_customer


async def request_code(client, phone: str):
    return await client.post(f"{WEB}/phone/request", json={"phone": phone})


async def fresh_token(client, phone: str) -> str:
    r = await request_code(client, phone)
    assert r.status_code == 202, r.text
    r = await client.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert r.status_code == 200, r.text
    return r.json()["phone_token"]


def is_web8(r) -> bool:
    return r.status_code == 403 and r.json()["detail"]["code"] == "E-WEB-8"


async def test_phone_token_flow(anon, admin):
    court = await new_court(admin)
    phone = random_phone()
    r = await request_code(anon, phone)
    assert r.status_code == 202
    body = r.json()
    assert body["resend_after"] == settings.OTP_RESEND_SECONDS and len(body["test_otp"]) == 6

    r = await anon.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": body["test_otp"]})
    assert r.status_code == 200, r.text
    token = r.json()["phone_token"]
    expires_at = datetime.fromisoformat(r.json()["expires_at"])
    left = expires_at - datetime.now(UTC)
    assert timedelta(minutes=29) < left <= timedelta(minutes=30)
    assert r.headers["Cache-Control"] == "no-store"

    # SĐT nhập kiểu khác vẫn là cùng SĐT đã chuẩn hóa
    spaced = f"{phone[:4]} {phone[4:7]} {phone[7:]}"
    r = await checkout(anon, [(court["code"], 9)], phone=spaced, phone_token=token)
    assert r.status_code == 201, r.text
    # Token dùng lại được trong hạn: lần 2 qua bước SĐT, vướng quy tắc "đang có lượt chờ"
    r = await checkout(anon, [(court["code"], 10)], phone=phone, phone_token=token)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-WEB-4"


async def test_checkout_without_valid_token_is_403(anon, admin):
    court = await new_court(admin)
    phone = random_phone()
    slot = [(court["code"], 9)]
    assert is_web8(await checkout(anon, slot, phone=phone, phone_token=None))
    assert is_web8(await checkout(anon, slot, phone=phone, phone_token="x" * 43))
    # Token của SĐT A không dùng cho SĐT B
    token_a = await phone_token(anon, random_phone())
    assert is_web8(await checkout(anon, slot, phone=phone, phone_token=token_a))
    # Hết hạn
    token = await fresh_token(anon, phone)
    async with SessionLocal() as s:
        await s.execute(
            update(OtpCode)
            .where(OtpCode.phone == phone, OtpCode.purpose == OtpPurpose.BOOKING_PHONE)
            .values(token_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await s.commit()
    assert is_web8(await checkout(anon, slot, phone=phone, phone_token=token))


async def test_reset_token_is_not_a_phone_token(anon, admin):
    court = await new_court(admin)
    phone = random_phone()
    async with new_customer(phone):
        pass
    r = await anon.post(f"{settings.API_PREFIX}/auth/password-reset/request", json={"phone": phone})
    r = await anon.post(
        f"{settings.API_PREFIX}/auth/password-reset/verify",
        json={"phone": phone, "otp": r.json()["test_otp"]},
    )
    reset_token = r.json()["reset_token"]
    r = await checkout(anon, [(court["code"], 9)], phone=phone, phone_token=reset_token)
    assert is_web8(r)


async def test_signed_in_customer_with_verified_phone_skips_otp(admin):
    court = await new_court(admin)
    phone = random_phone()
    async with new_customer(phone) as c:
        # Đăng ký chưa xác minh SĐT -> vẫn cần phone_token
        assert is_web8(await checkout(c, [(court["code"], 9)], phone=phone, phone_token=None))
        async with SessionLocal() as s:
            await s.execute(
                update(User).where(User.phone == phone).values(phone_verified_at=datetime.now(UTC))
            )
            await s.commit()
        # SĐT khác SĐT đã xác minh -> cần phone_token
        other = random_phone()
        assert is_web8(await checkout(c, [(court["code"], 9)], phone=other, phone_token=None))
        r = await checkout(c, [(court["code"], 9)], phone=phone, phone_token=None)
        assert r.status_code == 201, r.text


async def test_admin_session_is_not_a_verified_customer(admin):
    court = await new_court(admin)
    r = await checkout(
        admin, [(court["code"], 9)], phone=settings.FIRST_ADMIN_PHONE, phone_token=None
    )
    assert is_web8(r)


async def test_phone_code_errors(anon):
    r = await request_code(anon, "0912")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-WEB-1"
    r = await anon.post(f"{WEB}/phone/verify", json={"phone": random_phone(), "otp": "12345"})
    assert r.status_code == 422
    phone = random_phone()
    otp = (await request_code(anon, phone)).json()["test_otp"]
    bad = f"{(int(otp) + 1) % 10**6:06d}"
    r = await anon.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": bad})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-14"
    r = await request_code(anon, phone)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-AUTH-13"


async def test_phone_request_needs_origin(anon):
    anon.headers.pop("Origin")
    r = await request_code(anon, random_phone())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"


async def test_no_otp_channel_disables_online(anon, admin, monkeypatch):
    court = await new_court(admin)
    token = await fresh_token(anon, random_phone())
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    assert (await web_calendar(anon)).json()["online_enabled"] is False
    r = await request_code(anon, random_phone())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-WEB-5"
    r = await checkout(anon, [(court["code"], 9)], phone_token=token)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-WEB-5"
    # Zalo đủ 4 biến -> bật lại
    for name in ("ZALO_APP_ID", "ZALO_SECRET_KEY", "ZALO_REFRESH_TOKEN", "ZALO_TEMPLATE_OTP"):
        monkeypatch.setattr(settings, name, "x")
    assert (await web_calendar(anon)).json()["online_enabled"] is True


# ------------------------------------------------------------------ AC40: xác minh tài khoản


async def verify_booking_phone(client, phone: str):
    r = await request_code(client, phone)
    assert r.status_code == 202, r.text
    r = await client.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert r.status_code == 200, r.text
    return r.json()


async def account(phone: str | None = None, user_id: int | None = None) -> User:
    async with SessionLocal() as s:
        q = (
            select(User).where(User.phone == phone)
            if phone
            else select(User).where(User.id == user_id)
        )
        return await s.scalar(q)


async def phone_verified_audits(user_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).where(
                AuditLog.action == "auth.phone_verified", AuditLog.entity_code == str(user_id)
            )
        )


async def test_signed_in_customer_verifies_own_phone_while_booking(admin, monkeypatch):
    court = await new_court(admin)
    phone = random_phone()
    async with new_customer(phone) as c:
        user = await account(phone)
        assert user.phone_verified_at is None
        # Nhập SĐT kiểu khác vẫn trùng sau chuẩn hóa
        body = await verify_booking_phone(c, f"+84 {phone[1:]}")
        assert body["account_verified"] is True
        user = await account(phone)
        assert user.phone_verified_at is not None
        assert await phone_verified_audits(user.id) == 1
        assert (await c.get(f"{API}/auth/me")).json()["phone_verified"] is True
        # Lần đặt sau không cần phone_token
        r = await checkout(c, [(court["code"], 9)], phone=phone, phone_token=None)
        assert r.status_code == 201, r.text

        # Đã xác minh từ trước -> vẫn true, không ghi nhật ký lần nữa
        monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)
        body = await verify_booking_phone(c, phone)
        assert body["account_verified"] is True
        assert await phone_verified_audits(user.id) == 1


async def test_other_phone_or_anonymous_does_not_verify_account(anon):
    phone = random_phone()
    async with new_customer(phone) as c:
        body = await verify_booking_phone(c, random_phone())
        assert body["account_verified"] is False
        # Không đăng nhập xác minh đúng SĐT của tài khoản -> tài khoản không đổi
        body = await verify_booking_phone(anon, phone)
        assert body["account_verified"] is False
        user = await account(phone)
        assert user.phone_verified_at is None
        assert await phone_verified_audits(user.id) == 0
        assert (await c.get(f"{API}/auth/me")).json()["phone_verified"] is False


async def test_account_without_phone_gets_phone_attached(monkeypatch):
    """T-021 AC5 (thay T-013 AC40): tài khoản Google chưa có SĐT -> gắn SĐT vừa xác minh."""
    sub = str(uuid.uuid4().int)[:21]
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(google, "_signing_key", lambda _credential: _KEY.public_key())
    async with google_customer(sub) as c:
        user_id = (await c.get(f"{API}/auth/me")).json()["id"]
        phone = random_phone()
        body = await verify_booking_phone(c, phone)
        assert body["account_verified"] is True and body["became_member"] is True
        user = await account(user_id=user_id)
        assert user.phone == phone and user.phone_verified_at is not None


async def test_admin_session_does_not_verify(admin):
    body = await verify_booking_phone(admin, random_phone())
    assert body["account_verified"] is False

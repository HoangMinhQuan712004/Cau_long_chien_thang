"""QA T-013 AC40: tài khoản khách đã xác minh SĐT thì không cần OTP khi đặt sân.

Viết từ spec (AC19, AC26, AC40), không phụ thuộc test của BACKEND. Mỗi test dùng SĐT riêng.
"""

import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.conftest import API, _client, new_customer, unique_phone
from tests.helpers_booking import new_court
from tests.helpers_web import WEB, checkout

pytestmark = pytest.mark.anyio


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


@pytest.fixture(autouse=True)
async def fresh_otp_limits(monkeypatch):
    """Giới hạn gửi mã đếm trên ``otp_codes``; mỗi test bắt đầu từ 0 và gửi lại được ngay."""
    await x("DELETE FROM otp_codes")
    monkeypatch.setattr(settings, "OTP_RESEND_SECONDS", 0)


async def booking_verify(client, phone: str) -> dict:
    """Gửi mã + nhập đúng mã ở bước đặt sân; trả body của ``phone/verify``."""
    r = await client.post(f"{WEB}/phone/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    r = await client.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})
    assert r.status_code == 200, r.text
    return r.json()


async def user_row(phone: str):
    rows = await q(
        "SELECT id, phone, phone_verified_at, token_version FROM users WHERE phone=:p", p=phone
    )
    return rows[0] if rows else None


async def audits(user_id: int) -> list:
    return await q(
        "SELECT actor_type, actor_label, detail::text AS d FROM audit_log"
        " WHERE action='auth.phone_verified' AND entity_code=:u ORDER BY id",
        u=str(user_id),
    )


def is_web8(r) -> bool:
    return r.status_code == 403 and r.json()["detail"]["code"] == "E-WEB-8"


# ---------------------------------------- AC19: đăng ký không xác minh; lần đặt đầu vẫn OTP


async def test_ac40_new_account_first_booking_still_needs_otp(admin):
    court = await new_court(admin)
    phone = unique_phone()
    async with new_customer(phone) as c:
        assert (await user_row(phone))["phone_verified_at"] is None
        r = await checkout(c, [(court["code"], 10)], phone=phone, phone_token=None)
        assert is_web8(r), r.text


# ---------------------------------------- AC40: xác minh đúng SĐT tài khoản -> bỏ OTP lần sau


async def test_ac40_matching_phone_marks_account_and_skips_otp_next_time(admin):
    court = await new_court(admin)
    phone = unique_phone()
    async with new_customer(phone) as c:
        body = await booking_verify(c, phone)
        assert body["account_verified"] is True and body["phone_token"]
        row = await user_row(phone)
        assert row["phone_verified_at"] is not None
        assert (await c.get(f"{API}/auth/me")).json()["phone_verified"] is True
        # lần đặt sau: không cần phone_token
        r = await checkout(c, [(court["code"], 11)], phone=phone, phone_token=None)
        assert r.status_code == 201, r.text


@pytest.mark.parametrize("style", ["plus84", "plus84_spaces", "dots", "padded"])
async def test_ac40_phone_formats_normalize_to_the_account_phone(style):
    phone = unique_phone()
    typed = {
        "plus84": "+84" + phone[1:],
        "plus84_spaces": f"+84 {phone[1:4]} {phone[4:7]} {phone[7:]}",
        "dots": f"{phone[:4]}.{phone[4:7]}.{phone[7:]}",
        "padded": f"  {phone}  ",
    }[style]
    async with new_customer(phone) as c:
        assert (await booking_verify(c, typed))["account_verified"] is True
        assert (await user_row(phone))["phone_verified_at"] is not None


async def test_ac40_audit_entry_has_no_secret_and_names_the_customer():
    phone = unique_phone()
    async with new_customer(phone) as c:
        await booking_verify(c, phone)
        row = await user_row(phone)
        rows = await audits(row["id"])
        assert len(rows) == 1
        assert "web_booking" in rows[0]["d"]
        assert phone not in rows[0]["d"] and phone[1:] not in rows[0]["d"], "no full phone in audit"
        assert rows[0]["actor_type"] == "customer" and rows[0]["actor_label"], "names the customer"


async def test_ac40_already_verified_stays_true_without_a_second_audit_or_new_timestamp():
    phone = unique_phone()
    async with new_customer(phone) as c:
        await booking_verify(c, phone)
        first = await user_row(phone)
        again = await booking_verify(c, phone)
        assert again["account_verified"] is True
        second = await user_row(phone)
        assert second["phone_verified_at"] == first["phone_verified_at"], "timestamp not moved"
        assert len(await audits(first["id"])) == 1


# ---------------------------------------- AC40: sửa sang SĐT khác -> phải OTP


async def test_ac40_verified_account_other_phone_needs_otp(admin):
    court = await new_court(admin)
    phone = unique_phone()
    async with new_customer(phone) as c:
        await booking_verify(c, phone)
        other = unique_phone()
        r = await checkout(c, [(court["code"], 12)], phone=other, phone_token=None)
        assert is_web8(r), "a different phone in the form must be verified again"
        body = await booking_verify(c, other)
        assert body["account_verified"] is False
        assert (await user_row(phone))["phone_verified_at"] is not None, "account untouched"
        assert await user_row(other) is None, "the other phone is not attached to the account"


async def test_ac40_verified_phone_without_login_still_needs_otp(admin):
    court = await new_court(admin)
    phone = unique_phone()
    async with new_customer(phone) as c:
        await booking_verify(c, phone)
    async with _client() as guest:
        r = await checkout(guest, [(court["code"], 13)], phone=phone, phone_token=None)
        assert is_web8(r), "a verified account does not make its phone free for guests"


async def test_ac40_another_customer_cannot_borrow_a_verified_phone(admin):
    court = await new_court(admin)
    phone = unique_phone()
    async with new_customer(phone) as owner:
        await booking_verify(owner, phone)
    async with new_customer() as intruder:
        r = await checkout(intruder, [(court["code"], 14)], phone=phone, phone_token=None)
        assert is_web8(r)


# ---------------------------------------- AC40: các trường hợp không được đặt xác minh


async def test_ac40_wrong_code_does_not_verify_the_account():
    phone = unique_phone()
    async with new_customer(phone) as c:
        r = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        assert r.status_code == 202
        bad = "000000" if r.json()["test_otp"] != "000000" else "111111"
        r = await c.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": bad})
        assert r.status_code == 400
        row = await user_row(phone)
        assert row["phone_verified_at"] is None
        assert await audits(row["id"]) == []


async def test_ac40_guest_verifying_an_accounts_phone_does_not_verify_it(anon):
    phone = unique_phone()
    async with new_customer(phone) as c:
        body = await booking_verify(anon, phone)
        assert body["account_verified"] is False
        row = await user_row(phone)
        assert row["phone_verified_at"] is None and await audits(row["id"]) == []
        assert (await c.get(f"{API}/auth/me")).json()["phone_verified"] is False


async def test_ac40_other_customers_cookie_does_not_verify_someone_elses_account():
    victim_phone = unique_phone()
    async with new_customer(victim_phone):
        async with new_customer() as other:
            body = await booking_verify(other, victim_phone)
            assert body["account_verified"] is False
        row = await user_row(victim_phone)
        assert row["phone_verified_at"] is None and await audits(row["id"]) == []


async def test_ac40_staff_cookie_does_not_verify(staff):
    assert (await booking_verify(staff, unique_phone()))["account_verified"] is False


async def test_ac40_stale_session_after_password_change_does_not_verify():
    phone = unique_phone()
    async with new_customer(phone) as c:
        await x("UPDATE users SET token_version=token_version+1 WHERE phone=:p", p=phone)
        body = await booking_verify(c, phone)
        assert body["account_verified"] is False, "a revoked session is not a signed-in customer"
        assert (await user_row(phone))["phone_verified_at"] is None


async def test_ac40_disabled_account_cookie_does_not_verify():
    phone = unique_phone()
    async with new_customer(phone) as c:
        await x("UPDATE users SET is_active=false WHERE phone=:p", p=phone)
        body = await booking_verify(c, phone)
        assert body["account_verified"] is False
        assert (await user_row(phone))["phone_verified_at"] is None


async def test_ac40_garbage_cookie_is_a_guest_not_a_500():
    phone = unique_phone()
    async with _client() as c:
        c.cookies.set("access_token", "not.a.jwt")
        c.cookies.set("admin_session", "x" * 40)
        body = await booking_verify(c, phone)
        assert body["account_verified"] is False and body["phone_token"]


async def test_ac40_google_account_without_phone_is_not_given_a_phone():
    sub = "qa-ac40-" + uuid.uuid4().hex[:12]
    row = await q(
        "INSERT INTO users (full_name, google_sub, google_email, role, is_active)"
        " VALUES ('QA Google AC40', :g, 'qa-ac40@example.com', 'customer', true)"
        " RETURNING id, token_version",
        g=sub,
    )
    from app.core.security import create_token

    token = create_token(str(row[0]["id"]), "access", row[0]["token_version"])
    phone = unique_phone()
    async with _client() as c:
        c.cookies.set("access_token", token)
        assert (await c.get(f"{API}/auth/me")).status_code == 200
        body = await booking_verify(c, phone)
        assert body["account_verified"] is False
    after = (await q("SELECT phone, phone_verified_at FROM users WHERE id=:i", i=row[0]["id"]))[0]
    assert after["phone"] is None and after["phone_verified_at"] is None
    assert not await q("SELECT 1 FROM users WHERE phone=:p", p=phone), (
        "no account created for the phone"
    )


async def test_ac40_response_shape_is_stable():
    own = unique_phone()
    async with new_customer(own) as c:
        body = await booking_verify(c, own)
        assert isinstance(body["account_verified"], bool) and isinstance(body["phone_token"], str)
        assert "otp" not in body and "test_otp" not in body


async def test_ac40_verify_needs_origin_even_with_a_customer_cookie():
    phone = unique_phone()
    async with new_customer(phone) as c:
        r = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        otp = r.json()["test_otp"]
        r = await c.post(
            f"{WEB}/phone/verify",
            json={"phone": phone, "otp": otp},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"
        assert (await user_row(phone))["phone_verified_at"] is None

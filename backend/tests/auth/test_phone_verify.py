import asyncio
from datetime import UTC, datetime

import pytest
from httpx import Cookies
from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import service
from app.modules.auth.models import (
    AuditAction,
    User,
)
from tests.client import API, make_client
from tests.conftest import slot
from tests.helpers import (
    GOOGLE,
    PHONE_REQUEST,
    PHONE_VERIFY,
    RESET_REQUEST,
    SIGN_IN,
    audit_count,
    get_me,
    google_client,
    google_id_token,
    new_ip,
    new_phone,
    pause_commit,
    request_and_verify_phone,
    rewind_requests,
)


async def test_phone_verify_needs_customer_login(anon, admin):
    for c in [anon, admin]:
        r = await c.post(PHONE_REQUEST, json={"phone": new_phone()})
        assert r.status_code == 401
        r = await c.post(PHONE_VERIFY, json={"phone": new_phone(), "otp": "123456"})
        assert r.status_code == 401


async def test_phone_verify_attaches_phone(sent_otps):
    phone = new_phone()
    async with google_client() as c:
        me = await get_me(c)
        r = await c.post(PHONE_REQUEST, json={"phone": phone})
        assert r.status_code == 202
        assert r.json()["resend_after"] == settings.OTP_RESEND_SECONDS
        otp = sent_otps[me["id"]]

        wrong = "000000" if otp != "000000" else "111111"
        r = await c.post(PHONE_VERIFY, json={"phone": phone, "otp": wrong})
        assert r.status_code == 400
        assert r.json()["detail"] == {
            "code": "otp_invalid",
            "message": "Mã xác minh không đúng.",
            "attempts_left": settings.OTP_MAX_ATTEMPTS - 1,
        }
        # Mã gắn với SĐT đã yêu cầu: số khác ⇒ không có mã
        r = await c.post(PHONE_VERIFY, json={"phone": new_phone(), "otp": otp})
        assert r.json()["detail"]["code"] == "otp_expired"

        r = await c.post(PHONE_VERIFY, json={"phone": phone, "otp": otp})
        assert r.status_code == 200, r.text
        assert r.json()["merged"] is False
        assert r.json()["account"]["id"] == me["id"]
        assert (await get_me(c))["phone"] == phone
        assert await audit_count(AuditAction.PHONE_VERIFIED, me["id"]) == 1

        # Mã dùng rồi; đã có SĐT thì không đổi qua đây
        r = await c.post(PHONE_VERIFY, json={"phone": phone, "otp": otp})
        assert r.json()["detail"]["code"] == "otp_expired"
        r = await c.post(PHONE_REQUEST, json={"phone": new_phone()})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "phone_already_set"


@pytest.mark.usefixtures("sent_otps")
async def test_phone_verify_shares_rate_limit_with_password_reset(anon):
    phone = new_phone()
    r = await anon.post(RESET_REQUEST, json={"phone": phone})
    assert r.status_code == 202
    async with google_client() as c:
        r = await c.post(PHONE_REQUEST, json={"phone": phone})
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "otp_rate_limited"


async def test_phone_verify_merges_into_existing_customer(customer, sent_otps):
    """Gộp vào tài khoản đăng ký trước bằng SĐT nạn nhân ⇒ mật khẩu + JWT cũ của đích hết dùng."""
    target = await get_me(customer)
    attacker_cookies = Cookies(customer.cookies)
    sub = f"g-merge-{datetime.now(UTC).timestamp()}"
    async with google_client(sub) as c:
        google_id = (await get_me(c))["id"]
        google_cookies = Cookies(c.cookies)
        r = await request_and_verify_phone(c, sent_otps, target["phone"])
        assert r.status_code == 200, r.text
        assert r.json()["merged"] is True
        assert r.json()["password_cleared"] is True
        assert r.json()["account"]["id"] == target["id"]
        # Cookie đã đổi sang tài khoản đích (token_version mới)
        me = await get_me(c)
        assert me["id"] == target["id"] and me["google_email"] == "khach@gmail.com"
        assert (await c.post(f"{API}/auth/refresh")).status_code == 200

    async with SessionLocal() as s:
        assert await s.get(User, google_id) is None
    assert await audit_count(AuditAction.ACCOUNT_MERGED, target["id"]) == 1
    # JWT cũ: của tài khoản Google đã xóa và của tài khoản đích trước khi gộp ⇒ 401
    for cookies in [google_cookies, attacker_cookies]:
        old = make_client()
        old.cookies = cookies
        async with old:
            assert (await old.get(f"{API}/auth/me")).status_code == 401
            assert (await old.post(f"{API}/auth/refresh")).status_code == 401
    async with make_client() as again:
        # Mật khẩu cũ (của người đăng ký trước) không còn dùng được
        r = await again.post(
            SIGN_IN, json={"login": target["phone"], "password": "Password@123"}, headers=new_ip()
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "E-001"
        # Đăng nhập Google lần sau vào thẳng tài khoản đích
        r = await again.post(GOOGLE, json={"credential": google_id_token(sub)}, headers=new_ip())
        assert r.json()["account"]["id"] == target["id"]


async def test_phone_verify_merge_into_passwordless_account(sent_otps):
    """Đích không có mật khẩu ⇒ `password_cleared` false (FE không báo mất mật khẩu)."""
    phone = new_phone()
    async with make_client() as c:
        r = await c.post(
            f"{API}/auth/register",
            json={"full_name": "Chủ số", "phone": phone, "password": "Password@123"},
        )
        target_id = r.json()["id"]
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == target_id).values(hashed_password=None))
        await s.commit()
    async with google_client() as c:
        r = await request_and_verify_phone(c, sent_otps, phone)
        assert r.status_code == 200, r.text
        assert r.json()["merged"] is True and r.json()["password_cleared"] is False


async def test_register_racing_phone_verify_same_phone(sent_otps):
    """Đăng ký chen lúc khách Google đang gắn cùng SĐT ⇒ 409, không 500."""
    phone = new_phone()
    async with google_client() as c:
        user_id = (await get_me(c))["id"]
        assert (await c.post(PHONE_REQUEST, json={"phone": phone})).status_code == 202

    release = asyncio.Event()
    async with SessionLocal() as s, make_client() as anon:
        user = await s.get(User, user_id)
        pause_commit(s, release)
        task = asyncio.create_task(service.verify_phone(s, user, phone, sent_otps[user_id]))
        await asyncio.sleep(0.2)
        register = asyncio.create_task(
            anon.post(
                f"{API}/auth/register",
                json={"full_name": "Chen ngang", "phone": phone, "password": "Password@123"},
            )
        )
        await asyncio.sleep(0.2)
        release.set()
        assert (await task).account.phone == phone
        assert (await register).status_code == 409


async def test_phone_verify_admin_phone_or_linked_google_409(customer, sent_otps):
    # SĐT của Admin
    async with google_client() as c:
        r = await request_and_verify_phone(c, sent_otps, settings.FIRST_ADMIN_PHONE)
        assert r.status_code == 409
        assert r.json()["detail"] == {
            "code": "phone_unusable",
            "message": "Số điện thoại không dùng được.",
        }
        assert (await get_me(c))["phone"] is None
    # SĐT của khách đã gắn Google khác ⇒ không gộp (một tài khoản một Google)
    target = await get_me(customer)
    async with google_client() as first:
        assert (await request_and_verify_phone(first, sent_otps, target["phone"])).json()[
            "merged"
        ] is True
    await rewind_requests(settings.OTP_RESEND_SECONDS)
    async with google_client() as second:
        r = await request_and_verify_phone(second, sent_otps, target["phone"])
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "phone_unusable"


async def test_phone_verify_merge_refused_when_google_account_has_bookings(
    customer, admin, sent_otps
):
    """Đơn tại quầy đã gắn tài khoản Google ⇒ không tự gộp (không mất đơn)."""
    target = await get_me(customer)
    async with google_client() as c:
        google_id = (await get_me(c))["id"]
        r = await admin.post(
            f"{API}/admin/bookings",
            json={
                "slots": [slot(4, 13, days=6)],
                "customer_name": "Khách Google",
                "customer_id": google_id,
                "confirm": False,
            },
        )
        assert r.status_code == 201, r.text
        r = await request_and_verify_phone(c, sent_otps, target["phone"])
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "merge_has_bookings"
        assert (await get_me(c))["id"] == google_id


async def test_phone_verify_concurrent_same_phone(sent_otps):
    """Hai khách Google cùng gắn một SĐT mới ⇒ một bên được, bên kia phone_unusable."""
    phone = new_phone()
    async with google_client() as a, google_client() as b:
        ids = [(await get_me(a))["id"], (await get_me(b))["id"]]
        assert (await a.post(PHONE_REQUEST, json={"phone": phone})).status_code == 202
        await rewind_requests(settings.OTP_RESEND_SECONDS)
        assert (await b.post(PHONE_REQUEST, json={"phone": phone})).status_code == 202

    release = asyncio.Event()
    async with SessionLocal() as first, SessionLocal() as second:
        user_a, user_b = await first.get(User, ids[0]), await second.get(User, ids[1])
        pause_commit(first, release)
        task = asyncio.create_task(service.verify_phone(first, user_a, phone, sent_otps[ids[0]]))
        await asyncio.sleep(0.2)  # A đã gắn SĐT, chưa commit
        racing = asyncio.create_task(service.verify_phone(second, user_b, phone, sent_otps[ids[1]]))
        await asyncio.sleep(0.2)
        release.set()
        assert (await task).account.phone == phone
        with pytest.raises(service.OtpError) as error:
            await racing
        assert error.value.code == "phone_unusable"


async def test_booking_requires_verified_phone(sent_otps):
    async with google_client() as c:
        body = {"slots": [slot(4, 15, days=6)]}
        r = await c.post(f"{API}/bookings", json=body)
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "phone_required"

        phone = new_phone()
        assert (await request_and_verify_phone(c, sent_otps, phone)).status_code == 200
        r = await c.post(f"{API}/bookings", json=body)
        assert r.status_code == 201, r.text
        assert r.json()["customer_phone"] == phone

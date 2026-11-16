"""T-021: đăng ký 2 bước bằng OTP, tài khoản có SĐT đã xác minh = hội viên (R1).

AC1–AC7, AC9–AC10, SEC1–SEC5. Backfill (AC7) ở ``test_registration_migration.py``.
"""

import asyncio

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import RegistrationRequest, Role, User
from app.modules.members import api as members
from app.modules.members.models import Customer
from tests.conftest import (
    API,
    CUSTOMER_PASSWORD,
    _client,
    age_otp_codes,
    idem,
    new_customer,
    register,
    sign_in,
    unique_phone,
)
from tests.helpers_booking import new_court
from tests.helpers_web import checkout, sepay_payload, webhook
from tests.test_customer_accounts import fake_google, google_customer  # noqa: F401

REQ = f"{API}/auth/register/request"
VERIFY = f"{API}/auth/register/verify"
M = f"{API}/members"


@pytest.fixture
async def phones():
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.execute(delete(User).where(User.phone.in_(created)))
        await s.commit()


async def customer_of(phone: str) -> Customer | None:
    async with SessionLocal() as s:
        return await s.scalar(select(Customer).where(Customer.phone == phone))


async def user_of(**where) -> User | None:
    async with SessionLocal() as s:
        q = select(User)
        for k, v in where.items():
            q = q.where(getattr(User, k) == v)
        return await s.scalar(q)


async def audit_rows(action: str, code: str, phone: str | None = None) -> list[AuditLog]:
    """Mã HV được cấp lại sau khi test khác dọn hồ sơ (nhật ký không xóa) -> lọc thêm SĐT che."""
    q = select(AuditLog).where(AuditLog.action == action, AuditLog.entity_code == code)
    if phone is not None:
        q = q.where(AuditLog.detail["phone"].astext == f"{phone[:4]} xxx {phone[-3:]}")
    async with SessionLocal() as s:
        return list(await s.scalars(q))


async def request_code(client, phone: str, full_name: str = "Khách Mới", password: str = ""):
    await age_otp_codes(phone)
    return await client.post(
        REQ,
        json={"full_name": full_name, "phone": phone, "password": password or CUSTOMER_PASSWORD},
    )


# ------------------------------------------------------------------ AC1, AC2: đăng ký 2 bước


async def test_register_creates_account_and_member(anon, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await request_code(anon, phone, " Phạm  Thị Hoa ")
    assert r.status_code == 202, r.text
    assert set(r.json()) == {"resend_after", "test_otp"} and len(r.json()["test_otp"]) == 6
    # Bước 1 chưa tạo tài khoản, mật khẩu chỉ lưu dạng băm
    assert await user_of(phone=phone) is None
    async with SessionLocal() as s:
        pending = await s.scalar(
            select(RegistrationRequest).order_by(RegistrationRequest.otp_code_id.desc()).limit(1)
        )
    assert pending.full_name == "Phạm Thị Hoa" and CUSTOMER_PASSWORD not in pending.hashed_password

    r = await anon.post(VERIFY, json={"phone": phone, "otp": r.json()["test_otp"]})
    assert r.status_code == 201, r.text
    body = r.json()
    code = body["member_code"]
    assert body["upgraded_from_temp"] is False and code.startswith("HV")
    assert body["account"]["phone_verified"] is True and body["account"]["is_member"] is True
    # Đăng nhập luôn: cookie khách dùng được ngay, vào được khu hội viên
    assert (await anon.get(f"{API}/auth/me")).json()["is_member"] is True
    assert (await anon.get(f"{API}/member-area/me")).status_code == 200

    c = await customer_of(phone)
    assert (c.kind, c.member_code, c.full_name, c.tier) == ("member", code, "Phạm Thị Hoa", None)
    assert c.is_active and c.source == "self_register"
    async with SessionLocal() as s:  # dữ liệu chờ đã xóa
        assert (
            await s.scalar(
                select(func.count())
                .select_from(RegistrationRequest)
                .where(RegistrationRequest.full_name == "Phạm Thị Hoa")
            )
            == 0
        )
    # AC10: nhật ký có Mã HV, SĐT che
    [row] = await audit_rows("member.self_register", code, phone)
    assert (
        row.detail["member_code"] == code and row.detail["phone"] == f"{phone[:4]} xxx {phone[-3:]}"
    )
    assert phone not in str(row.detail)
    user = await user_of(phone=phone)
    assert await audit_rows("auth.register", str(user.id))

    # Mật khẩu đăng ký dùng được
    async with _client() as c2:
        assert (await sign_in(c2, phone, CUSTOMER_PASSWORD)).status_code == 200


async def test_admin_list_shows_self_registered_source(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    async with _client() as c:
        assert (await register(c, phone, "Tự Đăng Ký")).status_code == 201
    r = await admin.get(M, params={"q": phone})
    [row] = r.json()["items"]
    assert row["source"] == "self_register" and row["kind"] == "member"  # AC9


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "A", "phone": "12345", "password": CUSTOMER_PASSWORD},
        {"full_name": "A", "phone": "0812345678", "password": "password123"},  # thiếu in hoa
        {"full_name": "", "phone": "0812345678", "password": CUSTOMER_PASSWORD},
        {"full_name": "A" * 101, "phone": "0812345678", "password": CUSTOMER_PASSWORD},
    ],
)
async def test_request_validation(anon, body):
    assert (await anon.post(REQ, json=body)).status_code == 422


async def test_wrong_code_creates_nothing(anon, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await request_code(anon, phone)
    wrong = "000000" if r.json()["test_otp"] != "000000" else "111111"
    r = await anon.post(VERIFY, json={"phone": phone, "otp": wrong})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-AUTH-14"
    assert await user_of(phone=phone) is None and await customer_of(phone) is None


async def test_old_register_endpoint_closed(anon):
    """SEC1: không còn đường đăng ký không OTP."""
    r = await anon.post(
        f"{API}/auth/register",
        json={"full_name": "A", "phone": unique_phone(), "password": CUSTOMER_PASSWORD},
    )
    assert r.status_code == 410 and r.json()["detail"]["code"] == "E-AUTH-32"


async def test_no_otp_channel(anon, monkeypatch):
    """AC4: chưa có kênh OTP -> E-AUTH-23 với câu của đăng ký."""
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    monkeypatch.setattr(settings, "ZALO_APP_ID", "")
    r = await anon.post(
        REQ, json={"full_name": "A", "phone": unique_phone(), "password": CUSTOMER_PASSWORD}
    )
    assert r.status_code == 503
    assert r.json()["detail"] == {
        "code": "E-AUTH-23",
        "message": "Đăng ký tài khoản đang tạm ngưng. Vui lòng liên hệ quầy.",
    }


# ------------------------------------------------------------------ SEC2: không dò được SĐT


async def test_existing_phone_only_revealed_after_otp(anon, admin, phones):
    taken = unique_phone()
    phones.append(taken)
    async with _client() as c:
        assert (await register(c, taken)).status_code == 201
    free = unique_phone()
    phones.append(free)

    a, b = await request_code(anon, taken), await request_code(anon, free)
    assert a.status_code == b.status_code == 202
    assert set(a.json()) == set(b.json()) and a.json()["resend_after"] == b.json()["resend_after"]

    r = await anon.post(VERIFY, json={"phone": taken, "otp": a.json()["test_otp"]})
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-AUTH-22",
        "message": "Số điện thoại đã có tài khoản. Vui lòng đăng nhập hoặc dùng Quên mật khẩu.",
        "phone": taken,
    }
    assert "access_token" not in r.cookies
    async with SessionLocal() as s:
        assert (
            await s.scalar(select(func.count()).select_from(User).where(User.phone == taken)) == 1
        )


async def test_club_created_account_blocks_register(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await admin.post(M, json={"full_name": "Hội Viên Quầy", "phone": phone}, headers=idem())
    assert r.status_code == 201, r.text
    async with _client() as c:
        r = await register(c, phone)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-AUTH-22"
    user = await user_of(phone=phone)
    assert user.must_change_password and user.phone_verified_at is None  # không bị đụng


# ------------------------------------------------------------------ AC3: tài khoản chưa xác minh


async def test_verifier_takes_phone_from_unverified_account(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone) as old:
        old_user = await user_of(phone=phone)
        async with _client() as c:
            r = await register(c, phone, "Chủ Thật")
            assert r.status_code == 201, r.text
        # Tài khoản cũ: gỡ SĐT, không còn cách đăng nhập -> vô hiệu, phiên cũ hết hiệu lực
        async with SessionLocal() as s:
            stale = await s.get(User, old_user.id)
        assert stale.phone is None and stale.is_active is False
        assert (await old.get(f"{API}/auth/me")).status_code == 401
    [row] = await audit_rows("auth.phone_released", str(old_user.id))
    assert row.actor_type == "system" and row.detail["disabled"] is True
    assert phone not in str(row.detail)
    r = await admin.get(f"{API}/admin/audit-log", params={"action": "auth.phone_released"})
    shown = next(i for i in r.json()["items"] if i["id"] == row.id)
    assert shown["action_label"] == "Gỡ SĐT khỏi tài khoản chưa xác minh"
    # Hội viên tự đăng ký mới không hiện (khách tự làm)
    r = await admin.get(f"{API}/admin/audit-log")
    assert all(i["action"] != "member.self_register" for i in r.json()["items"])
    new_user = await user_of(phone=phone)
    assert new_user.id != old_user.id and new_user.full_name == "Chủ Thật"


async def test_released_account_with_google_stays_active(phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone):
        pass
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.phone == phone).values(google_sub=f"g-{phone}"))
        await s.commit()
    async with _client() as c:
        assert (await register(c, phone)).status_code == 201
    kept = await user_of(google_sub=f"g-{phone}")
    assert kept.phone is None and kept.is_active is True


# ------------------------------------------------------------------ R1: hồ sơ có sẵn


async def test_temp_profile_upgraded_keeps_history(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await admin.post(
        f"{M}/temp", json={"full_name": "Khách Quen", "phone": phone}, headers=idem()
    )
    assert r.status_code == 201, r.text
    temp = await customer_of(phone)

    async with _client() as c:
        r = await register(c, phone, "Tên Khác")
    assert r.status_code == 201, r.text
    assert r.json()["upgraded_from_temp"] is True
    code = r.json()["member_code"]
    c = await customer_of(phone)
    assert c.id == temp.id and c.public_id == temp.public_id  # cùng dòng -> giữ lịch sử
    assert (c.kind, c.member_code, c.full_name) == ("member", code, "Khách Quen")  # giữ tên
    assert c.source == "self_register" and c.created_at > temp.created_at
    assert c.version == temp.version + 1
    [row] = await audit_rows("member.auto_upgrade_temp", code, phone)
    assert row.detail["member_code"] == code and phone not in str(row.detail)
    # Hệ thống đổi dữ liệu quầy đã tạo -> hiện ở Lịch sử thao tác
    assert (row.actor_type, row.actor_label) == ("system", "Hệ thống")
    r = await admin.get(f"{API}/admin/audit-log", params={"action": "member.auto_upgrade_temp"})
    shown = next(i for i in r.json()["items"] if i["id"] == row.id)
    assert shown["action_label"] == "Tự nâng hồ sơ tạm thành hội viên"
    assert shown["actor_label"] == "Hệ thống" and shown["target"]["code"] == code


async def test_existing_member_only_linked(phones):
    phone = unique_phone()
    phones.append(phone)
    async with SessionLocal() as s:  # hội viên nhập tay, chưa có tài khoản
        await members.upsert_member(s, "HV9990", "Hội Viên Sẵn", phone, "Khá")
        await s.commit()
    try:
        async with _client() as c:
            r = await register(c, phone, "Tên Tài Khoản")
        assert r.status_code == 201, r.text
        assert r.json()["member_code"] == "HV9990" and r.json()["upgraded_from_temp"] is False
        c = await customer_of(phone)
        assert (c.full_name, c.tier, c.source) == ("Hội Viên Sẵn", "Khá", "counter")
        assert not await audit_rows("member.self_register", "HV9990")
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Customer).where(Customer.member_code == "HV9990"))
            await s.commit()


async def test_inactive_member_locks_new_account(phones):
    phone = unique_phone()
    phones.append(phone)
    async with SessionLocal() as s:
        await members.upsert_member(s, "HV9991", "Hội Viên Ngừng", phone, None, is_active=False)
        await s.commit()
    try:
        async with _client() as c:
            r = await register(c, phone)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-31"
            assert (await c.get(f"{API}/auth/me")).status_code == 401
        assert (await user_of(phone=phone)).is_active is False
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Customer).where(Customer.member_code == "HV9991"))
            await s.commit()


async def test_admin_still_cannot_promote_temp(admin, phones):
    """R2: màn quản trị vẫn chặn Thêm hội viên trùng hồ sơ tạm (E-MEM-1)."""
    phone = unique_phone()
    phones.append(phone)
    r = await admin.post(f"{M}/temp", json={"full_name": "Tạm", "phone": phone}, headers=idem())
    assert r.status_code == 201
    r = await admin.post(M, json={"full_name": "Tạm", "phone": phone}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-1"


# ------------------------------------------------------------------ SEC5: đồng thời


async def test_concurrent_verify_creates_one_account_and_member(anon, phones):
    phone = unique_phone()
    phones.append(phone)
    otp = (await request_code(anon, phone)).json()["test_otp"]
    async with _client() as a, _client() as b:
        results = await asyncio.gather(
            a.post(VERIFY, json={"phone": phone, "otp": otp}),
            b.post(VERIFY, json={"phone": phone, "otp": otp}),
        )
    assert sorted(r.status_code for r in results) == [201, 400]
    async with SessionLocal() as s:
        assert (
            await s.scalar(select(func.count()).select_from(User).where(User.phone == phone)) == 1
        )
        assert (
            await s.scalar(
                select(func.count()).select_from(Customer).where(Customer.phone == phone)
            )
            == 1
        )


# ------------------------------------------------------------------ AC6: các chỗ xác minh khác


async def test_phone_verify_makes_member(phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone) as c:  # tài khoản đời cũ, SĐT chưa xác minh
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is False
        r = await c.post(f"{API}/auth/phone/request", json={"phone": phone})
        assert r.status_code == 202, r.text
        r = await c.post(
            f"{API}/auth/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]}
        )
        assert r.status_code == 200, r.text
        assert r.json()["became_member"] is True and r.json()["member_code"].startswith("HV")
        assert r.json()["account"]["is_member"] is True
    assert (await customer_of(phone)).kind == "member"


async def test_password_reset_makes_member(anon, phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone):
        pass
    r = await anon.post(f"{API}/auth/password-reset/request", json={"phone": phone})
    r = await anon.post(
        f"{API}/auth/password-reset/verify", json={"phone": phone, "otp": r.json()["test_otp"]}
    )
    token = r.json()["reset_token"]
    r = await anon.post(
        f"{API}/auth/password-reset/confirm",
        json={"reset_token": token, "password": "NewPassword9"},
    )
    assert r.status_code == 204, r.text
    c = await customer_of(phone)
    assert c is not None and c.kind == "member" and c.source == "self_register"


# ------------------------------------------------------------------ AC5: OTP khi đặt online


async def booking_verify(client, phone: str):
    await age_otp_codes(phone)
    r = await client.post(f"{API}/web/booking/phone/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    return await client.post(
        f"{API}/web/booking/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]}
    )


async def test_booking_otp_makes_signed_in_customer_member(phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone) as c:
        r = await booking_verify(c, phone)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["account_verified"] and body["became_member"] and body["phone_token"]
        code = body["member_code"]
        # Lần sau: đã là hội viên -> không "vừa thành", vẫn trả mã
        r = await booking_verify(c, phone)
        assert (r.json()["became_member"], r.json()["member_code"]) == (False, code)
    assert (await customer_of(phone)).member_code == code


async def test_booking_otp_anonymous_does_not_create_member(anon, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await booking_verify(anon, phone)
    assert r.status_code == 200 and r.json()["became_member"] is False
    assert await customer_of(phone) is None  # khách vãng lai: hồ sơ tạo khi tiền về


async def test_booking_otp_attaches_phone_to_google_account(phones):
    phone = unique_phone()
    phones.append(phone)
    async with google_customer() as c:
        assert (await c.get(f"{API}/auth/me")).json()["phone"] is None
        r = await booking_verify(c, phone)
        assert r.status_code == 200, r.text
        assert r.json()["became_member"] and r.json()["account_merged"] is False
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["phone"] == phone and me["phone_verified"] and me["is_member"]


async def test_booking_otp_merges_google_into_phone_owner(phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone):  # chủ SĐT: tài khoản mật khẩu, chưa xác minh
        pass
    owner = await user_of(phone=phone)
    async with google_customer() as c:
        r = await booking_verify(c, phone)
        assert r.status_code == 200, r.text
        assert r.json()["account_merged"] is True and r.json()["became_member"] is True
        me = await c.get(f"{API}/auth/me")  # cookie mới -> tài khoản chủ SĐT
        assert me.status_code == 200 and me.json()["id"] == owner.id


async def test_booking_otp_unusable_phone_still_gives_token(admin, phones):
    """SĐT của tài khoản Admin -> E-AUTH-18: không gắn, lượt đặt vẫn có ``phone_token``."""
    async with SessionLocal() as s:
        admin_phone = await s.scalar(select(User.phone).where(User.role == Role.ADMIN).limit(1))
    async with google_customer() as c:
        r = await booking_verify(c, admin_phone)
        assert r.status_code == 200 and r.json()["phone_token"]
        assert r.json()["became_member"] is False and r.json()["member_code"] is None
        assert r.json()["reason"] == "E-AUTH-18"
        assert (await c.get(f"{API}/auth/me")).json()["phone"] is None


async def test_booking_otp_for_other_phone_keeps_account(phones):
    """Tài khoản có SĐT khác -> chỉ xác minh cho lượt đặt, ``reason`` E-AUTH-17."""
    own, other = unique_phone(), unique_phone()
    phones.extend([own, other])
    async with new_customer(own) as c:
        r = await booking_verify(c, other)
        assert r.status_code == 200 and r.json()["phone_token"]
        assert (r.json()["became_member"], r.json()["reason"]) == (False, "E-AUTH-17")
    assert await customer_of(other) is None and (await user_of(phone=own)) is not None


async def test_online_booking_after_member_keeps_member_snapshot(admin, phones):
    """Đặt online bằng SĐT vừa thành hội viên -> booking gắn hội viên."""
    phone = unique_phone()
    phones.append(phone)
    async with _client() as c:
        code = (await register(c, phone)).json()["member_code"]
        court = await new_court(admin)
        r = await checkout(c, [(court["code"], 20)], phone=phone)
        assert r.status_code == 201, r.text
        co = r.json()
        assert (await webhook(c, sepay_payload(co["pay_ref"], co["amount"]))).status_code == 200
    r = await admin.get(f"{M}/{code}")
    assert r.status_code == 200 and r.json()["bookings"] == 1

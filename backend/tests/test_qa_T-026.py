# ruff: noqa: E501
"""QA T-026 (API): Thêm hội viên báo tài khoản (`account_created`, `initial_password_expires_at`), không lộ mật khẩu. AC4, AC5, AC6 + đăng nhập SĐT/SĐT."""

import datetime as dt
import json

import pytest
from sqlalchemy import delete, select, text, update

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.modules.auth.models import User
from app.modules.booking_engine.models import OutboxEvent
from app.modules.members.models import Customer
from tests.conftest import API, _client, idem, new_customer, sign_in, unique_phone

M = f"{API}/members"
PW_WORDS = ("hashed", "$argon2", "$2b$", "mật khẩu")


@pytest.fixture
async def phones():
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.execute(delete(User).where(User.phone.in_(created)))
        await s.commit()


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def add(client, phone: str, name: str = "QA Hội Viên Mới", headers=None):
    return await client.post(M, json={"full_name": name, "phone": phone}, headers=headers or idem())


def deadline(data: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(data["initial_password_expires_at"])


async def test_new_phone_admin_and_staff_get_the_same_answer_and_a_3_day_deadline(
    admin, staff, phones
):
    days = dt.timedelta(days=settings.MEMBER_INITIAL_PASSWORD_DAYS)
    assert days == dt.timedelta(days=3)
    results = []
    for who in (admin, staff):  # AC6: ai có quyền Thêm hội viên đều thấy như nhau
        phone = unique_phone()
        phones.append(phone)
        before = dt.datetime.now(dt.UTC)
        r = await add(who, phone)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["account_created"] is True
        assert before + days <= deadline(d) <= dt.datetime.now(dt.UTC) + days, (
            "hạn = lúc tạo + 3 ngày"
        )
        assert deadline(d).tzinfo is not None, "có múi giờ"
        results.append(sorted(k for k in d if k.startswith("account") or k.startswith("initial")))
    assert results[0] == results[1] == ["account_created", "initial_password_expires_at"]


async def test_new_member_signs_in_with_phone_as_password_and_must_change_it(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    assert (await add(admin, phone)).status_code == 201
    async with _client() as c:
        r = await sign_in(c, phone, phone)
        assert r.status_code == 200, r.text
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["must_change_password"] is True and me["phone"] == phone
        wrong = await sign_in(c, phone, phone + "1")
        assert wrong.status_code in (400, 401, 403)


async def test_initial_password_expires_after_3_days_then_e_auth_30(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    r = await add(admin, phone)
    assert r.status_code == 201
    async with SessionLocal() as s:  # giả thời gian: lùi mốc tạo tài khoản quá hạn một chút
        await s.execute(
            update(User)
            .where(User.phone == phone)
            .values(member_account_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=3, minutes=1))
        )
        await s.commit()
    async with _client() as c:
        r = await sign_in(c, phone, phone)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-30"
    async with SessionLocal() as s:  # còn trong hạn một chút thì vẫn vào được
        await s.execute(
            update(User)
            .where(User.phone == phone)
            .values(member_account_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=2, hours=23))
        )
        await s.commit()
    async with _client() as c:
        assert (await sign_in(c, phone, phone)).status_code == 200


async def test_existing_account_phone_keeps_its_password_and_reports_false(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone) as c:  # tài khoản có sẵn, mật khẩu riêng của khách
        assert (await c.get(f"{API}/auth/me")).status_code == 200
    r = await add(admin, phone, "QA Đã Có Tài Khoản")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["account_created"] is False and d["initial_password_expires_at"] is None
    async with _client() as c:
        assert (await sign_in(c, phone, phone)).status_code in (400, 401, 403), (
            "mật khẩu = SĐT KHÔNG được đặt cho tài khoản đã có"
        )
    from tests.conftest import CUSTOMER_PASSWORD

    async with _client() as c:
        ok = await sign_in(c, phone, CUSTOMER_PASSWORD)
        assert ok.status_code == 200, "mật khẩu cũ vẫn dùng được"
        me = (await c.get(f"{API}/auth/me")).json()
        assert me["must_change_password"] is False, "không bị bắt đổi mật khẩu"
    row = (await q("SELECT member_account_at FROM users WHERE phone=:p", p=phone))[0]
    assert row["member_account_at"] is None, "không gắn hạn mật khẩu ban đầu cho tài khoản đã có"


async def test_ac4_replay_with_same_key_returns_the_same_body_flags_and_deadline(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    key = idem()
    first = await add(admin, phone, headers=key)
    again = await add(admin, phone, headers=key)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json(), "đúng body lần đầu gồm cờ và hạn"
    assert (
        again.headers.get("idempotent-replayed") == "true"
        and first.headers.get("idempotent-replayed") is None
    )
    assert first.json()["account_created"] is True
    assert (
        len(await q("SELECT 1 FROM customer WHERE phone=:p", p=phone)) == 1
        and len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1
    )
    # replay với SĐT đã có tài khoản cũng giữ nguyên cờ false
    phone2 = unique_phone()
    phones.append(phone2)
    async with new_customer(phone2):
        pass
    key2 = idem()
    a, b = await add(admin, phone2, headers=key2), await add(admin, phone2, headers=key2)
    assert (
        a.json() == b.json()
        and b.json()["account_created"] is False
        and b.json()["initial_password_expires_at"] is None
    )


async def test_ac4_other_key_for_the_same_phone_is_a_duplicate_member_and_creates_nothing_new(
    admin, phones
):
    phone = unique_phone()
    phones.append(phone)
    assert (await add(admin, phone)).status_code == 201
    r = await add(admin, phone)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-018"
    assert "account_created" not in json.dumps(r.json()), "lỗi không mang cờ tài khoản"
    assert len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1, (
        "không tạo tài khoản thứ hai"
    )


async def test_ac5_no_password_in_response_audit_or_outbox(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    base_audit = (await q("SELECT coalesce(max(id),0) AS m FROM audit_log"))[0]["m"]
    base_out = (await q("SELECT coalesce(max(id),0) AS m FROM booking.outbox"))[0]["m"]
    r = await add(admin, phone, "QA Không Lộ Bí Mật")
    assert r.status_code == 201
    low = r.text.lower()
    assert not any(w in low for w in PW_WORDS), "response không có giá trị băm / chữ mật khẩu"
    keys = {k.lower() for k in r.json()}
    assert not [
        k
        for k in keys
        if ("password" in k or "hash" in k or "secret" in k) and k != "initial_password_expires_at"
    ], keys
    rows = await q("SELECT action, detail::text AS d FROM audit_log WHERE id > :b", b=base_audit)
    assert rows, "có ghi nhật ký tạo hội viên"
    for row in rows:
        d = row["d"].lower()
        assert (
            "$argon2" not in d and "hashed" not in d and "password" not in d and "mật khẩu" not in d
        ), row["action"]
        assert phone not in row["d"], f"nhật ký {row['action']} không chứa SĐT đầy đủ"
    async with SessionLocal() as s:
        events = list(await s.scalars(select(OutboxEvent.payload).where(OutboxEvent.id > base_out)))
    blob = json.dumps(events, ensure_ascii=False).lower()
    assert (
        "password" not in blob
        and "$argon2" not in blob
        and "hashed" not in blob
        and "mật khẩu" not in blob
    )


async def test_permissions_only_admin_and_staff_can_add_members(
    admin, staff, anon, customer, phones
):
    phone = unique_phone()
    phones.append(phone)
    assert (await add(anon, phone)).status_code == 401
    assert (await add(customer, phone)).status_code in (401, 403)
    assert not await q("SELECT 1 FROM customer WHERE phone=:p", p=phone) and not await q(
        "SELECT 1 FROM users WHERE phone=:p", p=phone
    )
    assert (await add(staff, phone)).status_code == 201


async def test_member_with_inactive_existing_account_or_staff_phone_does_not_get_phone_as_password(
    admin, staff, phones
):
    # SĐT của một tài khoản NV/Admin: tạo hội viên không được đổi mật khẩu tài khoản đó
    admin_phone = settings.FIRST_ADMIN_PHONE
    r = await add(admin, admin_phone, "QA Trùng SĐT Admin")
    if r.status_code == 201:
        d = r.json()
        assert d["account_created"] is False and d["initial_password_expires_at"] is None
        async with SessionLocal() as s:
            await s.execute(
                delete(Customer).where(
                    Customer.phone == admin_phone, Customer.full_name == "QA Trùng SĐT Admin"
                )
            )
            await s.commit()
    else:
        assert r.status_code in (409, 422, 403), r.text
    async with _client() as c:
        assert (await sign_in(c, admin_phone, admin_phone)).status_code in (400, 401, 403), (
            "mật khẩu Admin không thành SĐT"
        )

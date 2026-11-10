# ruff: noqa: E501
"""QA T-021 (đăng ký là thành hội viên, bắt OTP): AC1-AC10, SEC1-SEC5, viết từ spec `T-021-dang-ky-la-hoi-vien.md`
(độc lập với test_registration.py của BACKEND). Quy ước như các file QA khác: xfail(strict) = lệch spec đã ghi.
"""

import asyncio
import datetime as dt
import re
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.conftest import (
    API,
    CUSTOMER_PASSWORD,
    _client,
    age_otp_codes,
    idem,
    register,
    sign_in,
    unique_phone,
)
from tests.helpers_booking import book, new_court, random_phone, safe_hour, temp
from tests.helpers_web import WEB
from tests.qa_accounts import db_account

REG = f"{API}/auth/register"
M = f"{API}/members"
LOG = f"{API}/admin/audit-log"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def err(r) -> dict:
    return r.json()["detail"]


async def request(client, phone, name="Khách Tự Đăng Ký", password=CUSTOMER_PASSWORD, **extra):
    await age_otp_codes(phone)
    return await client.post(
        f"{REG}/request", json={"full_name": name, "phone": phone, "password": password, **extra}
    )


async def verify(client, phone, otp):
    return await client.post(f"{REG}/verify", json={"phone": phone, "otp": otp})


async def customer_row(phone: str):
    rows = await q(
        "SELECT id, public_id, kind, member_code, full_name, tier, is_active, source, version, created_at FROM customer WHERE phone=:p",
        p=phone,
    )
    return rows[0] if rows else None


@pytest.fixture
async def cleanup():
    phones: list[str] = []
    yield phones
    if phones:
        await x("DELETE FROM customer WHERE phone = ANY(:p)", p=phones)


# ============================================================ AC1/AC2 đăng ký 2 bước


async def test_ac2_success_creates_verified_account_and_member_in_one_step(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    r = await register(anon, phone, "  Nguyễn   Văn Thử ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"HV\d{4,5}", body["member_code"]) and body["upgraded_from_temp"] is False
    acc = body["account"]
    assert acc["phone"] == phone and acc["phone_verified"] is True and acc["is_member"] is True
    assert acc["full_name"] == "Nguyễn Văn Thử", "họ tên cắt khoảng trắng"
    assert any(c.startswith("access_token=") for c in r.headers.get_list("set-cookie")), (
        "đăng nhập luôn"
    )
    user = (
        await q(
            "SELECT is_active, must_change_password AS m, phone_verified_at IS NOT NULL AS v, member_account_at IS NULL AS no_stamp, role::text AS role FROM users WHERE phone=:p",
            p=phone,
        )
    )[0]
    assert (
        user["is_active"]
        and user["v"]
        and user["m"] is False
        and user["no_stamp"]
        and user["role"] == "member"
    ), "R3: không mật khẩu ban đầu = SĐT"
    c = await customer_row(phone)
    assert (
        c["kind"] == "member" and c["member_code"] == body["member_code"] and c["is_active"] is True
    )
    assert c["tier"] is None, "Hạng = chưa xếp"
    assert c["source"] == "self_register" and c["full_name"] == "Nguyễn Văn Thử"
    assert c["created_at"].astimezone(settings.tz).date() == dt.datetime.now(settings.tz).date(), (
        "ngày tạo = hôm nay"
    )
    assert len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1, (
        "R3: không tạo tài khoản thứ hai"
    )
    # đăng nhập được bằng mật khẩu đã chọn, vào khu hội viên
    async with _client() as c2:
        assert (await sign_in(c2, phone, CUSTOMER_PASSWORD)).status_code == 200
        assert (await c2.get(f"{API}/member-area/me")).status_code == 200


async def test_ac1_request_does_not_create_an_account_or_member(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    r = await request(anon, phone)
    assert r.status_code == 202, r.text
    assert set(r.json()) <= {"resend_after", "test_otp"} and r.json()["resend_after"] > 0
    assert not await q("SELECT 1 FROM users WHERE phone=:p", p=phone), "chưa có tài khoản"
    assert await customer_row(phone) is None, "chưa có hồ sơ hội viên"
    assert not any(c.startswith("access_token=") for c in r.headers.get_list("set-cookie"))


async def test_ac1_validation_of_step_1(anon):
    phone = unique_phone()
    cases = [
        ({"password": "weakpass"}, "mật khẩu yếu"),
        ({"password": "Ab1"}, "quá ngắn"),
        ({"password": phone}, "mật khẩu = SĐT"),
        ({"full_name": ""}, "họ tên rỗng"),
        ({"full_name": "x" * 101}, "họ tên > 100"),
        ({"phone": "123"}, "SĐT sai"),
        ({"phone": ""}, "SĐT rỗng"),
        ({"email": "a@b.vn"}, "trường lạ email"),
        ({"role": "admin"}, "trường lạ role"),
    ]
    for over, why in cases:
        body = {"full_name": "Khách", "phone": phone, "password": CUSTOMER_PASSWORD, **over}
        r = await anon.post(f"{REG}/request", json=body)
        assert r.status_code == 422, (why, r.status_code, r.text[:120])
    assert not await q("SELECT 1 FROM otp_codes WHERE phone=:p", p=phone), (
        "yêu cầu lỗi không phát mã"
    )


async def test_ac1_whitespace_only_name_is_rejected(anon):
    r = await anon.post(
        f"{REG}/request",
        json={"full_name": "   ", "phone": unique_phone(), "password": CUSTOMER_PASSWORD},
    )
    assert r.status_code == 422, r.text[:120]


async def test_ac2_code_is_single_use_wrong_code_does_not_create_and_phone_must_match(
    anon, cleanup
):
    phone, other = unique_phone(), unique_phone()
    cleanup += [phone, other]
    req = await request(anon, phone)
    otp = req.json()["test_otp"]
    bad = "000000" if otp != "000000" else "111111"
    r = await verify(anon, phone, bad)
    assert r.status_code == 400 and err(r)["code"] == "E-AUTH-14" and "attempts_left" in err(r)
    r = await verify(anon, other, otp)
    assert r.status_code == 400, "mã của SĐT này không dùng được cho SĐT khác (SEC1)"
    assert not await q("SELECT 1 FROM users WHERE phone = ANY(:p)", p=[phone, other])
    ok = await verify(anon, phone, otp)
    assert ok.status_code == 201
    again = await verify(anon, phone, otp)
    assert again.status_code == 400, "mã dùng một lần"
    assert len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1


async def test_ac2_pending_password_hash_is_deleted_after_success_and_never_in_plain(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    pw = "Mat-Khau-Dai-" + uuid.uuid4().hex[:6]
    req = await request(anon, phone, password=pw)
    pending = await q(
        "SELECT r.hashed_password FROM registration_requests r JOIN otp_codes o ON o.id=r.otp_code_id WHERE o.phone=:p",
        p=phone,
    )
    assert (
        len(pending) == 1
        and pw not in pending[0]["hashed_password"]
        and pending[0]["hashed_password"].startswith("$argon2")
    )
    assert (await verify(anon, phone, req.json()["test_otp"])).status_code == 201
    left = await q(
        "SELECT count(*) AS n FROM registration_requests r JOIN otp_codes o ON o.id=r.otp_code_id WHERE o.phone=:p",
        p=phone,
    )
    assert left[0]["n"] == 0, "hash chờ bị xóa ngay khi đăng ký xong"


async def test_old_register_endpoint_is_closed_and_sets_no_cookie(anon):
    r = await anon.post(
        REG, json={"full_name": "Cũ", "phone": unique_phone(), "password": CUSTOMER_PASSWORD}
    )
    assert r.status_code == 410 and err(r)["code"] == "E-AUTH-32"
    assert not r.headers.get_list("set-cookie")


async def test_origin_is_required_on_both_steps():
    async with _client() as c:
        for path, body in (
            (
                "/request",
                {"full_name": "A", "phone": unique_phone(), "password": CUSTOMER_PASSWORD},
            ),
            ("/verify", {"phone": unique_phone(), "otp": "123456"}),
        ):
            r = await c.post(f"{REG}{path}", json=body, headers={"Origin": "https://evil.example"})
            assert r.status_code == 403 and err(r)["code"] == "E-SEC-1", path


# ============================================================ SEC2 không dò được SĐT + E-AUTH-22 sau OTP


async def test_sec2_request_answers_the_same_for_every_kind_of_phone(admin, cleanup):
    async with _client() as owner:
        r = await register(owner, unique_phone(), "Đã Xác Minh")
        verified_phone = r.json()["account"]["phone"]
    club = random_phone()
    cleanup.append(club)
    assert (
        await admin.post(M, json={"full_name": "QA HV Sân Tạo", "phone": club}, headers=idem())
    ).status_code == 201
    phones = {
        "unknown": unique_phone(),
        "verified_account": verified_phone,
        "club_created": club,
        "admin": settings.FIRST_ADMIN_PHONE,
    }
    shapes = {}
    for kind, phone in phones.items():
        async with _client() as c:
            r = await request(c, phone)
            shapes[kind] = (
                r.status_code,
                tuple(sorted(r.json())),
                r.json()["resend_after"],
                bool(r.json().get("test_otp")),
            )
    assert len(set(shapes.values())) == 1, shapes


async def test_sec2_e_auth_22_only_after_the_correct_otp_and_same_for_all_kinds(admin, cleanup):
    async with _client() as owner:
        v = (await register(owner, unique_phone(), "Chủ Số")).json()["account"]["phone"]
    club = random_phone()
    cleanup.append(club)
    assert (
        await admin.post(M, json={"full_name": "QA HV Sân Tạo 2", "phone": club}, headers=idem())
    ).status_code == 201
    outs = {}
    for kind, phone in (("verified", v), ("club", club), ("admin", settings.FIRST_ADMIN_PHONE)):
        async with _client() as c:
            req = await request(c, phone)
            wrong = await verify(c, phone, "000000")
            assert wrong.status_code == 400 and err(wrong)["code"] == "E-AUTH-14", (
                "sai mã: giống SĐT lạ"
            )
            good = await verify(c, phone, req.json()["test_otp"])
            outs[kind] = (
                good.status_code,
                err(good)["code"],
                err(good)["message"],
                err(good).get("phone"),
            )
            assert not any(
                h.startswith("access_token=") for h in good.headers.get_list("set-cookie")
            ), "không cấp phiên"
    assert len({o[:3] for o in outs.values()}) == 1, outs
    assert next(iter(outs.values()))[:2] == (409, "E-AUTH-22")
    assert (
        next(iter(outs.values()))[2]
        == "Số điện thoại đã có tài khoản. Vui lòng đăng nhập hoặc dùng Quên mật khẩu."
    )
    assert all(o[3] for o in outs.values()), "kèm phone để FE điền link"
    # tài khoản sẵn có không bị đụng
    async with _client() as c:
        assert (await sign_in(c, v, CUSTOMER_PASSWORD)).status_code == 200


async def test_sec2_wrong_code_answers_are_identical_for_known_and_unknown_phones(anon):
    async with _client() as owner:
        known = (await register(owner, unique_phone(), "Đã Có")).json()["account"]["phone"]
    unknown = unique_phone()
    res = []
    for phone in (known, unknown):
        async with _client() as c:
            await request(c, phone)
            v = await verify(c, phone, "000000")
            res.append((v.status_code, err(v)["code"], err(v).get("attempts_left")))
    assert res[0] == res[1]


async def test_sec2_request_timing_is_comparable_for_known_and_unknown(anon, monkeypatch):
    """Yêu cầu mã cho SĐT đã có và SĐT lạ làm CÙNG số phép băm mật khẩu (không lộ SĐT nào đã đăng ký).

    Trước đây so thời gian (ms); từ T-059 băm rẻ nên tỷ lệ chập chờn theo tải máy (T-067 AC3). Đếm số phép
    băm / so khớp mang cùng ý nghĩa bảo mật và xác định."""
    from app.core import security

    async with _client() as owner:
        known = (await register(owner, unique_phone(), "Đã Có Giờ")).json()["account"]["phone"]

    calls: list[str] = []
    real_hash, real_verify = security.password_hash.hash, security.password_hash.verify

    def spy_hash(*a, **kw):
        calls.append("hash")
        return real_hash(*a, **kw)

    def spy_verify(*a, **kw):
        calls.append("verify")
        return real_verify(*a, **kw)

    monkeypatch.setattr(security.password_hash, "hash", spy_hash)
    monkeypatch.setattr(security.password_hash, "verify", spy_verify)

    async def hashing(phone):
        calls.clear()
        async with _client() as c:
            r = await request(c, phone)
            assert r.status_code == 202
        return sorted(calls)

    k = [await hashing(known) for _ in range(2)]
    u = [await hashing(unique_phone()) for _ in range(2)]
    assert k[0] == k[1] == u[0] == u[1], (
        f"known {k} vs unknown {u}: cả hai đều băm mật khẩu như nhau"
    )
    assert "hash" in k[0] or "verify" in k[0], "cả hai đường đều có phép băm"


# ============================================================ AC3 tài khoản chưa xác minh đời cũ nhường SĐT


async def test_ac3_old_unverified_account_loses_the_phone_to_the_verifier(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    async with _client() as old:
        await db_account(old, phone, "Tài Khoản Cũ", "Old-Pass-123")
        assert (await old.get(f"{API}/auth/me")).status_code == 200
        old_id = (await q("SELECT id FROM users WHERE phone=:p", p=phone))[0]["id"]
        r = await register(anon, phone, "Người Xác Minh")
        assert r.status_code == 201, r.text
        row = (await q("SELECT phone, is_active FROM users WHERE id=:i", i=old_id))[0]
        assert row["phone"] is None, "tài khoản cũ bị gỡ SĐT"
        assert row["is_active"] is False, "không còn cách đăng nhập nào → vô hiệu"
        assert (await old.get(f"{API}/auth/me")).status_code == 401, "phiên cũ bị hủy"
    async with _client() as c:
        assert (await sign_in(c, phone, "Old-Pass-123")).status_code == 401, (
            "mật khẩu cũ không còn vào được"
        )
    new = r.json()["account"]
    assert new["phone"] == phone and new["phone_verified"] is True and new["id"] != old_id
    rows = await q(
        "SELECT actor_type, detail::text AS d FROM audit_log WHERE action='auth.phone_released' AND entity_code=:e",
        e=str(old_id),
    )
    assert len(rows) == 1 and rows[0]["actor_type"] == "system"
    assert phone not in rows[0]["d"], "SĐT trong nhật ký được che"


async def test_ac3_old_account_with_username_or_google_stays_active_without_the_phone(
    anon, cleanup
):
    phone = unique_phone()
    cleanup.append(phone)
    await db_account(None, phone, "Cũ Có Tên Đăng Nhập", "Old-Pass-123")
    await x(
        "UPDATE users SET username='qa.cu.' || substr(md5(random()::text),1,6) WHERE phone=:p",
        p=phone,
    )
    old = (await q("SELECT id, username FROM users WHERE phone=:p", p=phone))[0]
    r = await register(anon, phone, "Người Mới")
    assert r.status_code == 201
    after = (await q("SELECT phone, is_active FROM users WHERE id=:i", i=old["id"]))[0]
    assert after["phone"] is None and after["is_active"] is True, (
        "còn tên đăng nhập nên không vô hiệu"
    )
    async with _client() as c:
        assert (await sign_in(c, old["username"], "Old-Pass-123")).status_code == 200


# ============================================================ AC4 chưa có kênh OTP


async def test_ac4_without_an_otp_channel_registration_is_suspended(anon, monkeypatch):
    monkeypatch.setattr(settings, "OTP_TEST_MODE", False)
    phone = unique_phone()
    assert settings.otp_channel_ready is False, "môi trường test không có Zalo"
    r = await anon.post(
        f"{REG}/request", json={"full_name": "A B", "phone": phone, "password": CUSTOMER_PASSWORD}
    )
    assert r.status_code == 503 and err(r)["code"] == "E-AUTH-23"
    assert err(r)["message"] == "Đăng ký tài khoản đang tạm ngưng. Vui lòng liên hệ quầy."
    assert not await q("SELECT 1 FROM otp_codes WHERE phone=:p", p=phone)
    assert not await q("SELECT 1 FROM users WHERE phone=:p", p=phone)


# ============================================================ R1: các trường hợp hồ sơ theo SĐT


async def test_r1_temp_profile_is_upgraded_on_the_same_row_keeping_history_and_name(
    admin, anon, cleanup
):
    phone = random_phone()
    cleanup.append(phone)
    t = await admin.post(
        f"{M}/temp", json={"full_name": "QA Tên Hồ Sơ Tạm", "phone": phone}, headers=idem()
    )
    assert t.status_code == 201
    court = await new_court(admin)
    h = await safe_hour()
    b = await book(admin, court["code"], h, h + 1, customer=temp("QA Tên Hồ Sơ Tạm", phone))
    assert b.status_code == 201, b.text
    before = await customer_row(phone)
    assert before["kind"] == "temp"
    r = await register(anon, phone, "Tên Trên Tài Khoản")
    assert r.status_code == 201, r.text
    assert r.json()["upgraded_from_temp"] is True
    after = await customer_row(phone)
    assert after["id"] == before["id"] and after["public_id"] == before["public_id"], (
        "cùng một bản ghi"
    )
    assert after["kind"] == "member" and after["member_code"] == r.json()["member_code"]
    assert after["full_name"] == "QA Tên Hồ Sơ Tạm", "giữ họ tên của hồ sơ, không ghi đè"
    assert after["source"] == "self_register" and after["is_active"] is True
    assert after["version"] == before["version"] + 1, "version tăng khi nâng"
    detail = (await admin.get(f"{M}/{after['member_code']}")).json()
    assert detail["bookings"] >= 1, "giữ lịch sử đặt sân"
    assert (await admin.get(M, params={"q": phone})).json()["items"][0]["kind"] == "member"


async def test_r1_existing_club_member_is_only_linked_nothing_changes(admin, anon, cleanup):
    phone = random_phone()
    cleanup.append(phone)
    m = (
        await admin.post(
            M, json={"full_name": "QA HV Sân Tạo 3", "phone": phone, "tier": "Khá"}, headers=idem()
        )
    ).json()
    # tài khoản do sân tạo giữ SĐT → đăng ký bị E-AUTH-22; xóa tài khoản sân tạo để mô phỏng "hội viên quầy chưa có tài khoản"
    await x("DELETE FROM users WHERE phone=:p", p=phone)
    before = await customer_row(phone)
    r = await register(anon, phone, "Người Tự Đăng Ký")
    assert r.status_code == 201, r.text
    assert r.json()["member_code"] == m["member_code"] and r.json()["upgraded_from_temp"] is False
    after = await customer_row(phone)
    assert (
        after["id"],
        after["tier"],
        after["full_name"],
        after["source"],
        after["version"],
        after["member_code"],
    ) == (before["id"], "Khá", "QA HV Sân Tạo 3", "counter", before["version"], m["member_code"]), (
        "chỉ liên kết, không đổi gì"
    )


async def test_r1_inactive_member_links_but_locks_the_account(admin, anon, cleanup):
    phone = random_phone()
    cleanup.append(phone)
    m = (
        await admin.post(M, json={"full_name": "QA HV Ngừng", "phone": phone}, headers=idem())
    ).json()
    await x("DELETE FROM users WHERE phone=:p", p=phone)
    cur = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert (
        await admin.patch(
            f"{M}/{m['member_code']}",
            json={"is_active": False, "version": cur["version"]},
            headers=idem(),
        )
    ).status_code == 200
    r = await register(anon, phone, "Vào Khi Ngừng")
    assert r.status_code == 403 and err(r)["code"] == "E-AUTH-31", r.text
    assert not any(h.startswith("access_token=") for h in r.headers.get_list("set-cookie")), (
        "không cấp phiên"
    )
    u = (await q("SELECT is_active FROM users WHERE phone=:p", p=phone))[0]
    assert u["is_active"] is False, "tài khoản bị khóa theo quyết định 31/10"
    async with _client() as c:
        assert (await sign_in(c, phone, CUSTOMER_PASSWORD)).status_code in (401, 403)


async def test_r2_admin_add_member_on_a_temp_phone_still_e_mem_1(admin, cleanup):
    phone = random_phone()
    cleanup.append(phone)
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm R2", "phone": phone}, headers=idem()
        )
    ).status_code == 201
    r = await admin.post(M, json={"full_name": "QA Thêm Trùng", "phone": phone}, headers=idem())
    assert r.status_code == 409 and err(r)["code"] == "E-MEM-1"
    assert (await customer_row(phone))["kind"] == "temp"


# ============================================================ AC5/AC6 các chỗ xác minh khác


async def test_ac5_logged_in_unverified_account_verifying_in_booking_becomes_a_member(
    admin, cleanup
):
    phone = unique_phone()
    cleanup.append(phone)
    async with _client() as c:
        await db_account(c, phone, "Tự Xác Minh Khi Đặt")
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is False
        req = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        ver = await c.post(
            f"{WEB}/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
        )
        body = ver.json()
        assert (
            ver.status_code == 200
            and body["account_verified"] is True
            and body["became_member"] is True
        )
        assert re.fullmatch(r"HV\d{4,5}", body["member_code"]) and "phone_token" in body
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is True
        await age_otp_codes(phone)
        again = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        v2 = await c.post(
            f"{WEB}/phone/verify", json={"phone": phone, "otp": again.json()["test_otp"]}
        )
        assert v2.status_code == 200 and v2.json()["member_code"] == body["member_code"], (
            "xác minh lại không tạo hội viên thứ hai"
        )
        assert len(await q("SELECT 1 FROM customer WHERE phone=:p", p=phone)) == 1
    assert (await customer_row(phone))["source"] == "self_register"


async def test_ac5_guest_verifying_a_phone_does_not_become_a_member(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    req = await anon.post(f"{WEB}/phone/request", json={"phone": phone})
    ver = await anon.post(
        f"{WEB}/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
    )
    assert ver.status_code == 200 and ver.json().get("became_member") in (False, None)
    assert await customer_row(phone) is None and not await q(
        "SELECT 1 FROM users WHERE phone=:p", p=phone
    )


async def test_ac6_phone_verify_endpoint_applies_r1(cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    async with _client() as c:
        await db_account(c, phone, "Xác Minh Qua Hồ Sơ")
        req = await c.post(f"{API}/auth/phone/request", json={"phone": phone})
        assert req.status_code == 202, req.text
        ver = await c.post(
            f"{API}/auth/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
        )
        assert ver.status_code == 200, ver.text
        assert ver.json().get("became_member") is True and re.fullmatch(
            r"HV\d{4,5}", ver.json()["member_code"]
        )
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is True
    assert (await customer_row(phone))["kind"] == "member"


async def test_ac6_forgot_password_completion_applies_r1(cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    await db_account(None, phone, "Quên Mật Khẩu Hội Viên")
    assert await customer_row(phone) is None
    async with _client() as c:
        await age_otp_codes(phone)
        req = await c.post(f"{API}/auth/password-reset/request", json={"phone": phone})
        assert req.status_code == 202, req.text
        tok = await c.post(
            f"{API}/auth/password-reset/verify",
            json={"phone": phone, "otp": req.json()["test_otp"]},
        )
        assert tok.status_code == 200, tok.text
        done = await c.post(
            f"{API}/auth/password-reset/confirm",
            json={"reset_token": tok.json()["reset_token"], "password": "Moi-Mat-Khau-1"},
        )
        assert done.status_code == 204, done.text
    c = await customer_row(phone)
    assert c is not None and c["kind"] == "member", (
        "sau khi xác minh qua Quên mật khẩu thì là hội viên"
    )
    async with _client() as c2:
        r = await sign_in(c2, phone, "Moi-Mat-Khau-1")
        assert r.status_code == 200 and r.json()["account"]["is_member"] is True


# ============================================================ AC9 quản trị + AC10 nhật ký


async def test_ac9_admin_list_shows_source_and_counts_like_normal_members(admin, anon, cleanup):
    phone, club = unique_phone(), random_phone()
    cleanup += [phone, club]
    r = await register(anon, phone, "QA Tự Đăng Ký AC9")
    assert (
        await admin.post(M, json={"full_name": "QA Quầy AC9", "phone": club}, headers=idem())
    ).status_code == 201
    rows = {
        i["phone"]: i
        for i in (await admin.get(M, params={"size": 100})).json()["items"]
        if i["phone"] in (phone, club)
    }
    assert rows[phone]["source"] == "self_register" and rows[club]["source"] == "counter"
    assert rows[phone]["kind"] == "member" and rows[phone]["member_code"] == r.json()["member_code"]
    only_members = (await admin.get(M, params={"kind": "member", "q": phone})).json()
    assert only_members["total"] == 1 and only_members["counts"]["member"] >= 1


async def test_ac10_audit_rows_for_register_upgrade_and_release(admin, anon, cleanup):
    phone, tphone = unique_phone(), random_phone()
    cleanup += [phone, tphone]
    base = (await q("SELECT coalesce(max(id),0) AS i FROM audit_log"))[0]["i"]
    await db_account(None, phone, "Giữ Số Cũ")
    old_id = str((await q("SELECT id FROM users WHERE phone=:p", p=phone))[0]["id"])
    r = await register(anon, phone, "QA Tự Đăng Ký AC10")
    code = r.json()["member_code"]
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm AC10", "phone": tphone}, headers=idem()
        )
    ).status_code == 201
    async with _client() as c:
        r2 = await register(c, tphone, "QA Nâng AC10")
    code2 = r2.json()["member_code"]
    new = await q(
        "SELECT action, actor_type, entity_code, detail::text AS d FROM audit_log WHERE id > :b ORDER BY id",
        b=base,
    )
    by = {(n["action"], n["entity_code"]): n for n in new}
    assert ("member.self_register", code) in by, (
        "tạo hội viên mới ghi member.self_register với Mã HV"
    )
    assert ("member.auto_upgrade_temp", code2) in by, (
        "nâng hồ sơ tạm ghi member.auto_upgrade_temp với Mã HV"
    )
    assert ("auth.phone_released", old_id) in by, "gỡ SĐT ghi auth.phone_released"
    assert by[("auth.phone_released", old_id)]["actor_type"] == "system"
    for n in new:
        if n["action"] in (
            "member.self_register",
            "member.auto_upgrade_temp",
            "auth.phone_released",
        ):
            assert phone not in n["d"] and tphone not in n["d"], (n["action"], "SĐT được che")
            assert CUSTOMER_PASSWORD not in n["d"]


async def test_ac10_history_screen_shows_system_upgrade_and_phone_release_rows(
    admin, anon, cleanup
):
    tphone, phone = random_phone(), unique_phone()
    cleanup += [tphone, phone]
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm Lịch Sử", "phone": tphone}, headers=idem()
        )
    ).status_code == 201
    async with _client() as c:
        r = await register(c, tphone, "QA Nâng Lịch Sử")
    await db_account(None, phone, "Gỡ Lịch Sử")
    await register(anon, phone, "QA Gỡ SĐT Lịch Sử")
    items = (await admin.get(LOG, params={"size": 100, "actor": "system"})).json()["items"]
    labels = {i["action_label"] for i in items}
    assert "Tự nâng hồ sơ tạm thành hội viên" in labels, labels
    assert "Gỡ SĐT khỏi tài khoản chưa xác minh" in labels, labels
    up = next(
        i
        for i in items
        if i["action"] == "member.auto_upgrade_temp"
        and i["target"]["code"] == r.json()["member_code"]
    )
    assert up["actor"] == "system" and up["actor_label"] == "Hệ thống"
    allrows = (await admin.get(LOG, params={"size": 100})).json()["items"]
    assert not any(i["action"] == "member.self_register" for i in allrows), (
        "tự đăng ký không hiện ở màn (đã duyệt)"
    )


# ============================================================ SEC3 giới hạn OTP, SEC4, SEC5


async def test_sec3_resend_wait_hour_limit_and_attempt_limit(anon):
    phone = unique_phone()
    first = await anon.post(
        f"{REG}/request", json={"full_name": "A B", "phone": phone, "password": CUSTOMER_PASSWORD}
    )
    assert first.status_code == 202
    again = await anon.post(
        f"{REG}/request", json={"full_name": "A B", "phone": phone, "password": CUSTOMER_PASSWORD}
    )
    assert again.status_code == 429 and err(again)["code"] == "E-AUTH-13", "chờ 60 giây mới gửi lại"
    for _ in range(4):  # đủ 5 mã trong giờ
        await age_otp_codes(phone)
        r = await anon.post(
            f"{REG}/request",
            json={"full_name": "A B", "phone": phone, "password": CUSTOMER_PASSWORD},
        )
        assert r.status_code == 202
    await x(
        "UPDATE otp_codes SET created_at = now() - interval '5 minutes' WHERE phone=:p", p=phone
    )
    sixth = await anon.post(
        f"{REG}/request", json={"full_name": "A B", "phone": phone, "password": CUSTOMER_PASSWORD}
    )
    assert sixth.status_code == 429 and err(sixth)["code"] == "E-AUTH-13", "tối đa 5 mã mỗi giờ"


async def test_sec3_five_wrong_codes_kill_the_code(anon, cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    req = await request(anon, phone)
    otp = req.json()["test_otp"]
    bad = "000000" if otp != "000000" else "111111"
    codes = []
    for _ in range(5):
        r = await verify(anon, phone, bad)
        codes.append(err(r)["code"])
    assert codes[:4] == ["E-AUTH-14"] * 4 and codes[4] in ("E-AUTH-14", "E-AUTH-15"), codes
    r = await verify(anon, phone, otp)
    assert r.status_code == 400 and err(r)["code"] in ("E-AUTH-15", "E-AUTH-14"), (
        "mã đúng sau 5 lần sai cũng hết hiệu lực"
    )
    assert not await q("SELECT 1 FROM users WHERE phone=:p", p=phone)


async def test_sec3_ip_limit_on_request_is_10_per_hour(anon):
    for i in range(10):
        async with _client() as c:
            assert (await request(c, unique_phone())).status_code == 202, i
    async with _client() as c:
        r = await request(c, unique_phone())
        assert r.status_code == 429 and err(r)["code"] == "E-SEC-5"


async def test_sec4_temp_profile_is_not_upgraded_without_the_correct_otp(admin, anon, cleanup):
    phone = random_phone()
    cleanup.append(phone)
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm SEC4", "phone": phone}, headers=idem()
        )
    ).status_code == 201
    req = await request(anon, phone)
    for _ in range(3):
        assert (
            await verify(anon, phone, "000000" if req.json()["test_otp"] != "000000" else "111111")
        ).status_code == 400
    assert (await customer_row(phone))["kind"] == "temp", "chưa nhập đúng mã thì vẫn là hồ sơ tạm"
    assert not await q("SELECT 1 FROM users WHERE phone=:p", p=phone)
    # đặt online ẩn danh xác minh một SĐT khác không làm hồ sơ này đổi
    other = unique_phone()
    cleanup.append(other)
    r = await anon.post(f"{WEB}/phone/request", json={"phone": other})
    await anon.post(f"{WEB}/phone/verify", json={"phone": other, "otp": r.json()["test_otp"]})
    assert (await customer_row(phone))["kind"] == "temp"


async def test_sec5_concurrent_verifies_make_one_account_and_one_member_even_for_a_temp_profile(
    admin, cleanup
):
    phone = random_phone()
    cleanup.append(phone)
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm SEC5", "phone": phone}, headers=idem()
        )
    ).status_code == 201
    base = (await q("SELECT coalesce(max(id),0) AS i FROM audit_log"))[0]["i"]
    async with _client() as c0:
        otp = (await request(c0, phone)).json()["test_otp"]

    async def one():
        async with _client() as c:
            return (await verify(c, phone, otp)).status_code

    codes = sorted(await asyncio.gather(*[one() for _ in range(5)]))
    assert codes.count(201) == 1 and set(codes) <= {201, 400, 409}, codes
    assert len(await q("SELECT 1 FROM users WHERE phone=:p", p=phone)) == 1
    rows = await q("SELECT kind, member_code FROM customer WHERE phone=:p", p=phone)
    assert len(rows) == 1 and rows[0]["kind"] == "member"
    ups = await q(
        "SELECT count(*) AS n FROM audit_log WHERE id > :b AND action='member.auto_upgrade_temp' AND entity_code=:c",
        b=base,
        c=rows[0]["member_code"],
    )
    assert ups[0]["n"] == 1, "chỉ một lần nâng"


async def test_sec5_two_concurrent_registrations_for_different_new_phones_get_distinct_member_codes(
    cleanup,
):
    phones = [unique_phone() for _ in range(5)]
    cleanup += phones

    async def one(p):
        async with _client() as c:
            return await register(c, p, "Song Song Mã")

    res = await asyncio.gather(*[one(p) for p in phones])
    assert [r.status_code for r in res] == [201] * 5, [r.text for r in res if r.status_code != 201]
    codes = [r.json()["member_code"] for r in res]
    assert len(set(codes)) == 5, codes


# ============================================================ AC5 chi tiết: Google gắn / gộp / từ chối, vẫn cấp phone_token


async def google_client():
    from app.core.security import create_token

    row = await q(
        "INSERT INTO users (full_name, google_sub, google_email, role, is_active) VALUES ('QA Google', :g, 'qa-g@example.com', 'member', true) RETURNING id, token_version",
        g="qa-g-" + uuid.uuid4().hex[:10],
    )
    c = _client()
    c.cookies.set(
        "access_token", create_token(str(row[0]["id"]), "access", row[0]["token_version"])
    )
    return c, row[0]["id"]


async def booking_otp(c, phone):
    await age_otp_codes(phone)
    r = await c.post(f"{WEB}/phone/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    return await c.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]})


async def test_ac5_google_account_phone_owned_by_a_google_account_is_refused_but_booking_continues(
    cleanup,
):
    phone = unique_phone()
    cleanup.append(phone)
    owner, oid = await google_client()
    await x("UPDATE users SET phone=:p, phone_verified_at=now() WHERE id=:i", p=phone, i=oid)
    g, gid = await google_client()
    r = await booking_otp(g, phone)
    body = r.json()
    assert r.status_code == 200 and body["phone_token"], (
        "phone_token vẫn được cấp: lượt đặt không bị chặn"
    )
    assert (
        body["account_verified"] is False
        and body["became_member"] is False
        and body["reason"] == "E-AUTH-18"
    )
    assert (await q("SELECT phone FROM users WHERE id=:i", i=gid))[0]["phone"] is None, (
        "không gắn SĐT của người khác"
    )
    assert (await q("SELECT phone FROM users WHERE id=:i", i=oid))[0]["phone"] == phone, (
        "chủ SĐT không đổi"
    )


async def test_ac5_google_account_merges_into_the_plain_account_that_owns_the_phone(cleanup):
    phone = unique_phone()
    cleanup.append(phone)
    async with _client() as o:
        r0 = await register(o, phone, "Chủ Thường Gộp")
        code = r0.json()["member_code"]
    g, gid = await google_client()
    r = await booking_otp(g, phone)
    body = r.json()
    assert (
        r.status_code == 200 and body["account_merged"] is True and body["account_verified"] is True
    )
    assert body["member_code"] == code and body["phone_token"]
    me = await g.get(f"{API}/auth/me")
    assert (
        me.status_code == 200 and me.json()["phone"] == phone and me.json()["is_member"] is True
    ), "cookie đã đổi sang tài khoản đã gộp"
    assert len(await q("SELECT 1 FROM customer WHERE phone=:p", p=phone)) == 1, (
        "không tạo hồ sơ thứ hai"
    )


async def test_ac5_admin_phone_cannot_be_attached_but_token_is_granted():
    g, gid = await google_client()
    r = await booking_otp(g, settings.FIRST_ADMIN_PHONE)
    assert (
        r.status_code == 200
        and r.json()["phone_token"]
        and r.json()["reason"] in ("E-AUTH-17", "E-AUTH-18")
    )
    assert (await q("SELECT phone FROM users WHERE id=:i", i=gid))[0]["phone"] is None
    async with _client() as a:
        assert (
            await sign_in(a, settings.FIRST_ADMIN_PHONE, settings.FIRST_ADMIN_PASSWORD)
        ).status_code == 200, "Admin không bị đụng"


async def test_ac5_inactive_member_phone_reports_e_auth_31_locks_the_account_but_gives_token(
    admin, cleanup
):
    phone = random_phone()
    cleanup.append(phone)
    m = (
        await admin.post(M, json={"full_name": "QA Ngừng Web", "phone": phone}, headers=idem())
    ).json()
    await x("DELETE FROM users WHERE phone=:p", p=phone)
    cur = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert (
        await admin.patch(
            f"{M}/{m['member_code']}",
            json={"is_active": False, "version": cur["version"]},
            headers=idem(),
        )
    ).status_code == 200
    async with _client() as c:
        await db_account(c, phone, "Ngừng Xác Minh Web")
        r = await booking_otp(c, phone)
        assert (
            r.status_code == 200 and r.json()["phone_token"] and r.json()["reason"] == "E-AUTH-31"
        )
        assert (await c.get(f"{API}/auth/me")).status_code == 401, (
            "tài khoản bị khóa, phiên hết hiệu lực"
        )
    assert (await q("SELECT is_active FROM users WHERE phone=:p", p=phone))[0]["is_active"] is False


async def test_ac6_phone_verify_for_an_inactive_member_is_e_auth_31(admin, cleanup):
    phone = random_phone()
    cleanup.append(phone)
    m = (
        await admin.post(M, json={"full_name": "QA Ngừng Hồ Sơ", "phone": phone}, headers=idem())
    ).json()
    await x("DELETE FROM users WHERE phone=:p", p=phone)
    cur = (await admin.get(f"{M}/{m['member_code']}")).json()
    await admin.patch(
        f"{M}/{m['member_code']}",
        json={"is_active": False, "version": cur["version"]},
        headers=idem(),
    )
    async with _client() as c:
        await db_account(c, phone, "Ngừng Hồ Sơ")
        req = await c.post(f"{API}/auth/phone/request", json={"phone": phone})
        assert req.status_code == 202, req.text
        ver = await c.post(
            f"{API}/auth/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
        )
        assert ver.status_code == 403 and err(ver)["code"] == "E-AUTH-31", ver.text

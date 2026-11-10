# ruff: noqa: E501
"""QA T-016 đợt 1 (khu hội viên: "Hồ sơ của tôi" + ảnh đại diện), viết từ spec `T-016-khu-hoi-vien.md`
(gồm mục "Sửa đổi 30/10" – nền PR #21, liên kết theo SĐT) và ADR-009. AC4 đã bỏ.

Quy ước như test_qa_T-015: không có dấu xfail = đạt; điểm lệch spec là ``xfail(strict)`` kèm nhãn
[BUG] (lỗi chức năng/bảo mật thật) hoặc [OPEN] (chờ ARCHITECT hỏi người dùng).
"""

import asyncio
import io
import re
import uuid

import pytest
from PIL import Image
from sqlalchemy import text

from app.core.db import engine
from tests.conftest import API, _client, idem, sign_in, unique_phone
from tests.helpers_booking import book, new_court, safe_hour
from tests.helpers_web import WEB
from tests.qa_accounts import db_account

MA = f"{API}/member-area"
M = f"{API}/members"
PW = "Hv-Moi-Pass-1"


def deviation(kind: str, code: str, why: str):
    return pytest.mark.xfail(strict=True, reason=f"[{kind}] {code}: {why}")


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def err(r) -> dict:
    return r.json()["detail"]


@pytest.fixture
async def made():
    phones: list[str] = []
    yield phones
    if phones:
        await x("DELETE FROM customer WHERE phone = ANY(:p)", p=phones)
        await x("DELETE FROM users WHERE phone = ANY(:p)", p=phones)
        await x("DELETE FROM customer_avatar WHERE customer_id NOT IN (SELECT id FROM customer)")


def tag() -> str:
    return "QAT16" + uuid.uuid4().hex[:6].upper()


async def add_member(admin, made, **fields) -> dict:
    phone = fields.pop("phone", None) or unique_phone()
    made.append(phone)
    body = {"full_name": f"{tag()} Hội Viên", "phone": phone, **fields}
    r = await admin.post(f"{M}", json=body, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


async def admin_patch(admin, code: str, body: dict):
    """Sửa hội viên ở quản trị (T-020 AC4: bắt buộc `version`) – đọc version hiện tại rồi gửi."""
    cur = (await admin.get(f"{M}/{code}")).json()
    return await admin.patch(
        f"{M}/{code}", json={**body, "version": cur["version"]}, headers=idem()
    )


async def member_login(admin, made, *, change_password: bool = True, **fields):
    """Sân tạo hội viên -> tài khoản (mật khẩu = SĐT) -> đăng nhập, đổi mật khẩu lần đầu."""
    m = await add_member(admin, made, **fields)
    c = _client()
    assert (await sign_in(c, m["phone"], m["phone"])).status_code == 200
    if change_password:
        r = await c.post(f"{API}/auth/password/change", json={"new_password": PW}, headers=idem())
        assert r.status_code == 200, r.text
    return c, m


async def me(c):
    r = await c.get(f"{MA}/me")
    assert r.status_code == 200, r.text
    return r.json()


def put_body(cur: dict, **over) -> dict:
    body = {
        "full_name": cur["full_name"],
        "nickname": cur["nickname"],
        "email": cur["email"],
        "tier": cur["tier"],
        "racket": cur["racket"],
        "show_on_records": cur["show_on_records"],
        "version": cur["version"],
    }
    return {**body, **over}


async def save(c, cur: dict, **over):
    return await c.put(f"{MA}/me", json=put_body(cur, **over), headers=idem())


def png(size=(600, 400), color=(10, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


async def upload(c, data: bytes, *, name="a.png", ctype="image/png", cx=0, cy=0, size=300):
    return await c.put(
        f"{MA}/me/avatar",
        files={"file": (name, data, ctype)},
        data={"crop_x": cx, "crop_y": cy, "crop_size": size},
        headers=idem(),
    )


# ============================================================ AC1–AC3, SEC3 liên kết & quyền vào


async def test_ac2_anonymous_admin_staff_are_rejected(anon, admin, staff):
    assert (await anon.get(f"{MA}/me")).status_code == 401
    assert (await admin.get(f"{MA}/me")).status_code in (401, 403)
    assert (await staff.get(f"{MA}/me")).status_code in (401, 403)
    for c in (anon, admin, staff):
        r = await c.put(f"{MA}/me", json={"full_name": "A"}, headers=idem())
        assert r.status_code in (401, 403, 422) and r.status_code != 200


async def test_ac2_plain_customer_not_linked_gets_e_hv_8(customer):
    r = await customer.get(f"{MA}/me")
    assert r.status_code == 403 and err(r)["code"] == "E-HV-8"
    assert (await customer.get(f"{API}/auth/me")).json()["is_member"] is False
    for call in (
        customer.put(
            f"{MA}/me",
            json={"full_name": "A", "tier": None, "show_on_records": False, "version": 1},
            headers=idem(),
        ),
        customer.delete(f"{MA}/me/avatar", headers=idem()),
    ):
        r = await call
        assert r.status_code == 403 and err(r)["code"] == "E-HV-8", r.text
    r = await upload(customer, png())
    assert r.status_code == 403 and err(r)["code"] == "E-HV-8"


async def test_ac1_club_created_account_is_linked_after_changing_password(admin, made):
    c, m = await member_login(admin, made)
    info = await me(c)
    assert info["member_code"] == m["member_code"] and info["phone"] == m["phone"]
    assert (await c.get(f"{API}/auth/me")).json()["is_member"] is True


async def test_ac1_first_login_needs_password_change_first(admin, made):
    c, m = await member_login(admin, made, change_password=False)
    r = await c.get(f"{MA}/me")
    assert r.status_code == 403 and err(r)["code"] == "E-AUTH-25", "đổi mật khẩu ban đầu trước"
    r = await c.put(
        f"{MA}/me",
        json={"full_name": "A", "tier": None, "show_on_records": False, "version": 1},
        headers=idem(),
    )
    assert r.status_code == 403 and err(r)["code"] == "E-AUTH-25"
    ok = await c.post(f"{API}/auth/password/change", json={"new_password": PW}, headers=idem())
    assert ok.status_code == 200 and ok.json()["is_member"] is True, ok.text
    assert (await c.get(f"{MA}/me")).status_code == 200


async def test_ac1_initial_password_older_than_3_days_is_blocked_e_auth_30(admin, made):
    c, m = await member_login(admin, made, change_password=False)
    await x(
        "UPDATE users SET member_account_at = now() - interval '4 days' WHERE phone=:p",
        p=m["phone"],
    )
    r = await c.get(f"{MA}/me")
    assert r.status_code == 403 and err(r)["code"] == "E-AUTH-30", r.text


async def test_ac1_unverified_account_needs_otp_to_link_to_a_club_member(admin, made):
    """Tài khoản đời cũ (SĐT chưa xác minh) trùng SĐT hội viên quầy tạo → chưa liên kết; xác minh OTP rồi mới vào."""
    phone = unique_phone()
    made.append(phone)
    async with _client() as c:
        await db_account(c, phone, "Khách Đăng Ký Trước", "Tu-Dang-Ky-1")
        await add_member(admin, made, phone=phone)
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is False
        r = await c.get(f"{MA}/me")
        assert r.status_code == 403 and err(r)["code"] == "E-HV-8", "chưa xác minh SĐT → không vào"
        req = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        assert req.status_code == 202, req.text
        ver = await c.post(
            f"{WEB}/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
        )
        assert ver.status_code == 200 and ver.json()["account_verified"] is True
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is True
        assert (await c.get(f"{MA}/me")).status_code == 200


async def test_ac1_t021_temp_profile_is_upgraded_when_the_owner_verifies_the_phone(admin, made):
    """T-021 R1: hồ sơ tạm + chủ SĐT tự xác minh OTP → nâng lên hội viên trên cùng dòng, giữ lịch sử."""
    phone = unique_phone()
    made.append(phone)
    t = await admin.post(
        f"{M}/temp", json={"full_name": f"{tag()} Tạm", "phone": phone}, headers=idem()
    )
    assert t.status_code == 201
    before = (await q("SELECT id, public_id, kind FROM customer WHERE phone=:p", p=phone))[0]
    assert before["kind"] == "temp"
    async with _client() as c:
        await db_account(c, phone, "Có hồ sơ tạm", "Tu-Dang-Ky-1")
        r = await c.get(f"{MA}/me")
        assert r.status_code == 403 and err(r)["code"] == "E-HV-8", (
            "chưa xác minh OTP: chưa phải hội viên"
        )
        req = await c.post(f"{WEB}/phone/request", json={"phone": phone})
        ver = await c.post(
            f"{WEB}/phone/verify", json={"phone": phone, "otp": req.json()["test_otp"]}
        )
        assert ver.status_code == 200 and ver.json()["became_member"] is True, ver.text
        assert (await c.get(f"{API}/auth/me")).json()["is_member"] is True
        assert (await c.get(f"{MA}/me")).status_code == 200
    after = (await q("SELECT id, public_id, kind FROM customer WHERE phone=:p", p=phone))[0]
    assert after["id"] == before["id"] and after["public_id"] == before["public_id"]
    assert after["kind"] == "member", "nâng trên cùng dòng, không tạo dòng mới"


async def test_ac1_is_member_in_sign_in_response(admin, made):
    c, m = await member_login(admin, made)
    async with _client() as fresh:
        r = await sign_in(fresh, m["phone"], PW)
        assert r.status_code == 200 and r.json()["account"]["is_member"] is True, r.text


async def test_oq9_inactive_member_web_account_is_locked_user_decision_31_10(admin, made):
    """Người dùng chốt 31/10 (T-16-2): hội viên Ngừng thì tài khoản web bị khóa, không vào khu hội viên."""
    c, m = await member_login(admin, made)
    r = await admin_patch(admin, m["member_code"], {"is_active": False})
    assert r.status_code == 200, r.text
    r = await c.get(f"{MA}/me")
    assert r.status_code == 401, "phiên đang mở bị thu hồi"
    async with _client() as fresh:
        assert (await sign_in(fresh, m["phone"], PW)).status_code in (401, 403), (
            "không đăng nhập lại được"
        )
    # Hoạt động lại thì mở khóa
    assert (await admin_patch(admin, m["member_code"], {"is_active": True})).status_code == 200
    async with _client() as again:
        assert (await sign_in(again, m["phone"], PW)).status_code == 200
        assert (await again.get(f"{MA}/me")).status_code == 200


# ============================================================ AC7–AC8 xem hồ sơ


async def test_ac7_ac8_profile_shape_defaults_and_no_store(admin, made):
    c, m = await member_login(admin, made, gender="male", tier="Khá")
    r = await c.get(f"{MA}/me")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    d = r.json()
    assert d["member_code"] == m["member_code"] and re.fullmatch(r"HV\d{4,5}", d["member_code"])
    assert d["short_name"] == d["full_name"].split()[-1]
    assert d["nickname"] is None and d["email"] is None and d["racket"] is None
    assert d["tier"] == "Khá" and d["show_on_records"] is False, "OQ-2: mặc định Tắt"
    assert d["avatar_url"] is None and d["record_kmh"] is None
    assert d["phone"] == m["phone"], "chính chủ thấy SĐT đầy đủ"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d["joined_at"]) and isinstance(d["version"], int)


async def test_ac7_default_tier_null_is_allowed_to_stay_null(admin, made):
    c, _ = await member_login(admin, made)  # PR: tạo mới tier null
    cur = await me(c)
    assert cur["tier"] is None
    r = await save(c, cur, nickname="Gió")
    assert r.status_code == 200 and r.json()["tier"] is None and r.json()["nickname"] == "Gió"


# ============================================================ AC11–AC13 sửa hồ sơ


async def test_ac12_all_invalid_fields_reported_once_and_nothing_saved(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    r = await save(
        c,
        cur,
        full_name=" ",
        nickname="x" * 21,
        email="khong-hop-le",
        tier="Hạng không có",
        racket="Vợt mới không được thêm " + tag(),
    )
    assert r.status_code == 422, r.text
    fields = {f["field"]: f["code"] for f in err(r)["fields"]}
    assert fields.get("full_name") == "E-HV-1" and fields.get("nickname") == "E-HV-1"
    assert fields.get("email") == "E-HV-10" and fields.get("tier") == "E-HV-1", fields  # T-042
    again = await me(c)
    assert again == cur, "có lỗi thì không lưu ô nào"
    listed = (await c.get(f"{API}/rackets")).json()
    assert not any(i["name"].startswith("Vợt mới không được thêm") for i in listed), (
        "không thêm vợt khi lỗi"
    )


@pytest.mark.parametrize(
    ("over", "field", "code"),
    [
        ({"full_name": "x" * 101}, "full_name", "E-HV-1"),
        ({"nickname": "y" * 21}, "nickname", "E-HV-1"),
        ({"email": "a" * 250 + "@x.vn"}, "email", "E-HV-10"),
        ({"email": "thieu-a-cong.com"}, "email", "E-HV-10"),
        # T-042: Hạng tự chọn trong 8 bậc hoặc null; giá trị lạ -> E-HV-1 (không còn E-HV-14)
        ({"tier": "Vàng"}, "tier", "E-HV-1"),
        ({"tier": ""}, "tier", "E-HV-1"),
        ({"tier": "bán chuyên"}, "tier", "E-HV-1"),
    ],
)
async def test_ac12_field_rules(admin, made, over, field, code):
    c, _ = await member_login(admin, made, tier="Khá")
    r = await save(c, await me(c), **over)
    assert r.status_code == 422, (over, r.text)
    assert any(f["field"] == field and f["code"] == code for f in err(r)["fields"]), r.text


async def test_ac12_boundaries_accepted(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    r = await save(c, cur, full_name=("Ngô " * 30)[:100].strip(), nickname="n" * 20)
    assert r.status_code == 200, r.text
    r = await save(c, r.json(), email="x" * 64 + "@" + "d" * 63 + ".com")  # ≤ 254
    assert r.status_code in (200, 422)
    long_ok = await save(c, await me(c), email="ten.rat.dai@example.com")
    assert long_ok.status_code == 200


async def test_ac12_email_unique_case_insensitive_and_own_email_ok(admin, made):
    a, _ = await member_login(admin, made)
    b, _ = await member_login(admin, made)
    mail = f"{tag().lower()}@Example.com"
    ra = await save(a, await me(a), email=mail)
    assert ra.status_code == 200, ra.text
    rb = await save(b, await me(b), email=mail.upper())
    assert rb.status_code == 422 and err(rb)["fields"][0]["code"] == "E-HV-11", rb.text
    again = await save(a, ra.json())  # chính chủ gửi lại email của mình → không báo trùng
    assert again.status_code == 200
    cleared = await save(a, again.json(), email="")
    assert cleared.status_code == 200 and cleared.json()["email"] is None
    assert (await save(b, await me(b), email=mail)).status_code == 200, "email được giải phóng"


async def test_ac13_success_bumps_version_syncs_name_and_is_visible_elsewhere(admin, made):
    c, m = await member_login(admin, made, tier="Trung bình")
    cur = await me(c)
    new_name = f"{tag()} Nguyễn Văn Mới"
    r = await save(c, cur, full_name=new_name, nickname="Gió", tier="Khá", show_on_records=True)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (
        d["full_name"] == new_name
        and d["short_name"] == "Mới"
        and d["version"] == cur["version"] + 1
    )
    assert d["tier"] == "Khá" and d["show_on_records"] is True  # T-042: hội viên tự đổi Hạng
    assert (await q("SELECT full_name FROM users WHERE phone=:p", p=m["phone"]))[0][
        "full_name"
    ] == new_name
    assert (await c.get(f"{API}/auth/me")).json()["full_name"] == new_name, (
        "header public dùng tên mới"
    )
    listed = (await admin.get(M, params={"q": m["member_code"]})).json()["items"][0]
    assert listed["full_name"] == new_name and listed["tier"] == "Khá", (
        "màn quản trị thấy giá trị mới"
    )


async def test_ac13_name_change_renames_existing_bookings(admin, made):
    c, m = await member_login(admin, made)
    h = await safe_hour()
    court = await new_court(admin)
    b = await book(admin, court["code"], h, h + 1, customer={"member_code": m["member_code"]})
    if b.status_code != 201:
        pytest.skip("cannot book at the counter right now")
    code = b.json()["code"] if "code" in b.json() else b.json()["bookings"][0]["code"]
    new_name = f"{tag()} Đổi Tên"
    assert (await save(c, await me(c), full_name=new_name)).status_code == 200
    item = (await admin.get(f"{API}/booking/items/{code}")).json()
    assert (
        item["customer"]["name"] == new_name
        if "customer" in item
        else item.get("customer_name") == new_name
    )


async def test_ac12_no_change_does_not_save_or_audit(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    before = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.self_update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    r = await save(c, cur)
    assert r.status_code == 200 and r.json()["version"] == cur["version"]
    r = await save(c, cur, full_name=f"  {cur['full_name']}  ")  # chỉ khác khoảng trắng
    assert r.status_code == 200 and r.json()["version"] == cur["version"]
    after = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.self_update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    assert after == before


async def test_ac12_unknown_or_forbidden_fields_are_rejected(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    for extra in (
        {"phone": unique_phone()},
        {"member_code": "HV9999"},
        {"customer_id": 1},
        {"is_active": False},
    ):
        r = await c.put(f"{MA}/me", json={**put_body(cur), **extra}, headers=idem())
        assert r.status_code == 422, (extra, r.text)
    assert (await me(c))["phone"] == m["phone"] == cur["phone"]


async def test_ac13_racket_is_free_text_normalised_and_never_added_to_the_catalogue(admin, made):
    """T-033: ô chữ tự nhập – cắt 2 đầu, gộp khoảng trắng, tối đa 100, rỗng → null; không tự thêm vào danh mục vợt."""
    c, _ = await member_login(admin, made, tier="Khá")
    name = f"QA Vợt {tag()}"
    before = len((await c.get(f"{API}/rackets")).json())
    r = await save(c, await me(c), racket=f"  {name.replace(' ', '   ')}  ")
    assert r.status_code == 200 and r.json()["racket"] == name, (
        "chuẩn hóa: cắt 2 đầu, gộp khoảng trắng"
    )
    listed = (await c.get(f"{API}/rackets")).json()
    assert not any(i["name"].lower() == name.lower() for i in listed), "không thêm vào danh mục"
    assert len(listed) == before
    other, _ = await member_login(admin, made, tier="Khá")
    r2 = await save(other, await me(other), racket=name.upper())
    assert r2.status_code == 200 and r2.json()["racket"] == name.upper(), (
        "giữ nguyên chữ người nhập"
    )
    assert len((await other.get(f"{API}/rackets")).json()) == before
    blank = await save(c, r.json(), racket="   ")
    assert blank.status_code == 200 and blank.json()["racket"] is None, (
        "rỗng / toàn khoảng trắng → null"
    )
    cleared = await save(c, blank.json(), racket=None)
    assert cleared.status_code == 200 and cleared.json()["racket"] is None
    ok100 = await save(c, cleared.json(), racket="z" * 100)
    assert ok100.status_code == 200 and ok100.json()["racket"] == "z" * 100, "100 ký tự là hợp lệ"
    r3 = await save(c, ok100.json(), racket="z" * 101)
    assert r3.status_code == 422 and any(f["field"] == "racket" for f in err(r3)["fields"])


async def test_rackets_catalogue_access_rules(admin, made, customer, anon):
    c, _ = await member_login(admin, made)
    assert (await c.get(f"{API}/rackets")).status_code == 200
    assert (await customer.get(f"{API}/rackets")).status_code == 403
    assert (await anon.get(f"{API}/rackets")).status_code == 401
    r = await c.post(f"{API}/rackets", json={"name": f"QA {tag()}"}, headers=idem())
    assert r.status_code in (401, 403), "khách chỉ đọc danh mục; thêm vợt qua lưu hồ sơ"
    r = await c.get(f"{API}/rackets", params={"all": "true"})
    assert r.status_code == 200 and all(i.get("is_active", True) for i in r.json()), (
        "không thấy vợt ẩn"
    )


# ============================================================ AC14 khóa lạc quan


async def test_ac14_second_tab_with_stale_version_gets_e_hv_12(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    assert (await save(c, cur, nickname="Một")).status_code == 200
    stale = await save(c, cur, nickname="Hai")
    assert stale.status_code == 409 and err(stale)["code"] == "E-HV-12", stale.text
    assert (await me(c))["nickname"] == "Một", "không ghi đè"


async def test_ac14_admin_edit_after_open_blocks_the_members_save(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    r = await admin_patch(admin, m["member_code"], {"tier": "Chuyên nghiệp"})
    assert r.status_code == 200, r.text
    stale = await save(c, cur, nickname="Ghi đè")
    assert stale.status_code == 409 and err(stale)["code"] == "E-HV-12", stale.text
    assert (await admin.get(f"{M}/{m['member_code']}")).json()["tier"] == "Chuyên nghiệp"


async def test_ac14_concurrent_saves_one_wins(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    res = await asyncio.gather(*[save(c, cur, nickname=f"Song{i}") for i in range(4)])
    codes = sorted(r.status_code for r in res)
    assert codes.count(200) == 1 and set(codes) <= {200, 409}, codes


# ============================================================ AC17 audit


async def test_ac17_audit_before_after_masked_email_and_actor(admin, made):
    c, m = await member_login(admin, made, tier="Trung bình")
    cur = await me(c)
    mail = f"{tag().lower()}@gmail.com"
    r = await save(c, cur, email=mail, nickname="Gió", tier="Khá", racket=f"QA Vợt {tag()}")
    assert r.status_code == 200, r.text
    row = (
        await q(
            "SELECT actor_type, actor_label, detail::text AS d FROM audit_log WHERE action='member.self_update' AND entity_code=:c ORDER BY id DESC LIMIT 1",
            c=m["member_code"],
        )
    )[0]
    assert row["actor_label"] == f"Hội viên (tự sửa) · {m['member_code']}", row["actor_label"]
    assert "Gió" in row["d"] and "QA Vợt" in row["d"], "giá trị trước → sau"
    assert "Trình độ" not in row["d"], "T-042: Hạng có dòng audit riêng, không lặp ở self_update"
    assert mail not in row["d"] and re.search(r"[a-z0-9]\*\*\*@gmail\.com", row["d"]), "email che"
    assert m["phone"] not in row["d"]


async def test_ac17_new_racket_writes_no_racket_row_or_audit_and_audit_keeps_before_after(
    admin, made
):
    """T-033 AC3 + AC5: vợt lạ không sinh dòng `racket` / audit `racket.create`; audit sửa hồ sơ vẫn ghi trước → sau."""
    c, m = await member_login(admin, made, tier="Khá")
    base = (await q("SELECT coalesce(max(id), 0) AS i FROM audit_log"))[0]["i"]
    rows_before = (await q("SELECT count(*) AS n FROM racket"))[0]["n"]
    first, second = f"QA Vợt {tag()}", f"QA Vợt {tag()}"
    r1 = await save(c, await me(c), racket=first)
    assert r1.status_code == 200
    assert (await save(c, r1.json(), racket=second)).status_code == 200
    assert not await q("SELECT 1 FROM audit_log WHERE id > :b AND action='racket.create'", b=base)
    assert (await q("SELECT count(*) AS n FROM racket"))[0]["n"] == rows_before, (
        "không có dòng racket mới"
    )
    row = (
        await q(
            "SELECT detail::text AS d FROM audit_log WHERE action='member.self_update' AND entity_code=:c AND id > :b ORDER BY id DESC LIMIT 1",
            c=m["member_code"],
            b=base,
        )
    )[0]
    assert first in row["d"] and second in row["d"], "audit ghi vợt trước → sau"


async def test_ac17_failed_save_writes_no_audit(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    n0 = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.self_update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    assert (await save(c, await me(c), full_name="")).status_code == 422
    stale_cur = await me(c)
    await save(c, stale_cur, nickname="A")
    assert (await save(c, stale_cur, nickname="B")).status_code == 409
    n1 = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.self_update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    assert n1 == n0 + 1, "chỉ lần lưu thành công được ghi"


# ============================================================ SEC1 IDOR + SEC4 Origin / no-store


async def test_sec1_every_call_is_bound_to_the_session_not_to_parameters(admin, made):
    a, ma = await member_login(admin, made, tier="Khá")
    b, mb = await member_login(admin, made, tier="Khá")
    got = await a.get(
        f"{MA}/me", params={"id": 1, "member_code": mb["member_code"], "phone": mb["phone"]}
    )
    assert got.json()["member_code"] == ma["member_code"] and mb["phone"] not in got.text
    cur_b = await me(b)
    r = await a.put(
        f"{MA}/me",
        json={**put_body(await me(a)), "nickname": "Của A"},
        params={"member_code": mb["member_code"]},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["member_code"] == ma["member_code"]
    assert (await me(b)) == cur_b, "hồ sơ B không đổi"
    assert (await a.get(f"{MA}/me/../me")).status_code in (200, 404)
    assert (await a.get(f"{M}/{mb['member_code']}")).status_code in (401, 403), (
        "không có API quản trị"
    )
    assert (await a.get(M)).status_code in (401, 403)


async def test_sec1_avatar_upload_and_delete_only_touch_own_profile(admin, made):
    a, ma = await member_login(admin, made)
    b, mb = await member_login(admin, made)
    assert (await upload(a, png())).status_code == 200
    assert (await me(b))["avatar_url"] is None
    assert (await b.delete(f"{MA}/me/avatar", headers=idem())).status_code == 204
    assert (await me(a))["avatar_url"] is not None, "xóa của B không đụng ảnh của A"


async def test_sec4_writes_need_origin_and_responses_are_not_cached(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    evil = {"Origin": "https://evil.example", **idem()}
    r = await c.put(f"{MA}/me", json=put_body(cur, nickname="Hack"), headers=evil)
    assert r.status_code == 403 and err(r)["code"] == "E-SEC-1"
    r = await c.put(
        f"{MA}/me/avatar",
        files={"file": ("a.png", png(), "image/png")},
        data={"crop_x": 0, "crop_y": 0, "crop_size": 100},
        headers=evil,
    )
    assert r.status_code == 403 and err(r)["code"] == "E-SEC-1"
    assert (await c.delete(f"{MA}/me/avatar", headers=evil)).status_code == 403
    assert (await me(c))["nickname"] is None
    ok = await save(c, cur, nickname="Hợp lệ")
    assert "no-store" in ok.headers["cache-control"]


async def test_sec5_email_only_visible_to_the_owner(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    mail = f"{tag().lower()}@example.com"
    assert (await save(c, await me(c), email=mail)).status_code == 200
    # Người dùng chốt 2026-11-10: bỏ SEC5 cho màn chi tiết quản trị – chi tiết trả email đầy đủ,
    # danh sách (và các nơi khác) vẫn không có email
    listing = (await admin.get(M, params={"q": m["member_code"]})).text
    detail = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert mail not in listing, "danh sách quản trị không trả email của hội viên"
    assert detail["email"] == mail
    async with _client() as anon_c:
        assert mail not in (await anon_c.get(f"{MA}/avatars/1")).text


# ============================================================ AC18–AC19, SEC2 ảnh đại diện


async def test_ac18_upload_crop_serve_and_cache_headers(admin, made):
    c, m = await member_login(admin, made)
    r = await upload(c, png((800, 600)), cx=100, cy=0, size=600)
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert re.search(r"/member-area/avatars/\d+\?v=[0-9a-f]+$", url), url
    assert (await me(c))["avatar_url"] == url
    async with _client() as anon_c:  # công khai
        img = await anon_c.get(
            url.replace("/api/v1", API.replace("http://testserver", ""))
            if url.startswith("/api/v1")
            else url
        )
        assert img.status_code == 200, img.status_code
        assert img.headers["content-type"] == "image/webp"
        assert img.headers["x-content-type-options"] == "nosniff"
        assert (
            "max-age=31536000" in img.headers["cache-control"]
            and "immutable" in img.headers["cache-control"]
        )
        etag = img.headers["etag"]
        cached = await anon_c.get(url, headers={"If-None-Match": etag})
        assert cached.status_code == 304
        out = Image.open(io.BytesIO(img.content))
        assert out.format == "WEBP" and out.size[0] == out.size[1] <= 512, out.size


async def test_ac19_stored_bytes_are_reencoded_webp_without_metadata(admin, made):
    c, m = await member_login(admin, made)
    base = Image.new("RGB", (700, 700), (200, 30, 30))
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "QA-Camera"  # Make
    exif[0x0112] = 1
    base.save(buf, "JPEG", exif=exif.tobytes(), comment=b"secret-gps-comment")
    r = await upload(c, buf.getvalue(), name="a.jpg", ctype="image/jpeg", size=600)
    assert r.status_code == 200, r.text
    row = (
        await q(
            "SELECT content_type, bytes, etag FROM customer_avatar ORDER BY updated_at DESC LIMIT 1"
        )
    )[0]
    data = bytes(row["bytes"])
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP" and row["content_type"] == "image/webp"
    assert b"QA-Camera" not in data and b"secret-gps-comment" not in data and b"Exif" not in data
    assert len(data) < len(buf.getvalue()) * 3, "ảnh ≤ 512 px"


async def test_ac18_formats_accepted_png_jpeg_webp(admin, made):
    c, _ = await member_login(admin, made)
    for fmt, ctype in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
        buf = io.BytesIO()
        Image.new("RGB", (300, 300), (5, 100, 50)).save(buf, fmt)
        r = await upload(c, buf.getvalue(), name=f"a.{fmt.lower()}", ctype=ctype, size=200)
        assert r.status_code == 200, (fmt, r.text)


@pytest.mark.parametrize(
    ("label", "data", "name", "ctype"),
    [
        (
            "svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "a.svg",
            "image/svg+xml",
        ),
        (
            "svg-as-png",
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            "a.png",
            "image/png",
        ),
        (
            "html-as-png",
            b"<html><script>alert(document.cookie)</script></html>",
            "a.png",
            "image/png",
        ),
        (
            "gif",
            b"GIF89a"
            + b"\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            "a.gif",
            "image/gif",
        ),
        ("empty", b"", "a.png", "image/png"),
        ("truncated-png", png()[:60], "a.png", "image/png"),
        ("exe-as-jpg", b"MZ\x90\x00" + b"\x00" * 200, "a.jpg", "image/jpeg"),
        ("text", b"just text", "a.webp", "image/webp"),
    ],
)
async def test_sec2_malicious_or_wrong_files_are_rejected(admin, made, label, data, name, ctype):
    c, _ = await member_login(admin, made)
    r = await upload(c, data, name=name, ctype=ctype, size=1)
    assert r.status_code == 422 and err(r)["code"] == "E-HV-13", (
        label,
        r.status_code,
        r.text[:150],
    )
    assert (await me(c))["avatar_url"] is None


async def test_sec2_polyglot_png_with_html_tail_is_cleaned(admin, made):
    c, _ = await member_login(admin, made)
    evil = png((300, 300)) + b"<script>alert(1)</script>GIF89a"
    r = await upload(c, evil, size=200)
    if r.status_code == 200:
        row = (await q("SELECT bytes FROM customer_avatar ORDER BY updated_at DESC LIMIT 1"))[0]
        assert b"<script>" not in bytes(row["bytes"]) and bytes(row["bytes"])[8:12] == b"WEBP"
    else:
        assert r.status_code == 422 and err(r)["code"] == "E-HV-13"


async def test_sec2_png_with_embedded_html_chunk_is_stripped(admin, made):
    import struct
    import zlib

    c, _ = await member_login(admin, made)
    base = png((300, 300))
    chunk = b"tEXt" + b"Comment\x00<script>alert(1)</script>"
    crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    evil = base[:33] + struct.pack(">I", len(chunk) - 4) + chunk + crc + base[33:]
    r = await upload(c, evil, size=200)
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        row = (await q("SELECT bytes FROM customer_avatar ORDER BY updated_at DESC LIMIT 1"))[0]
        assert b"<script>" not in bytes(row["bytes"])


async def test_sec2_pixel_bomb_over_40mp_is_rejected(admin, made):
    c, _ = await member_login(admin, made)
    buf = io.BytesIO()
    Image.new("L", (7000, 7000)).save(buf, "PNG", optimize=False, compress_level=9)
    data = buf.getvalue()
    assert len(data) < 5 * 1024 * 1024, "bom ảnh nhỏ gọn nhưng 49 megapixel"
    r = await upload(c, data, size=100)
    assert r.status_code == 422 and err(r)["code"] == "E-HV-13", r.text[:160]
    assert (await me(c))["avatar_url"] is None


async def test_sec2_extreme_aspect_ratio_image_is_safe(admin, made):
    c, _ = await member_login(admin, made)
    buf = io.BytesIO()
    Image.new("RGB", (1, 20000), (1, 2, 3)).save(buf, "PNG")
    r = await upload(c, buf.getvalue(), size=1)
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        row = (await q("SELECT bytes FROM customer_avatar ORDER BY updated_at DESC LIMIT 1"))[0]
        assert bytes(row["bytes"])[8:12] == b"WEBP"


async def test_ac18_file_over_5mb_is_rejected(admin, made):
    c, _ = await member_login(admin, made)
    big = png((300, 300)) + b"\x00" * (5 * 1024 * 1024 + 10)
    r = await upload(c, big, size=100)
    assert r.status_code in (413, 422), r.status_code
    if r.status_code == 422:
        assert err(r)["code"] == "E-HV-13"
    assert (await me(c))["avatar_url"] is None


@pytest.mark.parametrize(
    "crop",
    [(-1, 0, 100), (0, -1, 100), (0, 0, 0), (0, 0, -5), (500, 0, 200), (0, 300, 200), (0, 0, 5000)],
)
async def test_ac19_invalid_crop_region_is_rejected(admin, made, crop):
    c, _ = await member_login(admin, made)
    r = await upload(c, png((600, 400)), cx=crop[0], cy=crop[1], size=crop[2])
    assert r.status_code == 422, (crop, r.status_code, r.text[:150])
    assert (await me(c))["avatar_url"] is None


async def test_ac18_missing_form_fields_are_422(admin, made):
    c, _ = await member_login(admin, made)
    r = await c.put(
        f"{MA}/me/avatar",
        files={"file": ("a.png", png(), "image/png")},
        data={"crop_x": 0},
        headers=idem(),
    )
    assert r.status_code == 422
    r = await c.put(
        f"{MA}/me/avatar", data={"crop_x": 0, "crop_y": 0, "crop_size": 10}, headers=idem()
    )
    assert r.status_code == 422


async def test_ac18_replace_delete_and_etag_changes(admin, made):
    c, m = await member_login(admin, made)
    first = (await upload(c, png((400, 400), (255, 0, 0)), size=300)).json()["avatar_url"]
    second = (await upload(c, png((400, 400), (0, 255, 0)), size=300)).json()["avatar_url"]
    assert first != second, "đổi ảnh → ?v= đổi (phá cache)"
    assert (
        await q(
            "SELECT count(*) AS n FROM customer_avatar WHERE customer_id=(SELECT id FROM customer WHERE phone=:p)",
            p=m["phone"],
        )
    )[0]["n"] == 1
    assert (await c.delete(f"{MA}/me/avatar", headers=idem())).status_code == 204
    assert (await me(c))["avatar_url"] is None
    assert (await c.delete(f"{MA}/me/avatar", headers=idem())).status_code == 204, (
        "xóa lần hai vẫn 204"
    )
    async with _client() as anon_c:
        assert (await anon_c.get(second)).status_code == 404


async def test_ac18_avatar_does_not_change_version_or_other_fields(admin, made):
    c, _ = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    assert (await upload(c, png(), size=200)).status_code == 200
    after = await me(c)
    assert after["version"] == cur["version"] and after["full_name"] == cur["full_name"]
    assert (await save(c, cur, nickname="Vẫn lưu được")).status_code == 200, (
        "version cũ vẫn hợp lệ sau khi đổi ảnh"
    )


async def test_ac19_audit_for_avatar_update_and_delete(admin, made):
    c, m = await member_login(admin, made)
    base = (await q("SELECT coalesce(max(id), 0) AS i FROM audit_log"))[0]["i"]
    await upload(c, png(), size=200)
    await c.delete(f"{MA}/me/avatar", headers=idem())
    rows = await q(
        "SELECT action FROM audit_log WHERE id > :b AND entity_code=:c AND action LIKE 'member.avatar_%' ORDER BY id",
        b=base,
        c=m["member_code"],
    )
    assert [r["action"] for r in rows] == ["member.avatar_update", "member.avatar_delete"]


async def test_ac19_avatar_endpoint_unknown_ids_and_headers(admin, made, anon):
    assert (await anon.get(f"{MA}/avatars/99999999")).status_code == 404
    assert (await anon.get(f"{MA}/avatars/abc")).status_code == 422
    assert (await anon.get(f"{MA}/avatars/0")).status_code == 422


async def test_ac19_avatar_upload_is_rate_limited_per_user(admin, made):
    c, _ = await member_login(admin, made)
    data = png((120, 120))
    statuses = [(await upload(c, data, size=100)).status_code for _ in range(23)]
    assert statuses.count(200) <= 20 and 429 in statuses, statuses


# ============================================================ liên kết quầy → khách (luồng chính)


async def test_flow_counter_creates_member_customer_verifies_and_enters(admin, made):
    """Quầy tạo HV → khách xác minh SĐT (OTP ở đặt sân) → vào khu hội viên."""
    phone = unique_phone()
    made.append(phone)
    m = await add_member(admin, made, phone=phone, tier="Khá", full_name=f"{tag()} Khách Quầy")
    async with _client() as c:
        # cách 1: đăng nhập bằng mật khẩu ban đầu (= SĐT) → bắt đổi mật khẩu
        assert (await sign_in(c, phone, phone)).status_code == 200
        assert (await c.get(f"{MA}/me")).status_code == 403
        await c.post(f"{API}/auth/password/change", json={"new_password": PW}, headers=idem())
        assert (await me(c))["member_code"] == m["member_code"]


# ============================================================ T-042: hội viên tự chọn Hạng (đảo T-038)


async def tier_rows(code: str, base: int) -> list[dict]:
    return list(
        await q(
            "SELECT actor_type, actor_label, entity_code, detail::text AS d FROM audit_log WHERE action='member.tier_self_change' AND entity_code=:c AND id > :b ORDER BY id",
            c=code,
            b=base,
        )
    )


async def audit_base() -> int:
    return (await q("SELECT coalesce(max(id), 0) AS i FROM audit_log"))[0]["i"]


async def test_t042_ac2_member_chooses_any_of_the_tiers_or_null_and_the_value_is_saved(admin, made):
    from app.modules.members.models import TIERS

    c, m = await member_login(admin, made)  # chưa xếp hạng
    cur = await me(c)
    assert cur["tier"] is None
    for wanted in (*TIERS, None):
        r = await save(c, cur, tier=wanted)
        assert r.status_code == 200, (wanted, r.text)
        assert r.json()["tier"] == wanted
        stored = (await q("SELECT tier FROM customer WHERE member_code=:c", c=m["member_code"]))[0]
        assert stored["tier"] == wanted
        assert (await admin.get(f"{M}/{m['member_code']}")).json()["tier"] == wanted, (
            "quản trị thấy hạng mới"
        )
        cur = r.json()


async def test_t042_ac2_unknown_tier_is_422_e_hv_1_with_other_field_errors_and_nothing_saved(
    admin, made
):
    c, m = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    base = await audit_base()
    for bad in ("Vàng", "", "khá", "KHÁ", "Khá+", "E-HV-14"):
        r = await save(c, cur, tier=bad, nickname="Không Được Lưu")
        assert r.status_code == 422, (bad, r.status_code)
        assert any(f["field"] == "tier" and f["code"] == "E-HV-1" for f in err(r)["fields"]), r.text
        assert err(r)["code"] != "E-HV-14", "đã bỏ E-HV-14"
    both = await save(c, cur, tier="Hạng lạ", email="khong-hop-le")
    fields = {f["field"]: f["code"] for f in err(both)["fields"]}
    assert fields.get("tier") == "E-HV-1" and fields.get("email") == "E-HV-10", "báo cùng ô khác"
    assert await me(c) == cur, "không lưu gì, version không đổi"
    assert not await tier_rows(m["member_code"], base)
    assert (await save(c, cur, tier=1)).status_code == 422, "sai kiểu"
    assert (await save(c, cur, tier="x" * 200)).status_code == 422, "quá dài"
    assert await me(c) == cur


async def test_t042_omitted_tier_keeps_the_tier_and_writes_no_tier_audit(admin, made):
    c, m = await member_login(admin, made, tier="Khá")
    cur = await me(c)
    base = await audit_base()
    r = await c.put(
        f"{MA}/me",
        json={
            "full_name": cur["full_name"],
            "nickname": "Giữ Hạng",
            "show_on_records": cur["show_on_records"],
            "version": cur["version"],
        },
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["tier"] == "Khá", r.text
    assert r.json()["nickname"] == "Giữ Hạng"
    same = await save(c, r.json(), tier="Khá", nickname="Vẫn Khá")
    assert same.status_code == 200 and same.json()["tier"] == "Khá"
    assert not await tier_rows(m["member_code"], base), "không đổi hạng thì không có audit hạng"


async def test_t042_ac3_each_tier_change_has_its_own_audit_row_with_member_actor(admin, made):
    c, m = await member_login(admin, made, tier="Trung bình")
    base = await audit_base()
    r1 = await save(c, await me(c), tier="Khá")
    r2 = await save(c, r1.json(), tier=None, nickname="Cùng Lúc")
    r3 = await save(c, r2.json(), tier="Chuyên nghiệp")
    assert [r.status_code for r in (r1, r2, r3)] == [200, 200, 200]
    rows = await tier_rows(m["member_code"], base)
    assert len(rows) == 3, rows
    for row in rows:
        assert row["actor_type"] == "customer"
        assert row["actor_label"] == f"Hội viên (tự sửa) · {m['member_code']}"
        assert m["phone"] not in row["d"], "không SĐT trong nhật ký"
    assert "Trung bình" in rows[0]["d"] and "Khá" in rows[0]["d"]
    assert "Khá" in rows[1]["d"] and "Chưa xếp hạng" in rows[1]["d"], "null hiện 'Chưa xếp hạng'"
    assert "Chưa xếp hạng" in rows[2]["d"] and "Chuyên nghiệp" in rows[2]["d"]
    self_rows = await q(
        "SELECT detail::text AS d FROM audit_log WHERE action='member.self_update' AND entity_code=:c AND id > :b ORDER BY id",
        c=m["member_code"],
        b=base,
    )
    assert any("Cùng Lúc" in r["d"] for r in self_rows), "ô khác vẫn ghi ở member.self_update"
    assert all("Trình độ" not in r["d"] for r in self_rows), "không lặp Trình độ"


async def test_t042_ac3_tier_change_shows_in_the_action_log_with_a_member_actor(admin, made):
    c, m = await member_login(admin, made, tier="Yếu")
    assert (await save(c, await me(c), tier="Khá")).status_code == 200
    log = f"{API}/admin/audit-log"
    cat = (await admin.get(f"{log}/catalog")).json()
    assert "Hội viên" in [a["label"] for a in cat["actors"]], "bộ lọc người làm có 'Hội viên'"
    assert "member.tier_self_change" in [t["key"] for g in cat["groups"] for t in g["types"]]
    r = await admin.get(log, params={"action": "member.tier_self_change", "size": 100})
    assert r.status_code == 200, r.text
    mine = [i for i in r.json()["items"] if i["target"]["code"] == m["member_code"]]
    assert mine, "dòng đổi hạng hiện ở Lịch sử thao tác"
    row = mine[0]
    assert row["actor"] == "customer" and row["actor_label"] == "Hội viên"
    assert row["actor_name"] == f"Hội viên (tự sửa) · {m['member_code']}"
    assert row["actor_code"] is None and row["action_label"] == "Hội viên tự đổi hạng"
    assert any(
        ch["field"] == "Trình độ" and ch["before"] == "Yếu" and ch["after"] == "Khá"
        for ch in row["changes"]
    ), row["changes"]
    assert m["phone"] not in r.text, "Lịch sử thao tác không lộ SĐT đầy đủ của hội viên"
    by_actor = await admin.get(log, params={"actor": "customer", "size": 100})
    assert by_actor.status_code == 200 and by_actor.json()["items"]
    assert all(
        i["actor"] == "customer" and i["action"] == "member.tier_self_change"
        for i in by_actor.json()["items"]
    ), "chỉ thao tác có trong danh mục"
    shown = {i["action"] for i in (await admin.get(log, params={"size": 100})).json()["items"]}
    assert not shown & {"member.self_update", "member.avatar_update", "member.avatar_delete"}


async def test_t042_ac5_changing_tier_does_not_evict_a_member_already_in_a_room(admin, made):
    """T-031 không đổi: đổi hạng khi đang ở trong phòng không đẩy người đó ra."""
    from tests.qa_rooms import make_room

    host_c, host = await member_login(admin, made, tier="Khá")
    guest_c, _ = await member_login(admin, made, tier="Khá")
    spec = await make_room(admin, host_c, host["member_code"])
    rid = spec["room"]["id"]
    d = (await guest_c.get(f"{MA}/rooms/{rid}")).json()
    joined = await guest_c.post(
        f"{MA}/rooms/{rid}/join-requests", json={"version": d["version"]}, headers=idem()
    )
    assert joined.status_code == 200, joined.text
    req = (await host_c.get(f"{MA}/rooms/{rid}")).json()["join_requests"][0]
    dh = (await host_c.get(f"{MA}/rooms/{rid}")).json()
    ok = await host_c.post(
        f"{MA}/rooms/{rid}/join-requests/{req['id']}/approve",
        json={"version": dh["version"]},
        headers=idem(),
    )
    assert ok.status_code == 200, ok.text
    before = {mm["display_name"] for mm in ok.json()["members"]}
    assert len(before) == 2
    assert (await save(guest_c, await me(guest_c), tier="Yếu")).status_code == 200
    after = {mm["display_name"] for mm in (await host_c.get(f"{MA}/rooms/{rid}")).json()["members"]}
    assert after == before, "người đã trong phòng không bị đẩy ra khi đổi hạng"


async def test_t042_self_registered_member_starts_unranked_and_register_rejects_tier(admin, anon):
    from tests.conftest import register

    phone = unique_phone()
    try:
        r = await register(anon, phone, "QA T038 Đăng Ký")
        assert r.status_code == 201, r.text
        mine = await me(anon)
        assert mine["tier"] is None, "hội viên tự đăng ký mặc định Chưa xếp hạng"
        # không có đường nhét `tier` qua đăng ký
        r2 = await anon.post(
            f"{API}/auth/register/request",
            json={
                "full_name": "QA",
                "phone": unique_phone(),
                "password": "Mat-Khau-1x",
                "tier": "Chuyên nghiệp",
            },
        )
        assert r2.status_code == 422
        # nhưng đăng ký xong thì tự chọn Hạng được (T-042)
        t = await save(anon, mine, tier="Chuyên nghiệp")
        assert t.status_code == 200 and t.json()["tier"] == "Chuyên nghiệp", t.text
    finally:
        await x("DELETE FROM customer WHERE phone = :p", p=phone)
        await x("DELETE FROM users WHERE phone = :p", p=phone)


async def test_t042_ac4_admin_and_staff_still_change_the_tier_and_audit_has_before_after(
    admin, staff, made
):
    c, m = await member_login(admin, made, tier="Trung bình")
    base = (await q("SELECT coalesce(max(id), 0) AS i FROM audit_log"))[0]["i"]
    cur = (await admin.get(f"{M}/{m['member_code']}")).json()
    r = await staff.patch(
        f"{M}/{m['member_code']}", json={"tier": "Khá", "version": cur["version"]}, headers=idem()
    )
    assert r.status_code == 200, r.text
    r2 = await admin_patch(admin, m["member_code"], {"tier": "Chuyên nghiệp"})
    assert r2.status_code == 200, r2.text
    assert (await me(c))["tier"] == "Chuyên nghiệp", "hội viên thấy Hạng do quầy xếp"
    rows = await q(
        "SELECT actor_type, detail::text AS d FROM audit_log WHERE action='member.update' AND entity_code=:c AND id > :b ORDER BY id",
        c=m["member_code"],
        b=base,
    )
    assert len(rows) == 2
    assert "Trung bình" in rows[0]["d"] and "Khá" in rows[0]["d"], "NV: trước → sau"
    assert "Khá" in rows[1]["d"] and "Chuyên nghiệp" in rows[1]["d"], "Admin: trước → sau"

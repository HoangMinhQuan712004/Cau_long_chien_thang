# ruff: noqa: E501
"""QA T-015 (màn Hội viên của PR #21): đối chiếu spec T-015 + SRS Hội viên v0.2 + quyết định người dùng.

Test viết từ **spec**, không theo thiết kế của PR. Chỗ PR cố ý khác spec đánh dấu
``xfail(strict=True)`` kèm mã lệch ``D<n>`` (xem board/qa/T-015-PR21-report.md): bộ test vẫn xanh,
và hễ BACKEND sửa theo spec thì test báo XPASS (strict) để gỡ dấu. Không có dấu xfail = đạt.
"""

import importlib
import re
import uuid

import pytest
from sqlalchemy import text

from app.core.db import engine
from tests.conftest import API, _client, idem, sign_in
from tests.helpers_booking import book, new_court, random_phone, safe_hour, temp
from tests.qa_accounts import db_account
from tests.qa_queries import count_statements

sepay = importlib.import_module("tests.test_qa_T-008").sepay  # fixture cấu hình SePay thử
M = f"{API}/members"
MASKED = re.compile(r"^\d{4} x{3} \d{3}$")


# ACCEPTED = người dùng đã chấp nhận (ARCHITECT 30/10); OPEN = chờ ARCHITECT hỏi người dùng;
# BUG = lỗi chức năng/bảo mật thật, BACKEND cần sửa.
CATEGORY = {
    "D1": "OPEN", "D2": "OPEN", "D3": "OPEN", "D4": "OPEN", "D5": "ACCEPTED", "D6": "OPEN",
    "D7": "OPEN", "D8": "OPEN", "D9": "OPEN", "D10": "ACCEPTED", "D11": "BUG", "D12": "OPEN",
    "D13": "OPEN", "D14": "OPEN", "D15": "OPEN", "F1": "BUG",
}  # fmt: skip


def deviation(code: str, why: str):
    return pytest.mark.xfail(strict=True, reason=f"[{CATEGORY[code]}] {code}: {why}")


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
    """Số điện thoại các hồ sơ test tạo ra -> dọn hồ sơ + tài khoản đăng nhập sau test."""
    phones: list[str] = []
    yield phones
    if phones:
        await x("DELETE FROM customer WHERE phone = ANY(:p)", p=phones)
        await x("DELETE FROM users WHERE phone = ANY(:p)", p=phones)


def tag() -> str:
    return "QAHV" + uuid.uuid4().hex[:8].upper()


async def add_member(client, made, *, name=None, phone=None, **fields):
    phone = phone or random_phone()
    made.append(phone)
    body = {"full_name": name or f"{tag()} Hội Viên", "phone": phone, **fields}
    return await client.post(M, json=body, headers=idem())


async def add_ok(client, made, **kw) -> dict:
    r = await add_member(client, made, **kw)
    assert r.status_code == 201, r.text
    return r.json()


async def add_temp(client, made, *, name=None, phone=None):
    phone = phone or random_phone()
    made.append(phone)
    return await client.post(
        f"{M}/temp", json={"full_name": name or f"{tag()} Tạm", "phone": phone}, headers=idem()
    )


async def patch_m(client, path: str, body: dict, *, version: int | None = None):
    """PATCH sửa hội viên (T-020 AC4): gửi kèm `version` hiện tại (đọc từ chi tiết) nếu không truyền."""
    if version is None and "version" not in body:
        got = await client.get(path)
        assert got.status_code == 200, (path, got.text)
        version = got.json()["version"]
    payload = body if version is None else {**body, "version": version}
    return await client.patch(path, json=payload, headers=idem())


async def listing(client, **params) -> dict:
    r = await client.get(M, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ============================================================ AC20 / SEC1 quyền


async def test_ac20_anonymous_and_member_are_rejected(anon, customer):
    for c in (anon, customer):
        assert (await c.get(M)).status_code in (401, 403)
        assert (
            await c.post(M, json={"full_name": "A", "phone": "0900000000"}, headers=idem())
        ).status_code in (401, 403)
        assert (await c.get(f"{M}/next-code")).status_code in (401, 403)


async def test_ac20_staff_can_view_add_edit_and_make_temp(staff, made):
    assert (await staff.get(M)).status_code == 200
    m = await add_ok(staff, made)
    assert m["member_code"].startswith("HV")
    assert (await add_temp(staff, made)).status_code == 201
    r = await patch_m(staff, f"{M}/{m['member_code']}", {"full_name": f"{tag()} Sửa"})
    assert r.status_code == 200, r.text
    assert (await staff.get(f"{M}/next-code")).status_code == 200


async def test_sec1_staff_cannot_change_status(staff, admin, made):
    m = await add_ok(admin, made)
    r = await patch_m(staff, f"{M}/{m['member_code']}", {"is_active": False})
    assert r.status_code == 403, r.text
    row = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert row["is_active"] is True


async def test_oq1_staff_can_change_tier_but_not_status_user_decision_31_10(staff, admin, made):
    """Người dùng chốt 31/10: giữ theo PR – NV đổi được Hạng, vẫn không đổi được Trạng thái."""
    m = await add_ok(admin, made, tier="Trung bình")
    r = await patch_m(staff, f"{M}/{m['member_code']}", {"tier": "Khá"})
    assert r.status_code == 200 and r.json()["tier"] == "Khá", r.text
    r = await add_member(staff, made, tier="Chuyên nghiệp")
    assert r.status_code == 201 and r.json()["tier"] == "Chuyên nghiệp"
    r = await patch_m(staff, f"{M}/{m['member_code']}", {"is_active": False})
    assert r.status_code == 403, "NV vẫn không đổi Trạng thái"


@deviation("D2", "Hạng mặc định phải là Trung bình (OQ-2); PR mặc định 'chưa xếp hạng' (null)")
async def test_ac10_default_tier_is_trung_binh(admin, made):
    m = await add_ok(admin, made)
    assert m["tier"] == "Trung bình"


# ============================================================ AC21 hạng 8 bậc

TIERS = [
    "Yếu", "Trung bình yếu", "Trung bình -", "Trung bình", "Trung bình +", "Khá",
    "Bán chuyên", "Chuyên nghiệp",
]  # fmt: skip


async def test_ac21_eight_tiers_accepted_and_old_ones_rejected(admin, made):
    for tier in TIERS:
        m = await add_ok(admin, made, tier=tier)
        assert m["tier"] == tier
    for old in ("Vàng", "Bạc", "Đồng", "Trung bình khá", ""):
        r = await add_member(admin, made, tier=old)
        assert r.status_code == 422, (old, r.text)


async def test_ac21_tier_shows_in_counter_search(admin, made):
    m = await add_ok(admin, made, tier="Trung bình +")
    r = await admin.get(f"{M}/search", params={"q": m["member_code"]})
    assert r.status_code == 200
    assert any(i["tier"] == "Trung bình +" for i in r.json())


# ============================================================ AC10/11 thêm hội viên


async def test_ac11_code_format_and_no_reuse(admin, made):
    a = await add_ok(admin, made)
    b = await add_ok(admin, made)
    na, nb = int(a["member_code"][2:]), int(b["member_code"][2:])
    assert re.fullmatch(r"HV\d{4,5}", a["member_code"]) and nb == na + 1
    nxt = (await admin.get(f"{M}/next-code")).json()["member_code"]
    assert int(nxt[2:]) == nb + 1, "next-code shows the next code without consuming it"


@deviation(
    "D3", "Báo mọi ô sai trong một lần (E-001 + E-002 cùng 422 kèm fields); PR dừng ở lỗi đầu"
)
async def test_ac11_all_invalid_fields_reported_at_once(admin):
    r = await admin.post(M, json={"full_name": " ", "phone": "12"}, headers=idem())
    assert r.status_code == 422
    fields = err(r).get("fields") or []
    assert {f["field"] for f in fields} >= {"full_name", "phone"}, r.text


async def test_ac11_validation_each_field(admin, made):
    r = await admin.post(M, json={"full_name": "", "phone": random_phone()}, headers=idem())
    assert r.status_code == 422 and err(r)["code"] in ("E-001", "E-HV-1")
    r = await admin.post(M, json={"full_name": "Có tên", "phone": ""}, headers=idem())
    assert r.status_code == 422
    for bad in ("12345", "abc", "0123456789012345", "09123"):
        r = await admin.post(M, json={"full_name": "Có tên", "phone": bad}, headers=idem())
        assert r.status_code == 422, (bad, r.text)
    r = await admin.post(M, json={"full_name": "x" * 101, "phone": random_phone()}, headers=idem())
    assert r.status_code == 422, "name over 100 characters"


async def test_ac11_name_is_trimmed_and_phone_normalized(admin, made):
    p = random_phone()
    m = await add_ok(
        admin, made, name=f"  {tag()}   Nguyễn  ", phone=f"+84 {p[1:4]} {p[4:7]} {p[7:]}"
    )
    assert m["full_name"] == m["full_name"].strip()
    again = await add_member(admin, made, phone=p)
    assert again.status_code == 409, "same phone in another format is a duplicate"


async def test_ac11_duplicate_phone_of_member_and_of_temp(admin, made):
    m = await add_ok(admin, made)
    r = await add_member(admin, made, phone=m["phone"])
    assert r.status_code == 409 and m["member_code"] in r.text
    t = await add_temp(admin, made)
    assert t.status_code == 201
    r = await add_member(admin, made, phone=t.json()["phone"])
    assert r.status_code == 409, "OQ-6: a phone that has a temp profile is blocked"
    assert (await listing(admin, q=t.json()["phone"]))["items"][0]["kind"] == "temp", "stays temp"


async def test_ac1_t020_temp_phone_blocks_member_with_e_004_and_upgrade_is_gone(admin, made):
    t = await add_temp(admin, made)
    tj = t.json()
    r = await add_member(admin, made, phone=tj["phone"])
    assert r.status_code == 409 and err(r)["code"] == "E-MEM-1", r.text
    msg = err(r)["message"]
    assert msg.startswith("Số điện thoại đã có hồ sơ tạm: ") and tj["full_name"] in msg, msg
    assert re.search(r"\(tạo \d{2}/\d{2}/\d{4}\)", msg), msg
    assert "bookings" not in err(r) and "next_code" not in err(r), (
        "đã bỏ dữ liệu của luồng nâng hồ sơ"
    )
    r = await add_member(admin, made, phone=tj["phone"], upgrade_temp=True)
    assert r.status_code == 422, "upgrade_temp không còn (trường lạ)"
    assert (await listing(admin, q=tj["phone"]))["items"][0]["kind"] == "temp", "vẫn là hồ sơ tạm"
    assert not await q(
        "SELECT 1 FROM audit_log WHERE action='member.promote' AND entity_code=:c", c=tj["ref"]
    )


async def test_ac12_idempotent_create_returns_same_member(admin, made):
    phone = random_phone()
    made.append(phone)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"full_name": f"{tag()} Idem", "phone": phone}
    r1 = await admin.post(M, json=body, headers=key)
    r2 = await admin.post(M, json=body, headers=key)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201 and r2.json()["member_code"] == r1.json()["member_code"], r2.text
    n = (await q("SELECT count(*) AS n FROM customer WHERE phone=:p", p=phone))[0]["n"]
    assert n == 1


async def test_sec3_write_needs_origin(admin, made):
    r = await admin.post(
        M, json={"full_name": "A B", "phone": random_phone()},
        headers={**idem(), "Origin": "https://evil.example"},
    )  # fmt: skip
    assert r.status_code == 403 and err(r)["code"] == "E-SEC-1"


# ============================================================ AC1-AC6 danh sách


async def test_ac1_ac2_list_shape(admin, made):
    m = await add_ok(admin, made, gender="male", tier="Khá")
    t = (await add_temp(admin, made)).json()
    data = await listing(admin, q=m["member_code"])
    row = data["items"][0]
    assert (
        row["member_code"] == m["member_code"] and row["tier"] == "Khá" and row["kind"] == "member"
    )
    assert row["is_active"] is True and row["bookings"] == 0
    trow = (await listing(admin, q=t["phone"]))["items"][0]
    assert trow["kind"] == "temp" and trow["member_code"] is None and trow["tier"] is None


@deviation("D5", "SĐT che 0912 xxx 678 ở danh sách (AC2, ADR-004, OQ-4); PR trả đầy đủ (b58d121)")
async def test_ac2_list_phone_is_masked(admin, made):
    m = await add_ok(admin, made)
    row = (await listing(admin, q=m["member_code"]))["items"][0]
    assert MASKED.match(row.get("phone_masked") or row["phone"]), row["phone"]


@deviation("D5", "SĐT đầy đủ chỉ ở /edit; chi tiết phải che (SEC2); PR trả đầy đủ ở cả chi tiết")
async def test_sec2_detail_phone_is_masked(admin, made):
    m = await add_ok(admin, made)
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert MASKED.match(d.get("phone_masked") or d["phone"]), d["phone"]


@deviation("D5", "/members/search trả SĐT đầy đủ cho popup chọn hội viên")
async def test_sec2_search_popup_phone_is_masked(admin, made):
    m = await add_ok(admin, made)
    r = (await admin.get(f"{M}/search", params={"q": m["member_code"]})).json()
    assert MASKED.match(r[0].get("phone_masked") or r[0]["phone"]), r[0]["phone"]


@deviation(
    "D6", "Số trên chip/tiêu đề không đổi theo tìm/lọc (AC1); PR đếm theo bộ lọc q/status/tier"
)
async def test_ac1_counts_ignore_search_and_filters(admin, made):
    await add_ok(admin, made)
    await add_temp(admin, made)
    base = (await listing(admin))["counts"]
    narrowed = (await listing(admin, q=f"zz-{uuid.uuid4().hex}"))["counts"]
    assert narrowed == base, (base, narrowed)
    assert base["all"] == base["member"] + base["temp"]


async def test_ac3_search_case_insensitive_substring_and_phone_forms(admin, made):
    token = tag()
    m = await add_ok(admin, made, name=f"{token} Trần Thị")
    assert any(
        i["member_code"] == m["member_code"]
        for i in (await listing(admin, q=token.lower()))["items"]
    )
    assert (await listing(admin, q=m["member_code"].lower()))["total"] >= 1
    p = m["phone"]
    for spaced in (p[:4] + " " + p[4:7] + " " + p[7:], p[:4] + "." + p[4:7] + "." + p[7:], p[-6:]):
        got = await listing(admin, q=spaced)
        assert any(i["member_code"] == m["member_code"] for i in got["items"]), spaced


@deviation("D7", "Tìm không phân biệt dấu (AC3): 'nguyen' phải ra 'Nguyễn'; PR dùng ILIKE thường")
async def test_ac3_search_ignores_diacritics(admin, made):
    token = tag()
    m = await add_ok(admin, made, name=f"{token} Nguyễn Văn Ánh")
    got = await listing(admin, q=f"{token} nguyen van anh")
    assert any(i["member_code"] == m["member_code"] for i in got["items"])


async def test_sec4_search_limits_and_wildcards_are_literal(admin, made):
    await add_ok(admin, made)
    r = await admin.get(M, params={"q": "a" * 51})
    assert r.status_code == 422
    for evil in ("%", "_", "%%%", "\\", "'; DROP TABLE customer; --", "(a+)+$"):
        r = await admin.get(M, params={"q": evil})
        assert r.status_code == 200, (evil, r.text)
        assert all(
            evil.lower() in (i["full_name"] + i["phone"] + (i["member_code"] or "")).lower()
            for i in r.json()["items"]
        ), evil
    assert (await q("SELECT count(*) AS n FROM customer"))[0]["n"] >= 1, "table still there"
    # ReDoS: tìm kiếm so khớp theo chữ (LIKE đã thoát ký tự), không dùng regex → trả kết quả rỗng, không treo.
    # Không đo thời gian (T-067 AC3): chỉ cần trả lời đúng; nếu dùng regex backtracking test sẽ treo thay vì chập chờn.
    r = await admin.get(M, params={"q": "(a+)+$" + "a" * 40})
    assert r.status_code == 200 and r.json()["items"] == []


async def test_ac4_kind_and_filters_combine(admin, made):
    token = tag()
    m = await add_ok(admin, made, name=f"{token} A", tier="Khá")
    await patch_m(admin, f"{M}/{m['member_code']}", {"is_active": False})
    t = (await add_temp(admin, made, name=f"{token} B")).json()
    both = await listing(admin, q=token)
    assert {i["kind"] for i in both["items"]} == {"member", "temp"}
    only_m = await listing(admin, q=token, kind="member")
    assert [i["member_code"] for i in only_m["items"]] == [m["member_code"]]
    only_t = await listing(admin, q=token, kind="temp")
    assert [i["kind"] for i in only_t["items"]] == ["temp"] and only_t["items"][0]["phone"] == t[
        "phone"
    ]
    filt = await listing(admin, q=token, status="inactive")
    assert all(i["kind"] == "member" for i in filt["items"]), "status filter hides temp profiles"
    assert (await listing(admin, q=token, tier="Khá", status="inactive"))["total"] == 1
    assert (await listing(admin, q=token, tier="Yếu"))["total"] == 0


@deviation(
    "D8", "Mặc định: hội viên theo Mã HV tăng dần rồi hồ sơ tạm mới nhất (AC5); PR: mới nhất trước"
)
async def test_ac5_default_order_members_by_code_then_temps(admin, made):
    token = tag()
    a = await add_ok(admin, made, name=f"{token} 1")
    b = await add_ok(admin, made, name=f"{token} 2")
    t = (await add_temp(admin, made, name=f"{token} T")).json()
    items = (await listing(admin, q=token))["items"]
    assert [i["member_code"] for i in items[:2]] == [a["member_code"], b["member_code"]]
    assert items[2]["phone"] == t["phone"]


async def test_ac5_pagination_20_per_page(admin, made):
    token = tag()
    for _ in range(23):
        await add_ok(admin, made, name=f"{token} P")
    first = await listing(admin, q=token)
    assert first["total"] == 23 and len(first["items"]) == 20 and first["size"] == 20
    second = await listing(admin, q=token, page=2)
    assert len(second["items"]) == 3
    ids = [i["member_code"] for i in first["items"] + second["items"]]
    assert len(set(ids)) == 23, "no overlap/loss between pages"
    assert (await listing(admin, q=token, page=3))["items"] == []


async def test_ac5_sort_by_bookings_both_directions(admin, made):
    token = tag()
    court = await new_court(admin)
    h = await safe_hour()
    many = await add_ok(admin, made, name=f"{token} Nhiều")
    few = await add_ok(admin, made, name=f"{token} Ít")
    none = await add_ok(admin, made, name=f"{token} Không")
    if h < 22:
        await book(admin, court["code"], h, h + 1, customer={"member_code": few["member_code"]})
    await book(
        admin,
        (await new_court(admin))["code"],
        h,
        h + 1,
        customer={"member_code": many["member_code"]},
    )
    await book(
        admin,
        (await new_court(admin))["code"],
        h,
        h + 1,
        customer={"member_code": many["member_code"]},
    )
    desc = [
        i["member_code"] for i in (await listing(admin, q=token, sort="bookings_desc"))["items"]
    ]
    asc = [i["member_code"] for i in (await listing(admin, q=token, sort="bookings_asc"))["items"]]
    assert desc[0] == many["member_code"] and asc[-1] == many["member_code"]
    assert asc[0] == none["member_code"] or asc[0] == few["member_code"]
    assert (await listing(admin, q=token, sort="bookings_desc"))["items"][0]["bookings"] == 2


async def test_ac6_no_match_is_empty_list(admin):
    data = await listing(admin, q=f"zz{uuid.uuid4().hex}")
    assert data["items"] == [] and data["total"] == 0


# ============================================================ AC8/AC9 chi tiết + số lần đặt


async def test_ac8_detail_fields_and_recent_bookings_newest_first(admin, made):
    m = await add_ok(admin, made, gender="female", tier="Khá", racket="Yonex Astrox")
    court = await new_court(admin)
    h = await safe_hour()
    r1 = await book(admin, court["code"], h, h + 1, customer={"member_code": m["member_code"]})
    assert r1.status_code == 201, r1.text
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert d["member_code"] == m["member_code"] and d["tier"] == "Khá" and d["racket"]
    assert d["bookings"] == 1 and d["total_minutes"] == 60
    assert len(d["recent_bookings"]) == 1 and d["recent_bookings"][0]["code"] == r1.json()["code"]
    assert d["recent_bookings"][0]["amount"] > 0


async def test_ac8_empty_history_is_zero(admin, made):
    m = await add_ok(admin, made)
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert d["bookings"] == 0 and d["total_minutes"] == 0 and d["recent_bookings"] == []


async def test_ac8_only_five_most_recent(admin, made):
    m = await add_ok(admin, made)
    h = await safe_hour()
    for _ in range(6):
        r = await book(
            admin,
            (await new_court(admin))["code"],
            h,
            h + 1,
            customer={"member_code": m["member_code"]},
        )
        assert r.status_code == 201, r.text
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert d["bookings"] == 6 and len(d["recent_bookings"]) == 5


@deviation("D9", "Số lần đặt không đếm 'Không thu được' (AC9/BR-005); PR đếm mọi booking")
async def test_ac9_uncollectible_booking_is_not_counted(admin, made):
    m = await add_ok(admin, made)
    h = await safe_hour()
    b = (
        await book(
            admin,
            (await new_court(admin))["code"],
            h,
            h + 1,
            customer={"member_code": m["member_code"]},
        )
    ).json()
    r = await admin.post(
        f"{API}/booking/items/{b['code']}/uncollectible",
        json={"reason": "QA không thu được", "version": b["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (await admin.get(f"{M}/{m['member_code']}")).json()["bookings"] == 0


async def test_ac9_multi_hour_booking_counts_once_and_sums_hours(admin, made):
    m = await add_ok(admin, made)
    h = await safe_hour()
    if h >= 22:
        pytest.skip("needs 2 hours before midnight")
    r = await book(
        admin,
        (await new_court(admin))["code"],
        h,
        h + 2,
        customer={"member_code": m["member_code"]},
    )
    assert r.status_code == 201, r.text
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert d["bookings"] == 1 and d["total_minutes"] == 120


async def test_ac9_history_follows_the_profile_not_the_phone(admin, made):
    m = await add_ok(admin, made)
    h = await safe_hour()
    await book(
        admin,
        (await new_court(admin))["code"],
        h,
        h + 1,
        customer={"member_code": m["member_code"]},
    )
    other = await add_ok(admin, made)
    assert (await admin.get(f"{M}/{other['member_code']}")).json()["bookings"] == 0


async def test_ac9_temp_profile_counts_its_bookings_in_list(admin, made):
    t = (await add_temp(admin, made)).json()
    h = await safe_hour()
    r = await book(
        admin, (await new_court(admin))["code"], h, h + 1, customer=temp("Khách tạm", t["phone"])
    )
    assert r.status_code == 201, r.text
    row = (await listing(admin, q=t["phone"]))["items"][0]
    assert row["kind"] == "temp" and row["bookings"] == 1


async def test_ac8_temp_detail_and_unknown_refs(admin, made):
    t = (await add_temp(admin, made)).json()
    assert (await admin.get(f"{M}/{t['ref']}")).status_code == 200, (
        "PR: a temp profile has a detail"
    )
    assert (await admin.get(f"{M}/HV9999999")).status_code == 404
    assert (await admin.get(f"{M}/{uuid.uuid4()}")).status_code == 404


# ============================================================ AC14-AC17 sửa


async def test_ac15_edit_updates_fields_and_noop_does_not_audit(admin, made):
    m = await add_ok(admin, made, gender="male")
    new = f"{tag()} Đã sửa"
    r = await patch_m(admin, f"{M}/{m['member_code']}", {"full_name": new, "tier": "Khá"})
    assert r.status_code == 200 and r.json()["full_name"] == new and r.json()["tier"] == "Khá"
    before = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    r = await patch_m(admin, f"{M}/{m['member_code']}", {"full_name": new})
    assert r.status_code == 200
    after = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='member.update' AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    assert after == before, "no-op does not write an audit row"


async def test_ac15_code_and_created_at_are_immutable(admin, made):
    m = await add_ok(admin, made)
    for field, value in (
        ("member_code", "HV0001"),
        ("created_at", "2020-01-01T00:00:00Z"),
        ("bookings", 99),
    ):
        r = await patch_m(admin, f"{M}/{m['member_code']}", {field: value})
        assert r.status_code == 422, (field, r.text)


@deviation(
    "D10", "Sửa được SĐT hội viên (AC14/AC15); PR không cho đổi SĐT (extra field bị từ chối)"
)
async def test_ac14_phone_is_editable_and_checked(admin, made):
    m = await add_ok(admin, made)
    new = random_phone()
    made.append(new)
    r = await patch_m(admin, f"{M}/{m['member_code']}", {"phone": new})
    assert r.status_code == 200 and r.json()["phone"] == new, r.text
    other = await add_ok(admin, made)
    r = await patch_m(admin, f"{M}/{m['member_code']}", {"phone": other["phone"]})
    assert r.status_code == 409


async def test_ac16_stale_version_is_rejected(admin, made):
    m = await add_ok(admin, made)
    d = (await admin.get(f"{M}/{m['member_code']}")).json()
    assert "version" in d, "detail must expose a version"
    ok = await patch_m(
        admin, f"{M}/{m['member_code']}", {"full_name": f"{tag()} A", "version": d["version"]}
    )
    assert ok.status_code == 200
    stale = await patch_m(
        admin, f"{M}/{m['member_code']}", {"full_name": f"{tag()} B", "version": d["version"]}
    )
    assert stale.status_code == 409


async def test_ac2_t020_inactive_member_is_selectable_and_bookable(admin, made):
    m = await add_ok(admin, made)
    assert (
        await patch_m(admin, f"{M}/{m['member_code']}", {"is_active": False})
    ).status_code == 200
    found = (await admin.get(f"{M}/search", params={"q": m["member_code"]})).json()
    assert found and found[0]["is_active"] is False, "popup hiện nhãn Ngừng"
    h = await safe_hour()
    court = await new_court(admin)
    r = await book(admin, court["code"], h, h + 1, customer={"member_code": m["member_code"]})
    assert r.status_code == 201, r.text
    body = r.json()
    first = body["bookings"][0] if "bookings" in body else body
    assert (
        first["customer"]["kind"] == "member"
        and first["customer"]["member_code"] == m["member_code"]
    ), first


# ============================================================ AC18 hồ sơ tạm


async def test_ac18_temp_create_validation_and_duplicate(admin, made):
    r = await admin.post(
        f"{M}/temp", json={"full_name": "", "phone": random_phone()}, headers=idem()
    )
    assert r.status_code == 422
    r = await admin.post(f"{M}/temp", json={"full_name": "A", "phone": "123"}, headers=idem())
    assert r.status_code == 422
    t = await add_temp(admin, made)
    assert t.status_code == 201 and t.json()["kind"] == "temp"
    again = await add_temp(admin, made, phone=t.json()["phone"])
    assert again.status_code == 409
    m = await add_ok(admin, made)
    assert (await add_temp(admin, made, phone=m["phone"])).status_code == 409


@deviation("D12", "Hồ sơ tạm không sửa được (OQ-4/FR-008); PR cho sửa họ tên, giới tính")
async def test_oq4_temp_profile_is_not_editable(admin, made):
    t = (await add_temp(admin, made)).json()
    r = await patch_m(admin, f"{M}/{t['ref']}", {"full_name": f"{tag()} X"})
    assert r.status_code in (403, 404, 405, 422), r.text


async def test_ac18_temp_create_is_idempotent(admin, made):
    phone = random_phone()
    made.append(phone)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"full_name": f"{tag()} T", "phone": phone}
    r1 = await admin.post(f"{M}/temp", json=body, headers=key)
    r2 = await admin.post(f"{M}/temp", json=body, headers=key)
    assert (
        r1.status_code == 201 and r2.status_code == 201 and r2.json()["ref"] == r1.json()["ref"]
    ), r2.text


# ============================================================ AC19 nhật ký


async def test_ac19_audit_rows_have_no_phone_and_name_the_actor(admin, staff, made):
    m = await add_ok(staff, made)
    rows = await q(
        "SELECT actor_label, detail::text AS d FROM audit_log WHERE action='member.create' AND entity_code=:c ORDER BY id DESC LIMIT 1",
        c=m["member_code"],
    )
    assert len(rows) == 1 and re.match(r"NV\d{3}", rows[0]["actor_label"]), rows[0]["actor_label"]
    # PR #22 (BR-007): nhật ký ghi SĐT đầy đủ, chỉ Admin xem – người dùng đã duyệt; mật khẩu thì không bao giờ
    assert "password" not in rows[0]["d"].lower() and "mật khẩu" not in rows[0]["d"].lower()
    t = (await add_temp(admin, made)).json()
    rows = await q(
        "SELECT actor_label, detail::text AS d FROM audit_log WHERE action LIKE 'member.temp%' AND entity_code=:r",
        r=t["ref"],
    )
    assert rows and rows[0]["actor_label"] == "Admin"


async def test_ac19_failed_save_writes_nothing(admin, made):
    m = await add_ok(admin, made)
    n0 = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action LIKE 'member.%' AND action <> 'member.view'"
        )
    )[0]["n"]
    await admin.post(M, json={"full_name": "A B", "phone": m["phone"]}, headers=idem())
    await admin.post(M, json={"full_name": "", "phone": random_phone()}, headers=idem())
    n1 = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action LIKE 'member.%' AND action <> 'member.view'"
        )
    )[0]["n"]
    assert n1 == n0


async def test_ac19_update_audit_has_before_and_after(admin, made):
    m = await add_ok(admin, made, tier="Trung bình")
    await patch_m(admin, f"{M}/{m['member_code']}", {"tier": "Khá"})
    d = (
        await q(
            "SELECT detail::text AS d FROM audit_log WHERE action='member.update' AND entity_code=:c ORDER BY id DESC LIMIT 1",
            c=m["member_code"],
        )
    )[0]["d"]
    assert "Trung bình" in d and "Khá" in d, d


@deviation(
    "D14",
    "Xem chi tiết không được ghi audit (spec chỉ ghi create/update/temp_create/racket.create); PR ghi member.view mỗi lần xem",
)
async def test_ac19_viewing_detail_is_not_audited(admin, made):
    m = await add_ok(admin, made)
    await admin.get(f"{M}/{m['member_code']}")
    assert not await q(
        "SELECT 1 FROM audit_log WHERE action='member.view' AND entity_code=:c", c=m["member_code"]
    )


# ============================================================ vợt


async def test_ac13_racket_catalog_rules(admin, staff, made):
    name = f"QA Vợt {uuid.uuid4().hex[:6]}"
    r = await staff.post(f"{API}/rackets", json={"name": name}, headers=idem())
    created_by_staff = r.status_code == 201
    r = await admin.post(
        f"{API}/rackets",
        json={"name": name if not created_by_staff else name + " 2"},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    listed = (await staff.get(f"{API}/rackets")).json()
    assert any(i["name"].lower().startswith("qa vợt") for i in listed)
    dup = await admin.post(
        f"{API}/rackets", json={"name": r.json()["name"].upper()}, headers=idem()
    )
    assert dup.status_code == 409, "duplicate name is case-insensitive"


# D15 hết lệch: NV mặc định có quyền Danh mục vợt (người dùng chốt 2026-11-05)
async def test_ac13_staff_can_add_racket(staff):
    r = await staff.post(
        f"{API}/rackets", json={"name": f"QA Khác {uuid.uuid4().hex[:6]}"}, headers=idem()
    )
    assert r.status_code == 201, r.text


async def test_ac13_racket_name_over_100_is_rejected(admin):
    r = await admin.post(f"{API}/rackets", json={"name": "x" * 101}, headers=idem())
    assert r.status_code in (409, 422), r.text
    assert r.status_code != 201


# ============================================================ tài khoản hội viên (mật khẩu = SĐT, đổi trong 3 ngày)


async def test_member_account_created_with_phone_password_and_must_change(admin, made):
    m = await add_ok(admin, made)
    row = (
        await q(
            "SELECT role::text AS role, must_change_password AS must, member_account_at IS NOT NULL AS stamped, is_active FROM users WHERE phone=:p",
            p=m["phone"],
        )
    )[0]
    assert row["role"] == "member" and row["must"] is True and row["stamped"] and row["is_active"]
    async with _client() as c:
        r = await sign_in(c, m["phone"], m["phone"])
        assert r.status_code == 200, r.text
        blocked = await c.get(f"{API}/auth/me")
        assert blocked.status_code in (200, 403)
        r2 = await c.post(
            f"{API}/auth/change-password", json={"new_password": m["phone"]}, headers=idem()
        )
        assert r2.status_code in (400, 404, 422), "new password equal to the phone is refused"


async def test_member_account_wrong_password_and_lockout_still_apply(admin, made):
    m = await add_ok(admin, made)
    async with _client() as c:
        codes = [(await sign_in(c, m["phone"], "Sai-mat-khau-1")).status_code for _ in range(5)]
        assert codes[:4] == [401] * 4 and codes[4] in (401, 423), codes
        r = await sign_in(c, m["phone"], m["phone"])
        assert r.status_code == 423, (
            "5 wrong attempts lock the account even for the initial password"
        )


async def test_member_account_expires_after_3_days(admin, made):
    m = await add_ok(admin, made)
    await x(
        "UPDATE users SET member_account_at = now() - interval '4 days' WHERE phone=:p",
        p=m["phone"],
    )
    async with _client() as c:
        r = await sign_in(c, m["phone"], m["phone"])
        assert r.status_code == 403 and err(r)["code"] == "E-AUTH-30", r.text
        r = await sign_in(c, m["phone"], "Sai-mat-khau-1")
        assert r.status_code == 401, "a wrong password is still a wrong password"


async def test_member_account_follows_status_stop_and_resume(admin, made):
    m = await add_ok(admin, made)
    assert (
        await patch_m(admin, f"{M}/{m['member_code']}", {"is_active": False})
    ).status_code == 200
    assert (await q("SELECT is_active FROM users WHERE phone=:p", p=m["phone"]))[0][
        "is_active"
    ] is False
    async with _client() as c:
        assert (await sign_in(c, m["phone"], m["phone"])).status_code in (401, 403)
    assert (await patch_m(admin, f"{M}/{m['member_code']}", {"is_active": True})).status_code == 200
    assert (await q("SELECT is_active FROM users WHERE phone=:p", p=m["phone"]))[0][
        "is_active"
    ] is True


async def test_member_account_does_not_take_over_an_existing_account(admin, made, customer):
    phone = (await customer.get(f"{API}/auth/me")).json()["phone"]
    before = (
        await q(
            "SELECT hashed_password, must_change_password AS m FROM users WHERE phone=:p", p=phone
        )
    )[0]
    r = await admin.post(
        M, json={"full_name": f"{tag()} Có tài khoản", "phone": phone}, headers=idem()
    )
    assert r.status_code == 201, r.text
    after = (
        await q(
            "SELECT hashed_password, must_change_password AS m FROM users WHERE phone=:p", p=phone
        )
    )[0]
    assert before == after, "existing customer account is not reset"
    await x("DELETE FROM customer WHERE phone=:p", p=phone)


# ============================================================ AC22 hiệu năng (5.000 hồ sơ)


# T-067: không đo ms nữa; số câu SQL không theo số dòng (đã gỡ xfail D16: test từng hỏng lặng lẽ từ T-019)
async def test_ac22_list_under_3s_with_5000_profiles_and_20000_bookings(admin):
    prefix = str(uuid.uuid4().int % 90_000)
    await x(
        "INSERT INTO customer (kind, full_name, phone, is_active) "
        "SELECT 'temp', 'QA Load ' || g, '06' || lpad((:base + g)::text, 8, '0'), true "
        "FROM generate_series(1, 5000) g",
        base=int(prefix) * 1000,
    )
    try:
        # Từ T-019 mỗi booking thuộc một đơn (order_id NOT NULL, seq 1–99): mỗi hồ sơ một đơn 4 khối
        await x(
            "INSERT INTO booking.booking_order (tenant_id, code, play_date, channel, customer_ref,"
            " customer_kind, customer_name, customer_phone, created_by_label) "
            "SELECT 1, 'BK-QALOAD-' || c.id, current_date, 'counter', c.id::text, 'temp', c.full_name,"
            " c.phone, 'Admin' FROM customer c WHERE c.full_name LIKE 'QA Load %'"
        )
        await x(
            "INSERT INTO booking.booking (tenant_id, order_id, seq, code, source, resource_id, play_date,"
            " start_at, end_at, customer_ref, customer_kind, customer_name, customer_phone, amount,"
            " payment_status, created_by_type, created_by_label) "
            "SELECT 1, o.id, n, 'QALOAD-' || c.id || '-' || n, 'counter', (SELECT min(id) FROM booking.resource),"
            " current_date - (n * 3 + (c.id % 3))::int,"
            " (current_date - (n * 3 + (c.id % 3))::int)::timestamptz + interval '9 hours',"
            " (current_date - (n * 3 + (c.id % 3))::int)::timestamptz + interval '10 hours',"
            " c.id::text, 'temp', c.full_name, c.phone, 100000, 'unpaid', 'admin', 'Admin' "
            "FROM customer c JOIN booking.booking_order o ON o.code = 'BK-QALOAD-' || c.id,"
            " generate_series(1, 4) n WHERE c.full_name LIKE 'QA Load %'"
        )
        total = (await q("SELECT count(*) AS n FROM booking.booking WHERE code LIKE 'QALOAD-%'"))[
            0
        ]["n"]
        assert total == 20000, total
        counts = {}
        for name, params in (
            ("default", {}),
            ("sort_desc", {"sort": "bookings_desc"}),
            ("sort_asc_page9", {"sort": "bookings_asc", "page": 9}),
            ("search", {"q": "QA Load 4999"}),
            ("filter_kind_sort", {"kind": "temp", "sort": "bookings_desc"}),
        ):
            with count_statements() as n:
                got = await listing(admin, **params)
            counts[name] = n[0]
            assert got["total"] >= 1
        print("AC22 statements", counts)
        # 20.000 booking: số câu SQL không theo số dòng (không N+1); không đo ms (T-067 AC3)
        assert max(counts.values()) <= 12, counts
    finally:
        await x("DELETE FROM booking.booking WHERE code LIKE 'QALOAD-%'")
        await x("DELETE FROM booking.booking_order WHERE code LIKE 'BK-QALOAD-%'")
        await x("DELETE FROM customer WHERE full_name LIKE 'QA Load %'")


# ============================================================ đổi mật khẩu lần đầu + hạn 3 ngày + cô lập dữ liệu


def pw_change(c, new, current=None):
    body = {"new_password": new, **({"current_password": current} if current else {})}
    return c.post(f"{API}/auth/password/change", json=body, headers=idem())


async def test_first_login_must_change_password_before_anything_else(admin, made):
    m = await add_ok(admin, made)
    async with _client() as c:
        assert (await sign_in(c, m["phone"], m["phone"])).status_code == 200
        r = await c.get(f"{API}/me/member")
        assert r.status_code == 403 and err(r)["code"] == "E-AUTH-25", r.text
        assert (await c.get(f"{API}/me/member/bookings")).status_code == 403
        # đổi mật khẩu: không cần mật khẩu hiện tại, nhưng không được trùng SĐT / quá yếu
        assert (await pw_change(c, m["phone"])).status_code == 422
        assert (await pw_change(c, "yeu")).status_code == 422
        ok = await pw_change(c, "Hv-Moi-Pass-1")
        assert ok.status_code == 200, ok.text
        card = await c.get(f"{API}/me/member")
        assert card.status_code == 200 and card.json()["member_code"] == m["member_code"], card.text
    async with _client() as c:
        assert (await sign_in(c, m["phone"], m["phone"])).status_code == 401, "old password is dead"
        assert (await sign_in(c, m["phone"], "Hv-Moi-Pass-1")).status_code == 200


async def test_after_first_change_old_session_is_revoked_and_current_password_is_needed(
    admin, made
):
    m = await add_ok(admin, made)
    async with _client() as a, _client() as b:
        await sign_in(a, m["phone"], m["phone"])
        await sign_in(b, m["phone"], m["phone"])
        assert (await pw_change(a, "Hv-Moi-Pass-1")).status_code == 200
        r = await b.get(f"{API}/auth/me")
        assert r.status_code == 401, "the other session opened with the old password is revoked"
        wrong = await pw_change(a, "Hv-Khac-Pass-2", current="sai-mat-khau")
        assert wrong.status_code == 400 and err(wrong)["code"] == "E-AUTH-28"
        good = await pw_change(a, "Hv-Khac-Pass-2", current="Hv-Moi-Pass-1")
        assert good.status_code == 200


async def test_expiry_blocks_an_open_session_and_forgot_password_recovers(admin, made):
    m = await add_ok(admin, made)
    async with _client() as c:
        assert (await sign_in(c, m["phone"], m["phone"])).status_code == 200
        await x(
            "UPDATE users SET member_account_at = now() - interval '4 days' WHERE phone=:p",
            p=m["phone"],
        )
        r = await c.get(f"{API}/me/member")
        assert r.status_code == 403 and err(r)["code"] == "E-AUTH-30", r.text
        r = await pw_change(c, "Hv-Moi-Pass-1")
        assert r.status_code in (401, 403), "expired session cannot change the password either"
    async with _client() as c:
        req = await c.post(
            f"{API}/auth/password-reset/request", json={"phone": m["phone"]}, headers=idem()
        )
        assert req.status_code == 202, req.text
        tok = await c.post(
            f"{API}/auth/password-reset/verify",
            json={"phone": m["phone"], "otp": req.json()["test_otp"]},
            headers=idem(),
        )
        assert tok.status_code == 200, tok.text
        done = await c.post(
            f"{API}/auth/password-reset/confirm",
            json={"reset_token": tok.json()["reset_token"], "password": "Hv-Reset-Pass-1"},
            headers=idem(),
        )
        assert done.status_code == 204, done.text
        assert (await sign_in(c, m["phone"], "Hv-Reset-Pass-1")).status_code == 200
        assert (await c.get(f"{API}/me/member")).status_code == 200, "flag cleared after the reset"


async def test_account_registered_before_the_club_cannot_read_the_member_card(admin, made):
    """Ai đó đăng ký trước bằng SĐT của hội viên (không OTP) rồi sân mới thêm hội viên."""
    phone = random_phone()
    made.append(phone)
    async with _client() as attacker:
        await db_account(
            attacker, phone, "Kẻ đăng ký trước", "Ke-Tan-Cong-1"
        )  # T-021: /auth/register đóng
        m = await add_ok(admin, made, phone=phone)
        row = (
            await q(
                "SELECT must_change_password AS m, member_account_at IS NULL AS no_stamp FROM users WHERE phone=:p",
                p=phone,
            )
        )[0]
        assert row["m"] is False and row["no_stamp"], "the existing account is left alone"
        card = await attacker.get(f"{API}/me/member")
        assert card.status_code == 403, "unverified phone cannot read the member card"
        assert (await attacker.get(f"{API}/me/member/bookings")).status_code == 403
    assert m["member_code"]


async def test_member_card_is_only_the_own_one(admin, made):
    a = await add_ok(admin, made)
    b = await add_ok(admin, made)
    async with _client() as ca:
        await sign_in(ca, a["phone"], a["phone"])
        await pw_change(ca, "Hv-Moi-Pass-1")
        card = (await ca.get(f"{API}/me/member")).json()
        assert card["member_code"] == a["member_code"]
        assert b["phone"] not in str(card) and b["member_code"] not in str(card)
        for probe in (
            f"{API}/me/member?ref={b['member_code']}",
            f"{API}/me/member?phone={b['phone']}",
        ):
            got = (await ca.get(probe)).json()
            assert got["member_code"] == a["member_code"], "query parameters are ignored"
        assert (await ca.get(f"{M}/{b['member_code']}")).status_code in (401, 403)
        assert (await ca.get(M)).status_code in (401, 403)
        assert (await ca.get(f"{API}/rackets")).status_code == 200, (
            "T-016: hội viên đọc được danh mục vợt"
        )


async def test_temp_profile_has_no_card_until_the_owner_verifies_by_otp(admin, made):
    t = (await add_temp(admin, made)).json()
    async with _client() as c:
        await db_account(c, t["phone"], "Có tạm", "Co-Tam-Pass-1")
        await x(
            "UPDATE users SET phone_verified_at = now() WHERE phone=:p", p=t["phone"]
        )  # xác minh giả, không qua OTP
        assert (await c.get(f"{API}/me/member")).status_code == 404, "hồ sơ tạm chưa phải hội viên"
        # T-021 R1: chủ SĐT tự xác minh bằng OTP → được nâng lên hội viên
        req = await c.post(f"{API}/web/booking/phone/request", json={"phone": t["phone"]})
        ver = await c.post(
            f"{API}/web/booking/phone/verify",
            json={"phone": t["phone"], "otp": req.json()["test_otp"]},
        )
        assert ver.status_code == 200 and ver.json()["became_member"] is True, ver.text
        card = await c.get(f"{API}/me/member")
        assert card.status_code == 200 and card.json()["member_code"] == ver.json()["member_code"]


# ============================================================ đồng thời


async def test_concurrent_create_same_phone_one_wins_no_500(admin, made):
    import asyncio

    phone = random_phone()
    made.append(phone)
    res = await asyncio.gather(
        *[
            admin.post(M, json={"full_name": f"{tag()} Race", "phone": phone}, headers=idem())
            for _ in range(6)
        ]
    )
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    assert (await q("SELECT count(*) AS n FROM customer WHERE phone=:p", p=phone))[0]["n"] == 1


async def test_concurrent_create_different_phones_get_distinct_codes(admin, made):
    import asyncio

    res = await asyncio.gather(*[add_member(admin, made) for _ in range(8)])
    assert [r.status_code for r in res] == [201] * 8, [r.text for r in res if r.status_code != 201]
    assert len({r.json()["member_code"] for r in res}) == 8


async def test_concurrent_temp_and_member_same_phone_never_two_rows(admin, made):
    import asyncio

    phone = random_phone()
    made.append(phone)
    res = await asyncio.gather(
        admin.post(M, json={"full_name": f"{tag()} M", "phone": phone}, headers=idem()),
        admin.post(f"{M}/temp", json={"full_name": f"{tag()} T", "phone": phone}, headers=idem()),
    )
    assert all(r.status_code in (201, 409) for r in res), [r.text for r in res]
    assert (await q("SELECT count(*) AS n FROM customer WHERE phone=:p", p=phone))[0]["n"] == 1


async def test_concurrent_edits_do_not_silently_overwrite(admin, made):
    """T-020 AC4: hai máy cùng mở một bản; máy lưu sau nhận 409 E-MEM-9 và không ghi đè."""
    m = await add_ok(admin, made, gender="male")
    path = f"{M}/{m['member_code']}"
    v = (await admin.get(path)).json()["version"]
    name_a = f"{tag()} Máy A"
    a = await patch_m(admin, path, {"full_name": name_a}, version=v)
    b = await patch_m(admin, path, {"full_name": f"{tag()} Máy B"}, version=v)
    assert a.status_code == 200 and b.status_code == 409 and err(b)["code"] == "E-MEM-9", b.text
    assert err(b)["message"].startswith("Hội viên này vừa được cập nhật ở máy khác")
    assert (await admin.get(path)).json()["full_name"] == name_a, "máy A không bị ghi đè"


async def test_ac4_version_rules_missing_stale_noop_bump_and_shared_with_member_area(admin, made):
    from tests.conftest import _client, sign_in

    m = await add_ok(admin, made, tier="Khá")
    path = f"{M}/{m['member_code']}"
    d = (await admin.get(path)).json()
    assert (
        isinstance(d["version"], int)
        and (await listing(admin, q=m["member_code"]))["items"][0]["version"] == d["version"]
    )
    r = await admin.patch(path, json={"full_name": f"{tag()} X"}, headers=idem())
    assert r.status_code == 422, "version bắt buộc"
    same = await patch_m(admin, path, {"full_name": d["full_name"]}, version=d["version"])
    assert same.status_code == 200 and same.json()["version"] == d["version"], (
        "không đổi gì thì giữ version"
    )
    up = await patch_m(admin, path, {"tier": "Bán chuyên"}, version=d["version"])
    assert up.status_code == 200 and up.json()["version"] == d["version"] + 1
    stale = await patch_m(admin, path, {"tier": "Khá"}, version=d["version"])
    assert stale.status_code == 409 and err(stale)["code"] == "E-MEM-9"
    # dùng chung version với khu hội viên: hội viên tự sửa thì quản trị đang mở bản cũ bị 409
    cur = (await admin.get(path)).json()
    async with _client() as c:
        assert (await sign_in(c, m["phone"], m["phone"])).status_code == 200
        await c.post(
            f"{API}/auth/password/change", json={"new_password": "Hv-Moi-Pass-1"}, headers=idem()
        )
        mine = (await c.get(f"{API}/member-area/me")).json()
        assert mine["version"] == cur["version"], "cùng một cột version"
        body = {
            k: mine[k]
            for k in (
                "full_name",
                "nickname",
                "email",
                "tier",
                "racket",
                "show_on_records",
                "version",
            )
        }
        assert (
            await c.put(
                f"{API}/member-area/me", json={**body, "nickname": "Tự sửa"}, headers=idem()
            )
        ).status_code == 200
    late = await patch_m(admin, path, {"tier": "Yếu"}, version=cur["version"])
    assert late.status_code == 409 and err(late)["code"] == "E-MEM-9"


async def test_ac3_idempotency_key_required_and_replay_returns_same_result(admin, made):
    phone = random_phone()
    made.append(phone)
    body = {"full_name": f"{tag()} Idem", "phone": phone}
    r = await admin.post(M, json=body)  # thiếu Idempotency-Key
    assert r.status_code == 400 and err(r)["code"] == "E-SEC-2", r.text
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r1 = await admin.post(M, json=body, headers=key)
    r2 = await admin.post(M, json=body, headers=key)
    assert r1.status_code == 201 and r2.status_code == 201 and r2.json() == r1.json()
    assert r2.headers.get("idempotent-replayed") == "true"
    assert (await q("SELECT count(*) AS n FROM customer WHERE phone=:p", p=phone))[0]["n"] == 1
    # hồ sơ tạm
    tp = random_phone()
    made.append(tp)
    tb = {"full_name": f"{tag()} Tạm", "phone": tp}
    assert (await admin.post(f"{M}/temp", json=tb)).status_code == 400
    k2 = {"Idempotency-Key": str(uuid.uuid4())}
    t1 = await admin.post(f"{M}/temp", json=tb, headers=k2)
    t2 = await admin.post(f"{M}/temp", json=tb, headers=k2)
    assert t1.status_code == 201 and t2.status_code == 201 and t2.json() == t1.json()
    # cùng key nhưng nội dung khác không được trả kết quả của lần trước
    other = await admin.post(
        M, json={"full_name": f"{tag()} Khác", "phone": random_phone()}, headers=key
    )
    assert other.status_code in (409, 422), "key cũ + body khác bị từ chối, không lẫn kết quả"


async def test_ac2_t020_inactive_member_can_get_a_ticket_and_online_booking_still_links(
    admin, made, anon, sepay
):
    t6 = importlib.import_module("tests.test_qa_T-006")
    t8 = importlib.import_module("tests.test_qa_T-008")
    m = await add_ok(admin, made)
    assert (
        await patch_m(admin, f"{M}/{m['member_code']}", {"is_active": False})
    ).status_code == 200
    # vé sự kiện tại quầy
    court = await new_court(admin)
    ev = await t6.new_session(admin, [court["code"]], capacity=3, hour=t6.usable_hour())
    if ev.status_code == 201:
        tk = await admin.post(
            f"{API}/front-desk/sessions/{ev.json()['code']}/tickets",
            json={"customer": {"member_code": m["member_code"]}},
            headers=idem(),
        )
        assert tk.status_code == 201, tk.text
        assert tk.json()["customer"]["kind"] == "member"
    # đặt online bằng đúng SĐT của hội viên Ngừng vẫn gắn vào hội viên
    court2 = await t8.court(admin)
    r = await t8.checkout(anon, t8.slots(court2["code"], 9), ph=m["phone"], name=m["full_name"])
    assert r.status_code == 201, r.text
    if True:
        row = await q(
            "SELECT customer_kind, member_code FROM booking.checkout WHERE pay_ref=:p",
            p=r.json()["pay_ref"],
        )
        assert row[0]["customer_kind"] == "member" and row[0]["member_code"] == m["member_code"], (
            row
        )

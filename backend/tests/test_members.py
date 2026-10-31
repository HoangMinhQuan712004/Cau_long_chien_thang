"""T-014 / T-020: màn Hội viên – danh sách, chi tiết + thống kê, thêm / sửa, hồ sơ tạm."""

import asyncio
import datetime as dt
import uuid

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine.api import customer_stats
from app.modules.booking_engine.models import Checkout
from app.modules.members.models import Customer
from tests.conftest import API, idem
from tests.helpers_booking import (
    BK,
    FD,
    book,
    member,
    new_court,
    patch_member,
    random_phone,
    safe_hour,
    today,
)
from tests.helpers_web import checkout

M = f"{API}/members"


@pytest.fixture
async def phones():
    """SĐT test tạo ra -> xóa hồ sơ sau test (mã HV không phình theo số lần chạy)."""
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.commit()


def name() -> str:
    return f"HV Test {uuid.uuid4().hex[:8]}"


async def add_member(client, phones: list[str], **fields) -> dict:
    phone = fields.pop("phone", None) or random_phone()
    phones.append(phone)
    r = await client.post(M, json={"full_name": name(), "phone": phone, **fields}, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


async def add_temp(client, phones: list[str], phone: str | None = None) -> dict:
    phone = phone or random_phone()
    phones.append(phone)
    r = await client.post(f"{M}/temp", json={"full_name": name(), "phone": phone}, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ quyền


async def test_requires_admin_session(anon, customer):
    for client in (anon, customer):
        r = await client.get(M)
        assert r.status_code in (401, 403)
        assert (
            await client.post(f"{M}/temp", json={"full_name": "A", "phone": "0"}, headers=idem())
        ).status_code in (401, 403)


async def test_staff_can_set_tier_but_not_status(staff, admin, phones):
    listing = (await staff.get(M)).json()
    assert listing["can"] == {"edit_status": False, "manage_rackets": False}
    assert (await admin.get(M)).json()["can"] == {"edit_status": True, "manage_rackets": True}

    row = await add_member(staff, phones)
    assert row["tier"] is None and row["kind"] == "member"  # mặc định chưa xếp hạng
    row = await add_member(staff, phones, tier="Trung bình yếu")  # 14 ký tự (cột 20)
    assert row["tier"] == "Trung bình yếu"

    code = row["member_code"]
    r = await patch_member(staff, code, {"tier": "Khá"})
    assert r.status_code == 200 and r.json()["tier"] == "Khá"
    r = await patch_member(staff, code, {"tier": None})
    assert r.status_code == 200 and r.json()["tier"] is None
    r = await patch_member(staff, code, {"is_active": False})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    # Gửi lại đúng giá trị cũ (form gửi cả form) thì không coi là đổi
    r = await patch_member(staff, code, {"is_active": True, "racket": "Yonex"})
    assert r.status_code == 200 and r.json()["racket"] == "Yonex"
    assert (await patch_member(staff, code, {"tier": "Vàng"})).status_code == 422

    r = await patch_member(admin, code, {"tier": "Chuyên nghiệp", "is_active": False})
    assert r.status_code == 200
    assert (r.json()["tier"], r.json()["is_active"]) == ("Chuyên nghiệp", False)


# ------------------------------------------------------------------ thêm / sửa


async def test_create_member_fields_and_next_code(admin, phones):
    expected = (await admin.get(f"{M}/next-code")).json()["member_code"]
    phone = random_phone()
    row = await add_member(
        admin, phones, phone=f"+84 {phone[1:4]}.{phone[4:]}", gender="female", racket="  Lining  "
    )
    assert row["member_code"] == expected == row["ref"]
    assert row["phone"] == phone  # chuẩn hóa, không che
    assert (row["gender"], row["racket"], row["bookings"]) == ("female", "Lining", 0)
    assert "id" not in row
    next_code = (await admin.get(f"{M}/next-code")).json()["member_code"]
    assert int(next_code[2:]) == int(expected[2:]) + 1


async def test_create_validation_and_duplicate_phone(admin, phones):
    for body, code in (
        ({"full_name": "  ", "phone": random_phone()}, "E-001"),
        ({"full_name": "A", "phone": ""}, "E-001"),
        ({"full_name": "A", "phone": "12345"}, "E-002"),
    ):
        r = await admin.post(M, json=body, headers=idem())
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert (
        await admin.post(
            M, json={"full_name": "A", "phone": random_phone(), "tier": "X"}, headers=idem()
        )
    ).status_code == 422

    m = await add_member(admin, phones)
    phone = phones[-1]
    r = await admin.post(M, json={"full_name": "B", "phone": phone}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-018"
    assert m["member_code"] in r.json()["detail"]["message"]

    t = await add_temp(admin, phones)
    r = await admin.post(M, json={"full_name": "B", "phone": phones[-1]}, headers=idem())
    detail = r.json()["detail"]
    assert r.status_code == 409 and detail["code"] == "E-MEM-1" and detail["ref"] == t["ref"]
    assert detail["full_name"] == t["full_name"]
    assert detail["message"].startswith(f"Số điện thoại đã có hồ sơ tạm: {t['full_name']} (tạo ")


async def test_update_member_cannot_change_phone(admin, phones):
    a = await add_member(admin, phones)
    phone = phones[-1]
    r = await patch_member(admin, a["member_code"], {"phone": random_phone()})
    assert r.status_code == 422  # StrictIn: không có trường phone
    r = await patch_member(admin, a["member_code"].lower(), {"full_name": " Tên  Mới "})
    assert r.status_code == 200 and r.json()["full_name"] == "Tên Mới"
    detail = (await admin.get(f"{M}/{a['member_code']}")).json()
    assert detail["phone"] == phone
    assert (await patch_member(admin, "HV9998", {"racket": "x"})).status_code == 404
    t = await add_temp(admin, phones)
    for body in ({"racket": "x"}, {"tier": "Khá"}, {"is_active": False}):
        r = await patch_member(admin, t["ref"], body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-MEM-6", body


async def test_concurrent_create_gets_distinct_codes(admin, phones):
    bodies = [{"full_name": name(), "phone": random_phone()} for _ in range(4)]
    phones.extend(b["phone"] for b in bodies)
    results = await asyncio.gather(*(admin.post(M, json=b, headers=idem()) for b in bodies))
    assert [r.status_code for r in results] == [201] * 4
    assert len({r.json()["member_code"] for r in results}) == 4


@pytest.mark.parametrize("path", ["", "/temp"])
async def test_concurrent_same_phone_one_wins(admin, phones, path):
    """Hai máy lưu cùng SĐT: UNIQUE(phone) bắt -> một 201, một 409 (không 500)."""
    phone = random_phone()
    phones.append(phone)
    results = await asyncio.gather(
        *(
            admin.post(f"{M}{path}", json={"full_name": name(), "phone": phone}, headers=idem())
            for _ in range(2)
        )
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["detail"]["code"] in ("E-018", "E-MEM-1")


async def test_stats_many_refs_single_parameter():
    """BE-1: 40.000 ref (> 32.767 tham số asyncpg) vẫn chạy – truyền một mảng."""
    async with SessionLocal() as s:
        stats = await customer_stats(s, [f"phone:{i}" for i in range(40_000)])
    assert stats == {}


# ------------------------------------------------------------------ hồ sơ tạm + chuyển


async def test_temp_create_and_duplicates(staff, admin, phones):
    t = await add_temp(staff, phones)
    assert t["kind"] == "temp" and t["member_code"] is None and t["tier"] is None
    uuid.UUID(t["ref"])  # mã tham chiếu mờ, không phải id
    assert (await staff.get(f"{M}/{t['ref']}")).status_code == 200
    async with SessionLocal() as s:
        actions = set(
            await s.scalars(select(AuditLog.action).where(AuditLog.entity_code == t["ref"]))
        )
    assert actions == {"member.temp.create", "member.view"}  # nhật ký biết hồ sơ nào
    # Hồ sơ tạm: NV sửa được họ tên + giới tính
    r = await patch_member(staff, t["ref"], {"full_name": " Tạm  Mới ", "gender": "female"})
    assert r.status_code == 200
    assert (r.json()["full_name"], r.json()["gender"], r.json()["kind"]) == (
        "Tạm Mới",
        "female",
        "temp",
    )
    r = await staff.post(f"{M}/temp", json={"full_name": "X", "phone": phones[-1]}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-1"
    await add_member(admin, phones)
    r = await staff.post(f"{M}/temp", json={"full_name": "X", "phone": phones[-1]}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-018"


async def test_member_with_temp_phone_is_blocked_no_upgrade(admin, staff, phones):
    """T-020 AC1: không còn nâng hồ sơ tạm – SĐT đã có hồ sơ tạm -> E-MEM-1 (SRS E-004)."""
    t = await add_temp(admin, phones)
    body = {"full_name": "Khách Muốn Làm HV", "phone": phones[-1], "tier": "Khá"}
    r = await staff.post(M, json=body, headers=idem())
    assert r.status_code == 409
    detail = r.json()["detail"]
    created = dt.datetime.now(settings.tz).strftime("%d/%m/%Y")
    assert detail["code"] == "E-MEM-1"
    assert detail["message"] == f"Số điện thoại đã có hồ sơ tạm: {t['full_name']} (tạo {created})"
    # Trường upgrade_temp đã gỡ -> 422; hồ sơ vẫn là hồ sơ tạm
    r = await staff.post(M, json={**body, "upgrade_temp": True}, headers=idem())
    assert r.status_code == 422
    listing = (await staff.get(M, params={"q": phones[-1]})).json()
    assert [i["kind"] for i in listing["items"]] == ["temp"]


async def test_list_filters_counts_and_masking(admin, phones):
    tag = uuid.uuid4().hex[:6]
    for i in range(3):
        phone = random_phone()
        phones.append(phone)
        tier = "Trung bình +" if i else None
        await admin.post(
            M, json={"full_name": f"Lọc {tag} {i}", "phone": phone, "tier": tier}, headers=idem()
        )
    phone = random_phone()
    phones.append(phone)
    await admin.post(
        f"{M}/temp", json={"full_name": f"Lọc {tag} tạm", "phone": phone}, headers=idem()
    )
    first = (await admin.get(M, params={"q": f"lọc {tag}"})).json()
    member_ref = next(i["ref"] for i in first["items"] if i["kind"] == "member")
    await patch_member(admin, member_ref, {"is_active": False})

    data = (await admin.get(M, params={"q": tag})).json()
    assert data["counts"] == {"all": 4, "member": 3, "temp": 1} and data["total"] == 4
    assert all("xxx" not in i["phone"] and "id" not in i for i in data["items"])
    assert [i["kind"] for i in data["items"]] == ["temp"] + ["member"] * 3  # mới nhất trước
    temps = (await admin.get(M, params={"q": tag, "kind": "temp"})).json()
    assert temps["total"] == 1 and temps["counts"]["all"] == 4
    assert (await admin.get(M, params={"q": tag, "status": "inactive"})).json()["total"] == 1
    assert (await admin.get(M, params={"q": tag, "tier": "Trung bình +"})).json()["total"] == 2
    # Chưa xếp hạng: HV số 0 + hồ sơ tạm
    assert (await admin.get(M, params={"q": tag, "tier": "none"})).json()["total"] == 2
    assert (await admin.get(M, params={"tier": "Bạc"})).status_code == 422
    page = (await admin.get(M, params={"q": tag, "size": 3, "page": 2})).json()
    assert len(page["items"]) == 1 and page["total"] == 4
    by_phone = (await admin.get(M, params={"q": phone[-6:]})).json()
    assert by_phone["items"][0]["kind"] == "temp"
    assert (await admin.get(M, params={"size": 101})).status_code == 422


async def test_sort_by_bookings_and_detail(admin, staff, phones):
    court = await new_court(admin)
    hour = await safe_hour()
    tag = uuid.uuid4().hex[:6]
    rows = []
    for i in range(2):
        phone = random_phone()
        phones.append(phone)
        r = await admin.post(
            M, json={"full_name": f"Sắp {tag} {i}", "phone": phone}, headers=idem()
        )
        rows.append(r.json())
    r = await book(staff, court["code"], hour, customer=member(rows[1]["member_code"]))
    assert r.status_code == 201, r.text
    data = (await admin.get(M, params={"q": tag, "sort": "bookings"})).json()
    assert [i["member_code"] for i in data["items"]] == [
        rows[1]["member_code"],
        rows[0]["member_code"],
    ]
    assert [i["bookings"] for i in data["items"]] == [1, 0]

    detail = (await staff.get(f"{M}/{rows[1]['member_code']}")).json()
    assert detail["phone"] == phones[-1] and detail["total_minutes"] == 60
    recent = detail["recent_bookings"][0]
    assert recent["code"] == r.json()["code"] and recent["resource_name"] == court["name"]
    assert "id" not in detail
    async with SessionLocal() as s:
        viewed = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "member.view", AuditLog.entity_code == rows[1]["member_code"])
        )
    assert viewed == 1
    assert (await admin.get(f"{M}/HV9997")).status_code == 404
    assert (await admin.get(f"{M}/{uuid.uuid4()}")).status_code == 404
    assert (await admin.get(f"{M}/123")).status_code == 404


# ------------------------------------------------------------------ đặt tại quầy (việc 3)


async def test_inactive_member_still_books_at_counter(admin, staff, phones):
    """T-020 AC2: hội viên Ngừng vẫn đặt quầy được, snapshot vẫn là hội viên."""
    court = await new_court(admin)
    m = await add_member(admin, phones)
    await patch_member(admin, m["member_code"], {"is_active": False})
    found = (await staff.get(f"{M}/search", params={"q": m["member_code"]})).json()
    assert found[0]["is_active"] is False  # popup Chọn hội viên hiện nhãn Ngừng
    r = await book(staff, court["code"], await safe_hour(), customer=member(m["member_code"]))
    assert r.status_code == 201, r.text
    assert r.json()["customer"]["kind"] == "member"
    assert r.json()["customer"]["member_code"] == m["member_code"]


async def test_unrated_member_label_has_no_tier(admin, staff, phones):
    court = await new_court(admin)
    m = await add_member(admin, phones)
    r = await book(staff, court["code"], await safe_hour(), customer=member(m["member_code"]))
    assert r.status_code == 201, r.text
    customer = r.json()["customer"]
    assert customer["profile_label"] == f"Hội viên ({m['member_code']})"
    assert customer["tier"] is None


# ------------------------------------------------------------------ T-020 AC2–AC4


@pytest.mark.parametrize("path", ["", "/temp"])
async def test_replay_same_key_returns_same_result(admin, phones, path):
    """AC3: gửi lại cùng Idempotency-Key -> 201 cùng kết quả, không báo E-018 / E-MEM-1."""
    phone = random_phone()
    phones.append(phone)
    headers = idem()
    body = {"full_name": name(), "phone": phone}
    first = await admin.post(f"{M}{path}", json=body, headers=headers)
    again = await admin.post(f"{M}{path}", json=body, headers=headers)
    assert first.status_code == again.status_code == 201, again.text
    assert again.json() == first.json()
    assert again.headers.get("idempotent-replayed") == "true"
    assert (await admin.get(M, params={"q": phone})).json()["total"] == 1
    # Thiếu Idempotency-Key -> 400 E-SEC-2
    r = await admin.post(f"{M}{path}", json={"full_name": name(), "phone": random_phone()})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "E-SEC-2"


async def test_patch_uses_version(admin, staff, phones):
    """AC4: PATCH kèm version; lệch -> 409 E-MEM-9, không ghi đè; khu hội viên dùng chung."""
    m = await add_member(admin, phones)
    code = m["member_code"]
    assert m["version"] == 1
    r = await staff.patch(f"{M}/{code}", json={"tier": "Khá"})
    assert r.status_code == 422  # thiếu version
    r = await staff.patch(f"{M}/{code}", json={"tier": "Khá", "version": 1})
    assert r.status_code == 200 and r.json()["version"] == 2
    # Máy khác vẫn cầm version 1
    r = await admin.patch(f"{M}/{code}", json={"full_name": "Ghi Đè", "version": 1})
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-MEM-9",
        "message": "Hội viên này vừa được cập nhật ở máy khác. Tải lại để xem bản mới nhất.",
    }
    detail = (await admin.get(f"{M}/{code}")).json()
    assert detail["tier"] == "Khá" and detail["full_name"] != "Ghi Đè" and detail["version"] == 2
    # Không đổi gì -> không tăng version
    r = await admin.patch(f"{M}/{code}", json={"tier": "Khá", "version": 2})
    assert r.status_code == 200 and r.json()["version"] == 2
    # Hội viên tự sửa ở khu hội viên tăng cùng version (giả lập) -> quản trị bị chặn
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.member_code == code)
            .values(version=Customer.version + 1)
        )
        await s.commit()
    r = await admin.patch(f"{M}/{code}", json={"tier": "Yếu", "version": 2})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-9"


async def test_inactive_member_ticket_and_online_still_attach(admin, staff, anon, phones):
    """AC2: hội viên Ngừng đăng ký vé tại quầy được; đặt online bằng SĐT vẫn gắn hội viên."""
    m = await add_member(admin, phones)
    phone = phones[-1]
    await patch_member(admin, m["member_code"], {"is_active": False})

    court = await new_court(admin)
    hour = await safe_hour()
    ev = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": today().isoformat(),
            "start_hour": hour,
            "end_hour": hour + 1,
            "name": "Giao lưu",
            "capacity": 5,
            "ticket_price": 40_000,
        },
        headers=idem(),
    )
    r = await staff.post(
        f"{FD}/sessions/{ev.json()['code']}/tickets",
        json={"customer": {"member_code": m["member_code"]}},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["customer"]["kind"] == "member"

    other = await new_court(admin)
    r = await checkout(anon, [(other["code"], 19)], phone=phone)
    assert r.status_code == 201, r.text
    async with SessionLocal() as s:
        co = await s.scalar(select(Checkout).where(Checkout.customer_phone == phone))
    assert co.customer_kind == "member" and co.member_code == m["member_code"]

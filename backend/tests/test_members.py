"""T-014: màn Hội viên – danh sách, chi tiết + thống kê, thêm / sửa, hồ sơ tạm, nâng hồ sơ tạm."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.api import customer_stats
from app.modules.booking_engine.models import Booking
from app.modules.members.models import Customer
from tests.conftest import API
from tests.helpers_booking import book, member, new_court, random_phone, safe_hour, temp

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
    r = await client.post(M, json={"full_name": name(), "phone": phone, **fields})
    assert r.status_code == 201, r.text
    return r.json()


async def add_temp(client, phones: list[str], phone: str | None = None) -> dict:
    phone = phone or random_phone()
    phones.append(phone)
    r = await client.post(f"{M}/temp", json={"full_name": name(), "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ quyền


async def test_requires_admin_session(anon, customer):
    for client in (anon, customer):
        r = await client.get(M)
        assert r.status_code in (401, 403)
        assert (
            await client.post(f"{M}/temp", json={"full_name": "A", "phone": "0"})
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
    r = await staff.patch(f"{M}/{code}", json={"tier": "Khá"})
    assert r.status_code == 200 and r.json()["tier"] == "Khá"
    r = await staff.patch(f"{M}/{code}", json={"tier": None})
    assert r.status_code == 200 and r.json()["tier"] is None
    r = await staff.patch(f"{M}/{code}", json={"is_active": False})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    # Gửi lại đúng giá trị cũ (form gửi cả form) thì không coi là đổi
    r = await staff.patch(f"{M}/{code}", json={"is_active": True, "racket": "Yonex"})
    assert r.status_code == 200 and r.json()["racket"] == "Yonex"
    assert (await staff.patch(f"{M}/{code}", json={"tier": "Vàng"})).status_code == 422

    r = await admin.patch(f"{M}/{code}", json={"tier": "Chuyên nghiệp", "is_active": False})
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
    assert row["phone_masked"] == f"{phone[:4]} xxx {phone[-3:]}"
    assert (row["gender"], row["racket"], row["bookings"]) == ("female", "Lining", 0)
    assert "id" not in row and "phone" not in row
    next_code = (await admin.get(f"{M}/next-code")).json()["member_code"]
    assert int(next_code[2:]) == int(expected[2:]) + 1


async def test_create_validation_and_duplicate_phone(admin, phones):
    for body, code in (
        ({"full_name": "  ", "phone": random_phone()}, "E-001"),
        ({"full_name": "A", "phone": ""}, "E-001"),
        ({"full_name": "A", "phone": "12345"}, "E-002"),
    ):
        r = await admin.post(M, json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code
    assert (
        await admin.post(M, json={"full_name": "A", "phone": random_phone(), "tier": "X"})
    ).status_code == 422

    m = await add_member(admin, phones)
    phone = phones[-1]
    r = await admin.post(M, json={"full_name": "B", "phone": phone})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-018"
    assert m["member_code"] in r.json()["detail"]["message"]

    t = await add_temp(admin, phones)
    r = await admin.post(M, json={"full_name": "B", "phone": phones[-1]})
    detail = r.json()["detail"]
    assert r.status_code == 409 and detail["code"] == "E-MEM-1" and detail["ref"] == t["ref"]
    assert detail["full_name"] == t["full_name"] and detail["bookings"] == 0
    assert detail["next_code"] == (await admin.get(f"{M}/next-code")).json()["member_code"]


async def test_update_member_cannot_change_phone(admin, phones):
    a = await add_member(admin, phones)
    phone = phones[-1]
    r = await admin.patch(f"{M}/{a['member_code']}", json={"phone": random_phone()})
    assert r.status_code == 422  # StrictIn: không có trường phone
    r = await admin.patch(f"{M}/{a['member_code'].lower()}", json={"full_name": " Tên  Mới "})
    assert r.status_code == 200 and r.json()["full_name"] == "Tên Mới"
    detail = (await admin.get(f"{M}/{a['member_code']}")).json()
    assert detail["phone"] == phone
    assert (await admin.patch(f"{M}/HV9998", json={"racket": "x"})).status_code == 404
    t = await add_temp(admin, phones)
    for body in ({"racket": "x"}, {"tier": "Khá"}, {"is_active": False}):
        r = await admin.patch(f"{M}/{t['ref']}", json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-MEM-6", body


async def test_concurrent_create_gets_distinct_codes(admin, phones):
    bodies = [{"full_name": name(), "phone": random_phone()} for _ in range(4)]
    phones.extend(b["phone"] for b in bodies)
    results = await asyncio.gather(*(admin.post(M, json=b) for b in bodies))
    assert [r.status_code for r in results] == [201] * 4
    assert len({r.json()["member_code"] for r in results}) == 4


@pytest.mark.parametrize("path", ["", "/temp"])
async def test_concurrent_same_phone_one_wins(admin, phones, path):
    """Hai máy lưu cùng SĐT: UNIQUE(phone) bắt -> một 201, một 409 (không 500)."""
    phone = random_phone()
    phones.append(phone)
    results = await asyncio.gather(
        *(admin.post(f"{M}{path}", json={"full_name": name(), "phone": phone}) for _ in range(2))
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
    r = await staff.patch(f"{M}/{t['ref']}", json={"full_name": " Tạm  Mới ", "gender": "female"})
    assert r.status_code == 200
    assert (r.json()["full_name"], r.json()["gender"], r.json()["kind"]) == (
        "Tạm Mới",
        "female",
        "temp",
    )
    r = await staff.post(f"{M}/temp", json={"full_name": "X", "phone": phones[-1]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-1"
    await add_member(admin, phones)
    r = await staff.post(f"{M}/temp", json={"full_name": "X", "phone": phones[-1]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-018"


async def test_upgrade_temp_keeps_history_and_audits(admin, staff, phones):
    courts = [await new_court(admin), await new_court(admin)]
    hour = await safe_hour()
    phone = random_phone()
    phones.append(phone)
    # 2 lượt tại quầy (tạo hồ sơ tạm, ref = id); lượt đầu đổi thành ref online ``phone:<sđt>``
    codes = []
    for court in courts:
        r = await book(staff, court["code"], hour, customer=temp("Khách Chuyển", phone))
        assert r.status_code == 201, r.text
        codes.append(r.json()["code"])
    async with SessionLocal() as s:
        await s.execute(
            update(Booking).where(Booking.code == codes[0]).values(customer_ref=f"phone:{phone}")
        )
        await s.commit()
    listing = (await staff.get(M, params={"q": phone, "kind": "temp"})).json()
    row = listing["items"][0]
    expected = 2
    assert row["bookings"] == expected

    body = {"full_name": "Khách Đã Chuyển", "phone": phone, "gender": "male", "tier": "Khá"}
    r = await staff.post(M, json=body)
    assert r.status_code == 409 and r.json()["detail"]["bookings"] == expected  # hỏi xác nhận
    # Hai máy cùng xác nhận nâng: khóa dòng -> một 201, máy kia E-MEM-3 (không 500)
    results = await asyncio.gather(
        *(staff.post(M, json={**body, "upgrade_temp": True}) for _ in range(2))
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    promoted = next(r for r in results if r.status_code == 201).json()
    loser = next(r for r in results if r.status_code == 409).json()
    assert loser["detail"]["code"] == "E-MEM-3"
    assert promoted["kind"] == "member" and promoted["tier"] == "Khá"
    assert promoted["bookings"] == expected and promoted["ref"] == promoted["member_code"]
    assert promoted["full_name"] == "Khách Đã Chuyển"
    assert (await staff.get(M, params={"q": phone})).json()["total"] == 1  # cùng một dòng

    detail = (await admin.get(f"{M}/{promoted['member_code']}")).json()
    assert detail["bookings"] == expected and len(detail["recent_bookings"]) == expected
    assert detail["total_minutes"] == 60 * expected
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "member.promote", AuditLog.entity_code == promoted["member_code"]
            )
        )
    assert n == 1


# ------------------------------------------------------------------ danh sách + chi tiết


async def test_list_filters_counts_and_masking(admin, phones):
    tag = uuid.uuid4().hex[:6]
    for i in range(3):
        phone = random_phone()
        phones.append(phone)
        tier = "Trung bình +" if i else None
        await admin.post(M, json={"full_name": f"Lọc {tag} {i}", "phone": phone, "tier": tier})
    phone = random_phone()
    phones.append(phone)
    await admin.post(f"{M}/temp", json={"full_name": f"Lọc {tag} tạm", "phone": phone})
    first = (await admin.get(M, params={"q": f"lọc {tag}"})).json()
    member_ref = next(i["ref"] for i in first["items"] if i["kind"] == "member")
    await admin.patch(f"{M}/{member_ref}", json={"is_active": False})

    data = (await admin.get(M, params={"q": tag})).json()
    assert data["counts"] == {"all": 4, "member": 3, "temp": 1} and data["total"] == 4
    assert all("xxx" in i["phone_masked"] and "id" not in i for i in data["items"])
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
        r = await admin.post(M, json={"full_name": f"Sắp {tag} {i}", "phone": phone})
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


async def test_inactive_member_blocked_at_counter(admin, staff, phones):
    court = await new_court(admin)
    m = await add_member(admin, phones)
    await admin.patch(f"{M}/{m['member_code']}", json={"is_active": False})
    r = await book(staff, court["code"], await safe_hour(), customer=member(m["member_code"]))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-MEM-2"


async def test_unrated_member_label_has_no_tier(admin, staff, phones):
    court = await new_court(admin)
    m = await add_member(admin, phones)
    r = await book(staff, court["code"], await safe_hour(), customer=member(m["member_code"]))
    assert r.status_code == 201, r.text
    customer = r.json()["customer"]
    assert customer["profile_label"] == f"Hội viên ({m['member_code']})"
    assert customer["tier"] is None

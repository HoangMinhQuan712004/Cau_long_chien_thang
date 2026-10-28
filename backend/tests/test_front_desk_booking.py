"""T-006 phần 1: lịch ngày, tìm hội viên, đặt tại quầy, tìm mã, thông tin booking."""

import asyncio
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.api import expire_holds
from app.modules.booking_engine.models import Booking
from app.modules.booking_engine.testing import make_hold
from app.modules.members.models import Customer
from tests.conftest import API, idem, is_staff_label
from tests.helpers_booking import (
    BK,
    at,
    book,
    calendar,
    member,
    new_court,
    random_phone,
    safe_hour,
    temp,
    today,
)

# ------------------------------------------------------------------ lịch (BR-001, 002, 004)


async def test_calendar_seed_layout(staff):
    cal = await calendar(staff)
    codes = [r["code"] for r in cal["resources"]]
    assert codes[:5] == ["S01", "S02", "S03", "S04", "S05"]
    assert "S06" not in codes  # sân ngừng, không có chỗ chiếm
    s05 = next(r for r in cal["resources"] if r["code"] == "S05")
    assert 5 in s05["off_hours"]  # S05 mở 06:00 -> ô 05:00 Xám
    s01 = next(r for r in cal["resources"] if r["code"] == "S01")
    assert 5 not in s01["off_hours"]
    assert cal["columns"][0] <= 5 and cal["columns"][-1] >= 21
    assert cal["can"] == {"counter_book": True, "create_session": False}
    assert cal["is_past"] is False


async def test_calendar_permissions_and_range(admin, staff):
    tomorrow = today() + timedelta(days=1)
    # Admin: tạo sự kiện ngày sau, không giới hạn "hết tháng sau" (T-008 AC31b);
    # đặt quầy chỉ hôm nay (cả Admin)
    for day in (tomorrow, today() + timedelta(days=200)):
        assert (await calendar(admin, day))["can"] == {
            "counter_book": False,
            "create_session": True,
        }
    # Tài khoản tại máy: chỉ đặt hôm nay, không tạo sự kiện
    assert (await calendar(staff, tomorrow))["can"] == {
        "counter_book": False,
        "create_session": False,
    }
    past = await calendar(admin, today() - timedelta(days=3))
    assert past["is_past"] is True
    assert past["can"] == {"counter_book": False, "create_session": False}


async def test_calendar_shows_booking_block_and_unpaid_chip(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    before = (await calendar(staff))["unpaid_count"]
    r = await book(staff, court["code"], hour, customer=member("HV0087"))
    assert r.status_code == 201, r.text
    cal = await calendar(staff)
    assert cal["unpaid_count"] == before + 1
    block = next(b for b in cal["blocks"] if b["code"] == r.json()["code"])
    assert block["type"] == "booking" and block["resource_codes"] == [court["code"]]
    assert block["payment_status"] == "unpaid"
    assert block["customer_name"] == "Phạm Thu Trang"
    assert block["phone_masked"] == "0987 xxx 087"
    assert (block["start_hour"], block["end_hour"]) == (hour, hour + 1)
    assert "0987654087" not in str(cal)


# ------------------------------------------------------------------ tìm hội viên (BR-007)


async def test_member_search(staff):
    async def search(q):
        r = await staff.get(f"{API}/members/search", params={"q": q})
        assert r.status_code == 200, r.text
        return r.json()

    assert [m["member_code"] for m in await search("hv0031")] == ["HV0031"]
    by_name = await search("nguyễn")
    assert {"HV0058", "HV0102"} <= {m["member_code"] for m in by_name}
    by_phone = await search("0938 120")  # SĐT có khoảng trắng
    assert [m["member_code"] for m in by_phone] == ["HV0120"]
    assert by_phone[0]["is_active"] is False  # hội viên Ngừng vẫn hiện
    assert by_phone[0]["phone_masked"] == "0938 xxx 777"
    assert await search("Lê Thị Lan") == []  # hồ sơ tạm không nằm trong danh sách hội viên
    assert await search("%") == []  # ký tự đại diện không lọt vào LIKE
    for row in await search("HV"):
        assert set(row) == {"ref", "member_code", "name", "phone_masked", "tier", "is_active"}
    r = await staff.get(f"{API}/members/search", params={"q": ""})
    assert r.status_code == 422


async def test_member_search_rate_limited(staff):
    for _ in range(60):
        assert (await staff.get(f"{API}/members/search", params={"q": "HV"})).status_code == 200
    r = await staff.get(f"{API}/members/search", params={"q": "HV"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"


# ------------------------------------------------------------------ đặt tại quầy (BR-005…011)


async def test_counter_booking_member(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, customer=member("hv0087"))
    assert r.status_code == 201, r.text
    item = r.json()
    assert re.fullmatch(rf"BK-{today():%Y%m%d}-\d{{3}}", item["code"])
    assert item["kind"] == "booking" and item["source"] == "counter" and item["version"] == 1
    assert item["customer"] == {
        "name": "Phạm Thu Trang",
        "phone_masked": "0987 xxx 087",
        "profile_label": "Hội viên (HV0087 · Hạng Bạc)",
        "kind": "member",
        "member_code": "HV0087",
        "tier": "Bạc",
    }
    assert item["schedule"]["resource_codes"] == [court["code"]]
    assert item["schedule"]["start_time"] == f"{hour:02d}:00"
    assert item["payment"]["payment_status"] == "unpaid"
    assert is_staff_label(item["created_by"])
    assert "collect" in item["actions"]
    quote = await staff.post(
        f"{BK}/quote",
        json={
            "resource_code": court["code"],
            "date": today().isoformat(),
            "start_hour": hour,
            "end_hour": hour + 1,
        },
    )
    assert item["payment"]["amount"] == quote.json()["total_amount"]
    assert [p["price"] for p in item["price_breakdown"]] == [
        i["price"] for i in quote.json()["items"]
    ]

    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "booking.counter.create", AuditLog.entity_code == item["code"]
            )
        )
    assert row is not None and is_staff_label(row.actor_label)
    assert "0987654087" not in str(row.detail)


async def test_counter_booking_temp_profile_create_reuse_and_member_clash(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    phone = random_phone()
    r = await book(
        staff,
        court["code"],
        hour,
        customer=temp("  Nguyễn  Văn   Bình ", f"+84 {phone[1:4]}.{phone[4:]}", note="Mang vợt"),
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["customer"]["name"] == "Nguyễn Văn Bình"
    assert item["customer"]["profile_label"] == "Hồ sơ tạm"
    assert item["note"] == "Mang vợt"
    async with SessionLocal() as s:
        created = await s.scalar(select(Customer).where(Customer.phone == phone))
        assert created.kind == "temp" and created.full_name == "Nguyễn Văn Bình"
        temp_audits = await s.scalar(
            select(func.count()).where(AuditLog.action == "member.temp.create")
        )

    # Trùng hồ sơ tạm -> dùng lại, giữ tên cũ (OQ-21), không tạo hồ sơ mới
    other = await new_court(admin)
    r = await book(staff, other["code"], hour, customer=temp("Tên Khác", phone))
    assert r.status_code == 201, r.text
    assert r.json()["customer"]["name"] == "Nguyễn Văn Bình"
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).where(Customer.phone == phone)) == 1
        assert (
            await s.scalar(select(func.count()).where(AuditLog.action == "member.temp.create"))
            == temp_audits
        )

    # SĐT là của hội viên -> E-018, không tạo gì
    third = await new_court(admin)
    r = await book(staff, third["code"], hour, customer=temp("Ai đó", "0934.567.019"))
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-018",
        "message": "Số điện thoại này đã là của hội viên HV0031 – Phạm Văn Nam. "
        "Vui lòng chọn Hồ sơ hội viên.",
    }
    cal = await calendar(staff)
    assert not [b for b in cal["blocks"] if third["code"] in b["resource_codes"]]


@pytest.mark.parametrize(
    ("customer", "status", "code"),
    [
        ({"temp": {"full_name": "  ", "phone": "0901234567"}}, 422, "E-001"),
        ({"temp": {"full_name": "A", "phone": ""}}, 422, "E-001"),
        ({"temp": {"full_name": "A" * 101, "phone": "0901234567"}}, 422, "E-001"),
        ({"temp": {"full_name": "A", "phone": "12345"}}, 422, "E-002"),
        ({"temp": {"full_name": "A", "phone": "1901234567"}}, 422, "E-002"),
        ({"member_code": "HV9999"}, 422, "E-014"),
    ],
)
async def test_counter_booking_customer_validation(admin, staff, customer, status, code):
    court = await new_court(admin)
    r = await book(staff, court["code"], await safe_hour(), customer=customer)
    assert r.status_code == status, r.text
    assert r.json()["detail"]["code"] == code


async def test_counter_booking_customer_shape_rejected(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    for customer in ({}, {"member_code": "HV0031", "temp": {"full_name": "A", "phone": "x"}}):
        r = await book(staff, court["code"], hour, customer=customer)
        assert r.status_code == 422


async def test_counter_booking_server_rules(admin, staff):
    court = await new_court(admin, open_time="06:00", close_time="22:00")
    hour = await safe_hour()
    tomorrow = today() + timedelta(days=1)
    # Ngày sau: chỉ Đặt sự kiện (quầy và Admin) -> 403
    for client in (staff, admin):
        r = await book(client, court["code"], 8, day=tomorrow)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    # Ngày đã qua (cả Admin)
    for client in (staff, admin):
        r = await book(client, court["code"], 8, day=today() - timedelta(days=1))
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004"
    # Khung đã qua trong hôm nay (giờ kết thúc ≤ bây giờ)
    if hour >= 1:
        full = await new_court(admin)
        r = await book(staff, full["code"], hour - 1, hour + 1)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004"
    # Ngoài giờ mở cửa / giờ ngược
    r = await book(staff, court["code"], 22, 23)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-10"
    r = await book(staff, court["code"], 10, 10)
    assert r.status_code == 422
    # Sân không có
    r = await book(staff, "S99", hour)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-NOT-FOUND"


@pytest.mark.parametrize(
    "extra",
    [
        {"amount": 1},
        {"price": 1},
        {"code": "BK-1"},
        {"payment_status": "paid"},
        {"customer_name": "X"},
        {"created_by": "Admin"},
    ],
)
async def test_counter_booking_rejects_server_fields(admin, staff, extra):
    court = await new_court(admin)
    hour = await safe_hour()
    r = await staff.post(
        f"{API}/front-desk/bookings",
        json={
            "resource_code": court["code"],
            "date": today().isoformat(),
            "start_hour": hour,
            "end_hour": hour + 1,
            "customer": member(),
            **extra,
        },
        headers=idem(),
    )
    assert r.status_code == 422


async def test_counter_booking_price_locked_at_booking_time(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour)
    assert r.status_code == 201
    amount = r.json()["payment"]["amount"]
    table = (await admin.get(f"{BK}/prices")).json()
    raised = [{**p, "price_per_hour": p["price_per_hour"] + 10_000} for p in table["prices"]]
    r2 = await admin.put(
        f"{BK}/prices", json={"version": table["version"], "prices": raised}, headers=idem()
    )
    assert r2.status_code == 200
    try:
        item = (await staff.get(f"{BK}/items/{r.json()['code']}")).json()
        assert item["payment"]["amount"] == amount
    finally:
        await admin.put(
            f"{BK}/prices",
            json={"version": r2.json()["version"], "prices": table["prices"]},
            headers=idem(),
        )


async def test_counter_booking_idempotent_replay(admin, staff):
    court = await new_court(admin)
    headers = idem()
    hour = await safe_hour()
    r1 = await book(staff, court["code"], hour, headers=headers)
    r2 = await book(staff, court["code"], hour, headers=headers)
    assert r1.status_code == r2.status_code == 201
    assert r2.json() == r1.json() and r2.headers.get("idempotent-replayed") == "true"


async def test_counter_booking_race_20_requests_one_wins(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    results = await asyncio.gather(*(book(staff, court["code"], hour) for _ in range(20)))
    statuses = sorted(r.status_code for r in results)
    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 19
    assert all(r.json()["detail"]["code"] == "E-003" for r in results if r.status_code == 409)
    winner = next(r for r in results if r.status_code == 201).json()
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(Booking)
            .where(Booking.play_date == today(), Booking.start_at == at(today(), hour))
            .where(Booking.code == winner["code"])
        )
    assert n == 1
    blocks = [b for b in (await calendar(staff))["blocks"] if court["code"] in b["resource_codes"]]
    assert len(blocks) == 1


async def test_counter_booking_blocked_by_hold_until_it_expires(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    start, end = at(today(), hour), at(today(), hour + 1)
    async with SessionLocal() as s:
        await make_hold(s, resource_code=court["code"], start=start, end=end, minutes=7)
        await s.commit()
    cal = await calendar(staff)
    hold = next(b for b in cal["blocks"] if court["code"] in b["resource_codes"])
    assert hold["type"] == "hold" and hold["expires_at"] and hold["code"] is None
    r = await book(staff, court["code"], hour)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-003"

    # Giữ chỗ đã quá hạn (worker chưa chạy): không hiện, không chặn
    other = await new_court(admin)
    async with SessionLocal() as s:
        await make_hold(s, resource_code=other["code"], start=start, end=end, minutes=-1)
        await s.commit()
    cal = await calendar(staff)
    assert not [b for b in cal["blocks"] if other["code"] in b["resource_codes"]]
    r = await book(staff, other["code"], hour)
    assert r.status_code == 201, r.text


async def test_expire_holds_job():
    async with SessionLocal() as s:
        await make_hold(
            s,
            resource_code="S03",
            start=at(today() + timedelta(days=5), 9),
            end=at(today() + timedelta(days=5), 10),
            minutes=-2,
        )
        await s.commit()
    async with SessionLocal() as s:
        assert await expire_holds(s) >= 1
        await s.commit()
    async with SessionLocal() as s:
        assert await expire_holds(s) == 0


# ------------------------------------------------------------------ tìm mã (BR-023) + item


async def test_search_code_and_item(admin, staff):
    court = await new_court(admin)
    r = await book(staff, court["code"], await safe_hour())
    code = r.json()["code"]
    res = await staff.get(f"{BK}/search", params={"code": f"  {code.lower()} "})
    assert res.status_code == 200
    assert res.json() == {"kind": "booking", "code": code, "play_date": today().isoformat()}

    res = await staff.get(f"{BK}/search", params={"code": "bk-20000101-999"})
    assert res.status_code == 404
    assert res.json()["detail"] == {
        "code": "E-021",
        "message": "Không tìm thấy mã BK-20000101-999. Kiểm tra lại mã.",
    }
    # Không tìm theo tên / SĐT
    res = await staff.get(f"{BK}/search", params={"code": "Phạm Văn Nam"})
    assert res.status_code == 404

    item = await staff.get(f"{BK}/items/{code.lower()}")
    assert item.status_code == 200 and item.json()["code"] == code
    assert "id" not in item.json() and "customer_ref" not in item.text
    assert (await staff.get(f"{BK}/items/BK-20000101-999")).status_code == 404


async def test_search_rate_limited(staff):
    for _ in range(60):
        await staff.get(f"{BK}/search", params={"code": "X"})
    r = await staff.get(f"{BK}/search", params={"code": "X"})
    assert r.status_code == 429


async def test_customer_cannot_use_front_desk(customer):
    r = await book(customer, "S01", 10)
    assert r.status_code == 403
    assert (
        await customer.get(f"{BK}/calendar", params={"date": today().isoformat()})
    ).status_code == 403

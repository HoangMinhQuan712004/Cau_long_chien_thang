"""T-006 phần 1: lịch ngày, tìm hội viên, đặt tại quầy, tìm mã, thông tin booking."""

import asyncio
import re
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.api import expire_holds
from app.modules.booking_engine.models import Allocation, Booking, OutboxEvent
from app.modules.booking_engine.testing import make_hold
from app.modules.members.models import Customer
from app.modules.play_rooms import handlers as room_handlers
from app.modules.play_rooms import lifecycle as rooms
from app.modules.play_rooms.models import PlayRoom
from tests.conftest import API, idem, is_staff_label
from tests.helpers_booking import (
    BK,
    FD,
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
    # Sân ngừng vẫn hiện xám, xuống cuối danh sách (người dùng chốt 2026-11-09)
    flags = [r["is_active"] for r in cal["resources"]]
    assert flags == sorted(flags, reverse=True), "sân hoạt động trước, sân ngừng sau cùng"
    assert (
        "S06" in codes and not next(r for r in cal["resources"] if r["code"] == "S06")["is_active"]
    )
    s05 = next(r for r in cal["resources"] if r["code"] == "S05")
    assert 5 in s05["off_hours"]  # S05 mở 06:00 -> ô 05:00 Xám
    s01 = next(r for r in cal["resources"] if r["code"] == "S01")
    assert 5 not in s01["off_hours"]
    assert cal["columns"][0] <= 5 and cal["columns"][-1] >= 21
    # NV mặc định tạo được sự kiện (người dùng chốt 2026-11-05)
    assert cal["can"] == {"counter_book": True, "create_session": True}
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
    # NV: chỉ đặt hôm nay; tạo được sự kiện (người dùng chốt 2026-11-05)
    assert (await calendar(staff, tomorrow))["can"] == {
        "counter_book": False,
        "create_session": True,
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
    assert block["phone"] == "0987654087"  # màn quản trị: SĐT đầy đủ
    assert (block["start_hour"], block["end_hour"]) == (hour, hour + 1)


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
    assert by_phone[0]["phone"] == "0938120777"
    assert await search("Lê Thị Lan") == []  # hồ sơ tạm không nằm trong danh sách hội viên
    assert await search("%") == []  # ký tự đại diện không lọt vào LIKE
    for row in await search("HV"):
        assert set(row) == {"ref", "member_code", "name", "phone", "tier", "is_active"}
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
    # Mã đơn BK-YYYYMMDD-NNN, khối nhận mã con -01 (T-019)
    assert re.fullmatch(rf"BK-{today():%Y%m%d}-\d{{3}}", item["order_code"])
    assert item["code"] == f"{item['order_code']}-01"
    assert item["kind"] == "booking" and item["source"] == "counter" and item["version"] == 1
    assert item["customer"] == {
        "name": "Phạm Thu Trang",
        "phone": "0987654087",
        "profile_label": "Hội viên (HV0087 · Hạng Trung bình +)",
        "kind": "member",
        "member_code": "HV0087",
        "tier": "Trung bình +",
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
    # Lịch sử thao tác chỉ Admin xem -> SĐT ghi đầy đủ (SRS Lịch sử thao tác BR-007)
    assert "0987654087" in str(row.detail)


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
    # Sân không có – mã không thể có (test khác tạo sân S01…S99+ trong cùng DB test)
    r = await book(staff, "ZZ999", hour)
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
    order_code = r.json()["order_code"]
    assert res.json() == {
        "kind": "booking",
        "code": code,
        "play_date": today().isoformat(),
        "order_code": order_code,
        "codes": [],
    }
    # Mã đơn -> danh sách khối
    res = await staff.get(f"{BK}/search", params={"code": order_code})
    assert res.json() == {
        "kind": "order",
        "code": order_code,
        "play_date": today().isoformat(),
        "order_code": order_code,
        "codes": [code],
    }

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


# ------------------------------------------------------------------ đổi sân (2026-11-09)


async def cancel_paid(admin, item: dict) -> dict:
    """Khung đang diễn ra chỉ hủy được khi đã thu: thu tiền rồi hủy (xác nhận hoàn tiền)."""
    paid = await admin.post(
        f"{BK}/items/{item['code']}/collect",
        json={"method": "cash", "version": item["version"]},
        headers=idem(),
    )
    assert paid.status_code == 200, paid.text
    r = await admin.post(
        f"{FD}/items/{item['code']}/cancel",
        json={"reason": "Thử đổi sân", "version": paid.json()["version"], "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    return r.json()


MOVE_REASON = "Sân hỏng / bảo trì"


async def move(client, code: str, resource_code: str, version: int, reason=MOVE_REASON, **headers):
    body = {"resource_code": resource_code, "version": version}
    if reason is not None:  # None: không gửi trường reason
        body["reason"] = reason
    return await client.post(
        f"{BK}/items/{code}/move",
        json=body,
        headers={**idem(), **headers},
    )


async def test_move_keeps_code_price_payment_and_follows_room(admin, staff):
    hour = await safe_hour()
    a = await new_court(admin)
    b = await new_court(admin, resource_type_code="vip")  # khác loại: giá giữ nguyên
    booked = (await book(staff, a["code"], hour, customer=member())).json()
    paid = await staff.post(
        f"{BK}/items/{booked['code']}/collect",
        json={"method": "cash", "version": booked["version"]},
        headers=idem(),
    )
    assert paid.status_code == 200, paid.text
    before = paid.json()
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == booked["code"]))
        booking_id, amount = row.id, row.amount
        await rooms.ensure_for_codes(s, [booked["code"]])
        await s.commit()

    targets = (await staff.get(f"{BK}/items/{booked['code']}/move-targets")).json()
    assert b["code"] in [t["code"] for t in targets] and a["code"] not in [
        t["code"] for t in targets
    ]

    r = await move(staff, booked["code"], b["code"], before["version"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["code"] == booked["code"] and out["version"] == before["version"] + 1
    assert out["schedule"]["resource_codes"] == [b["code"]]
    assert out["payment"] == before["payment"], "tiền đã thu giữ nguyên"
    assert out["price_breakdown"] == before["price_breakdown"], "giá đã chốt giữ nguyên"
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == booked["code"]))
        assert (row.id, row.amount) == (booking_id, amount)
        alloc = await s.scalar(select(Allocation).where(Allocation.booking_id == booking_id))
        assert alloc.active and alloc.resource_id == row.resource_id
        event = await s.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.event_type == "booking.moved")
            .order_by(OutboxEvent.id.desc())
        )
        assert event.payload["code"] == booked["code"]
        assert event.payload["resource_code"] == b["code"]
    # Worker phát sự kiện -> phòng chơi (nếu có) đổi theo tên sân
    await room_handlers.follow_moved_booking(event.payload)
    async with SessionLocal() as s:
        room = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == booked["code"]))
    assert room is not None, "booking của hội viên có phòng chơi"
    assert (room.resource_code, room.resource_name) == (b["code"], b["name"])

    log = await admin.get(f"{API}/admin/audit-log", params={"action": "booking.move"})
    row = next(i for i in log.json()["items"] if i["target"]["code"] == booked["code"])
    assert row["action_label"] == "Đổi sân"
    assert row["changes"] == [
        {"field": "Sân", "before": a["name"], "after": b["name"]},
        {"field": "Lý do", "before": None, "after": MOVE_REASON},
    ]


async def test_move_conflict_and_bad_target(admin):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    stopped = await new_court(admin)
    first = (await book(admin, a["code"], hour, customer=temp())).json()
    blocker = (await book(admin, b["code"], hour, customer=temp())).json()
    assert first["code"] and blocker["code"]
    # Trùng giờ: exclusion constraint chặn
    r = await move(admin, first["code"], b["code"], first["version"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-8", r.text
    targets = [
        t["code"] for t in (await admin.get(f"{BK}/items/{first['code']}/move-targets")).json()
    ]
    assert b["code"] not in targets and stopped["code"] in targets
    # Sân đích ngừng
    r = await admin.patch(
        f"{BK}/resources/{stopped['code']}",
        json={"version": stopped["version"], "is_active": False},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    r = await move(admin, first["code"], stopped["code"], first["version"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-BOOK-7", r.text
    targets = [
        t["code"] for t in (await admin.get(f"{BK}/items/{first['code']}/move-targets")).json()
    ]
    assert stopped["code"] not in targets
    # Sân đích không bán khung (đóng cửa sớm)
    early = await new_court(admin, open_time="00:00", close_time="01:00", peak_bands=[])
    if hour >= 1:
        r = await move(admin, first["code"], early["code"], first["version"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-BOOK-7"
    # Cùng sân, mã sân lạ, version cũ, khác origin
    r = await move(admin, first["code"], a["code"], first["version"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-6"
    assert (await move(admin, first["code"], "S999", first["version"])).status_code == 404
    r = await move(admin, first["code"], early["code"], first["version"] + 5)
    assert r.status_code in (409, 422)
    evil = await move(admin, first["code"], early["code"], 1, Origin="https://evil.example")
    assert evil.status_code == 403


async def test_move_rejects_cancelled_ended_and_non_booking(admin, anon):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    ended = (await book(admin, a["code"], hour, customer=temp())).json()
    async with SessionLocal() as s:
        # Lùi cả giờ bắt đầu: chạy trong phút đầu của giờ thì ``now - 1'`` sớm hơn ``HH:00`` của
        # khung -> vi phạm ``start_at < end_at`` (CI đỏ lúc 14:00, PR #65)
        await s.execute(
            update(Booking)
            .where(Booking.code == ended["code"])
            .values(
                start_at=func.now() - timedelta(minutes=61),
                end_at=func.now() - timedelta(minutes=1),
            )
        )
        await s.commit()
    item = (await admin.get(f"{BK}/items/{ended['code']}")).json()
    assert "move" not in item["actions"]
    r = await move(admin, ended["code"], b["code"], item["version"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-6"
    assert "kết thúc" in r.json()["detail"]["message"]

    other = await new_court(admin)
    cancelled = await cancel_paid(
        admin, (await book(admin, other["code"], hour, customer=temp())).json()
    )
    r = await move(admin, cancelled["code"], b["code"], cancelled["version"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-6"

    day = today() + timedelta(days=3)
    ev = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [b["code"]],
            "date": day.isoformat(),
            "start_hour": 10,
            "end_hour": 12,
            "name": "Sự kiện không đổi sân",
            "capacity": 8,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert ev.status_code == 201, ev.text
    r = await move(admin, ev.json()["code"], a["code"], 1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-6"
    assert (await move(admin, "BK-20000101-999-01", a["code"], 1)).status_code == 404


async def test_move_needs_counter_booking_permission(admin, staff):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    booked = (await book(admin, a["code"], hour, customer=temp())).json()
    async with SessionLocal() as s:
        await s.execute(
            delete(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == "booking.counter.create"
            )
        )
        await s.commit()
    try:
        r = await move(staff, booked["code"], b["code"], booked["version"])
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
        assert (await staff.get(f"{BK}/items/{booked['code']}/move-targets")).status_code == 403
        item = (await staff.get(f"{BK}/items/{booked['code']}")).json()
        assert "move" not in item["actions"]
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm="booking.counter.create"))
            await s.commit()
    r = await move(staff, booked["code"], b["code"], booked["version"])
    assert r.status_code == 200, r.text


async def test_move_history_in_item_oldest_first_and_kept_after_cancel(admin, staff):
    hour = await safe_hour()
    a, b, c = await new_court(admin), await new_court(admin), await new_court(admin)
    booked = (await book(admin, a["code"], hour, customer=temp())).json()
    assert booked["moves"] == [], "chưa đổi: rỗng"
    # Người dùng chốt 2026-11-09: lý do bắt buộc, đúng 1 trong 2 giá trị
    for bad in (None, "", "Khách yêu cầu", "ngừng sân", "x" * 101):
        r = await move(admin, booked["code"], b["code"], booked["version"], reason=bad)
        assert r.status_code == 422, (bad, r.text)
        if bad != "x" * 101:
            assert r.json()["detail"] == {"code": "E-001", "message": "Chọn lý do đổi sân."}
    first = await move(admin, booked["code"], b["code"], booked["version"])
    assert first.status_code == 200, first.text
    second = await move(
        staff, booked["code"], c["code"], first.json()["version"], reason="Ngừng sân"
    )
    assert second.status_code == 200, second.text

    moves = (await admin.get(f"{BK}/items/{booked['code']}")).json()["moves"]
    assert [(m["from_code"], m["to_code"]) for m in moves] == [
        (a["code"], b["code"]),
        (b["code"], c["code"]),
    ]
    assert [(m["from_name"], m["to_name"]) for m in moves][0] == (a["name"], b["name"])
    start, end = f"{hour:02d}:00", f"{hour + 1:02d}:00"
    for m in moves:
        assert (m["start_time"], m["end_time"]) == (start, end)
        assert (m["from_start_time"], m["from_end_time"]) == (start, end)
        assert m["date"] == today().isoformat() and m["moved_at"]
    assert [m["reason"] for m in moves] == ["Sân hỏng / bảo trì", "Ngừng sân"]
    assert moves[0]["moved_by"] != moves[1]["moved_by"], "ghi đúng người đổi (Admin rồi NV)"
    assert is_staff_label(moves[1]["moved_by"])
    assert second.json()["moves"] == moves, "response đổi sân cũng có lịch sử"

    # Hủy không xóa lịch sử; sân đã xóa vẫn hiện tên
    await cancel_paid(admin, second.json())
    assert (await admin.delete(f"{BK}/resources/{a['code']}", headers=idem())).status_code == 204
    kept = (await admin.get(f"{BK}/items/{booked['code']}")).json()["moves"]
    assert kept == moves and kept[0]["from_name"] == a["name"]


async def test_move_reason_in_audit(admin):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    booked = (await book(admin, a["code"], hour, customer=temp())).json()
    r = await move(admin, booked["code"], b["code"], booked["version"], reason="Ngừng sân")
    assert r.status_code == 200, r.text
    log = await admin.get(f"{API}/admin/audit-log", params={"action": "booking.move"})
    row = next(i for i in log.json()["items"] if i["target"]["code"] == booked["code"])
    assert {"field": "Lý do", "before": None, "after": "Ngừng sân"} in row["changes"]

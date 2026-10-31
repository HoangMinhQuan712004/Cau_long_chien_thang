"""T-018: Tổng quan, đặt sân trong khu hội viên (``as_member``), Lịch sử thanh toán."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.models import Booking
from app.modules.members.models import Customer
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem, unique_phone
from tests.helpers_booking import BK, book, member, new_court, safe_hour, today
from tests.helpers_web import WEB, simulate, tomorrow
from tests.test_play_rooms import post, room_for

people = base.people  # fixture: hội viên có tài khoản liên kết

MA = f"{API}/member-area"


async def overview(client) -> dict:
    r = await client.get(f"{MA}/overview")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


async def collect(staff, code: str, method: str = "cash"):
    item = (await staff.get(f"{BK}/items/{code}")).json()
    r = await staff.post(
        f"{BK}/items/{code}/collect",
        json={"method": method, "version": item["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ AC1–AC3: Tổng quan


async def test_overview_greeting_rooms_and_unread(staff, admin, people):
    host = await people("Nguyễn Văn Bình")
    guest = await people("Trần Thị Cúc")
    info = await room_for(staff, admin, host.code)
    room = info["room"]

    o = await overview(host.client)
    assert o["greeting_name"] == "Bình"  # tên ngắn
    assert o["today"] == today().isoformat()
    item = next(i for i in o["upcoming"] if i["room_id"] == room.id)
    assert item["role"] == "host" and item["phase"] == "ongoing"
    assert item["host_name"] == "Nguyễn Văn Bình" and item["count"] == 1
    assert item["capacity"] == 8 and item["booking_code"] == info["code"]
    assert item["order_code"] and info["code"].startswith(item["order_code"])
    assert o["today_count"] >= 1

    # Thành viên phòng cũng thấy lịch; Host thấy thông báo chưa đọc
    await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    d = (await host.client.get(f"{MA}/rooms/{room.id}")).json()
    rid = d["join_requests"][0]["id"]
    await post(host.client, f"/{room.id}/join-requests/{rid}/approve", {"version": d["version"]})
    g = await overview(guest.client)
    gi = next(i for i in g["upcoming"] if i["room_id"] == room.id)
    assert gi["role"] == "member" and gi["count"] == 2 and gi["host_name"] == "Nguyễn Văn Bình"
    assert len(gi["members_preview"]) == 2
    assert (await overview(host.client))["unread_count"] == 1

    # Biệt danh thay tên ngắn
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == host.customer_id).values(nickname="Bình Smash")
        )
        await s.commit()
    assert (await overview(host.client))["greeting_name"] == "Bình Smash"


async def test_overview_booking_without_room_and_limits(staff, admin, people):
    """Booking chưa có phòng vẫn hiện (room_id null); tối đa 4 mục; hết giờ thì không tính."""
    host = await people("Lê Văn Dũng")
    court = await new_court(admin)
    hour = await safe_hour()
    codes = []
    for h in range(hour, min(hour + 5, 24)):
        r = await book(staff, court["code"], h, h + 1, member(host.code))
        assert r.status_code == 201, r.text
        codes.append(r.json()["code"])
    o = await overview(host.client)
    mine = [i for i in o["upcoming"] if i["booking_code"] in codes]
    assert len(o["upcoming"]) <= 4 and mine
    first = mine[0]
    assert first["room_id"] is None and first["count"] is None  # chưa chạy tạo phòng
    assert first["role"] == "host" and first["host_name"] == "Lê Văn Dũng"
    assert o["today_count"] >= 1

    # Có phòng rồi -> dòng đó có room_id
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, codes[:1])
        await s.commit()
    o = await overview(host.client)
    assert next(i for i in o["upcoming"] if i["booking_code"] == codes[0])["room_id"]

    # Đã kết thúc -> không còn trong lịch sắp tới
    past = datetime.now(UTC) - timedelta(minutes=1)
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code == codes[0])
            .values(start_at=past - timedelta(hours=1), end_at=past)
        )
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.booking_code == codes[0])
            .values(start_at=past - timedelta(hours=1), end_at=past)
        )
        await s.commit()
    o = await overview(host.client)
    assert codes[0] not in [i["booking_code"] for i in o["upcoming"]]


async def test_overview_needs_member(anon, customer):
    assert (await anon.get(f"{MA}/overview")).status_code == 401
    r = await customer.get(f"{MA}/overview")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"


# ------------------------------------------------------------------ AC4, AC5: đặt sân trong khu HV


async def member_checkout(client, court_code: str, hour: int, **extra):
    body = {
        "date": tomorrow().isoformat(),
        "slots": [{"resource_code": court_code, "start_hour": hour}],
        "as_member": True,
        **extra,
    }
    return await client.post(f"{WEB}/checkouts", json=body, headers=idem())


async def test_as_member_checkout_uses_profile_and_creates_room(admin, people):
    host = await people("Phạm Hội Viên")
    court = await new_court(admin)
    # Họ tên / SĐT gửi lên bị bỏ qua; không cần phone_token
    r = await member_checkout(
        host.client, court["code"], 9, full_name="Tên Khác", phone=unique_phone()
    )
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    async with SessionLocal() as s:
        [b] = list(
            await s.scalars(select(Booking).where(Booking.customer_ref == str(host.customer_id)))
        )
    assert (b.customer_kind, b.member_code, b.customer_name) == (
        "member",
        host.code,
        "Phạm Hội Viên",
    )
    assert b.customer_phone == host.phone

    # Phòng tạo qua outbox (worker) – trước đó by-booking trả 404
    r = await host.client.get(f"{MA}/rooms/by-booking/{b.code}")
    assert r.status_code == 404
    while await engine.publish_outbox(SessionLocal):
        pass
    r = await host.client.get(f"{MA}/rooms/by-booking/{b.code}")
    assert r.status_code == 200, r.text
    room_id = r.json()["room_id"]
    d = (await host.client.get(f"{MA}/rooms/{room_id}")).json()
    assert d["my_role"] == "host"
    # Lịch sử thanh toán: QR online, hiện mã chung
    items = (await host.client.get(f"{MA}/payments")).json()["items"]
    item = next(i for i in items if i["code"] == b.code)
    assert (item["method"], item["channel"]) == ("QR", "online")
    assert item["display_code"] != b.code and b.code.startswith(item["display_code"])


async def test_by_booking_only_for_room_members(staff, admin, people):
    host, other = await people(), await people()
    info = await room_for(staff, admin, host.code)
    r = await other.client.get(f"{MA}/rooms/by-booking/{info['code']}")
    assert r.status_code == 404
    r = await host.client.get(f"{MA}/rooms/by-booking/{info['code']}")
    assert r.json() == {"room_id": info["room"].id}


async def test_as_member_requires_active_linked_member(anon, customer, admin, people):
    court = await new_court(admin)
    r = await member_checkout(anon, court["code"], 10, full_name="A", phone=unique_phone())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"
    r = await member_checkout(customer, court["code"], 10, full_name="A", phone=unique_phone())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"
    stopped = await people()
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == stopped.customer_id).values(is_active=False)
        )
        await s.commit()
    r = await member_checkout(stopped.client, court["code"], 10)
    assert r.status_code == 403


async def test_public_checkout_unchanged_for_signed_in_member(admin, people):
    """Không có cờ: đặt hộ SĐT khác vẫn cần phone_token như cũ (không tự đổi SĐT)."""
    host = await people()
    court = await new_court(admin)
    body = {
        "date": tomorrow().isoformat(),
        "slots": [{"resource_code": court["code"], "start_hour": 11}],
        "full_name": "Bạn Của Tôi",
        "phone": unique_phone(),
    }
    r = await host.client.post(f"{WEB}/checkouts", json=body, headers=idem())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-WEB-8"


# ------------------------------------------------------------------ AC7–AC10: Lịch sử thanh toán


async def test_payment_history(staff, admin, people):
    host = await people("Vũ Thanh Toán")
    other = await people()
    court = await new_court(admin)
    hour = await safe_hour()
    paid = await book(staff, court["code"], hour, hour + 1, member(host.code))
    unpaid_hour = hour + 1 if hour < 23 else hour - 1
    unpaid = await book(staff, court["code"], unpaid_hour, unpaid_hour + 1, member(host.code))
    assert paid.status_code == unpaid.status_code == 201
    await collect(staff, paid.json()["code"])

    # Vé sự kiện (thu tiền mặt tại quầy)
    ev_court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [ev_court["code"]],
            "date": today().isoformat(),
            "start_hour": hour,
            "end_hour": hour + 1,
            "name": "Giao lưu cuối tuần",
            "capacity": 8,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    r = await staff.post(
        f"{API}/front-desk/sessions/{ev['code']}/tickets",
        json={"customer": member(host.code)},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    ticket_code = r.json()["code"]
    await collect(staff, ticket_code)

    r = await host.client.get(f"{MA}/payments")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    body = r.json()
    now = datetime.now(settings.tz)
    assert body["month"] == f"{now.year:04d}-{now.month:02d}" and body["month"] in body["months"]
    codes = {i["code"] for i in body["items"]}
    assert paid.json()["code"] in codes and ticket_code in codes
    assert unpaid.json()["code"] not in codes  # chỉ khoản đã thanh toán
    s = body["summary"]
    assert s["count"] == 2 and s["bookings"]["count"] == 1 and s["bookings"]["hours"] == 1.0
    assert s["tickets"] == {"count": 1, "total": 50_000}
    b = next(i for i in body["items"] if i["kind"] == "booking")
    assert s["total"] == b["amount"] + 50_000 and b["amount"] > 0
    assert b["display_code"] == paid.json()["order_code"]  # mã chung (T-019)
    assert b["method"] == "Tiền mặt" and b["channel"] == "counter"
    assert b["title"].startswith(f"Đặt sân · {court['name']} · ")
    t = next(i for i in body["items"] if i["kind"] == "ticket")
    assert t["display_code"] == ticket_code and t["method"] == "Tiền mặt"
    assert t["title"] == f"Vé sự kiện · Giao lưu cuối tuần · {ev_court['name']}"
    assert host.phone not in r.text

    only = (await host.client.get(f"{MA}/payments", params={"kind": "ticket"})).json()
    assert [i["kind"] for i in only["items"]] == ["ticket"] and only["summary"]["count"] == 2

    # Chi tiết: của mình -> 200; người khác / chưa thanh toán -> 404
    r = await host.client.get(f"{MA}/payments/{b['code']}")
    assert r.status_code == 200 and r.json()["amount"] == b["amount"]
    assert (await other.client.get(f"{MA}/payments/{b['code']}")).status_code == 404
    assert (await host.client.get(f"{MA}/payments/{unpaid.json()['code']}")).status_code == 404

    # Tháng khác: trống (AC10); tháng sai -> 422
    empty = (await host.client.get(f"{MA}/payments", params={"month": "2001-01"})).json()
    assert empty["items"] == [] and empty["summary"]["count"] == 0
    assert (await host.client.get(f"{MA}/payments", params={"month": "2026-13"})).status_code == 422
    assert (await host.client.get(f"{MA}/payments", params={"month": "abc"})).status_code == 422


async def test_payment_month_follows_paid_at(staff, admin, people):
    """Tháng theo thời điểm thanh toán (giờ VN), không theo ngày chơi."""
    host = await people()
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, hour + 1, member(host.code))
    code = r.json()["code"]
    await collect(staff, code)
    paid_at = datetime(2025, 3, 31, 17, 30, tzinfo=UTC)  # = 01/04/2025 00:30 giờ VN
    async with SessionLocal() as s:
        await s.execute(update(Booking).where(Booking.code == code).values(paid_at=paid_at))
        await s.commit()
    april = (await host.client.get(f"{MA}/payments", params={"month": "2025-04"})).json()
    assert [i["code"] for i in april["items"]] == [code]
    assert "2025-04" in april["months"]
    march = (await host.client.get(f"{MA}/payments", params={"month": "2025-03"})).json()
    assert march["items"] == []


async def test_payments_include_online_bookings_before_profile(staff, admin, people):
    """Booking online đặt khi SĐT chưa có hồ sơ (``phone:…``) vẫn nằm trong lịch sử của hồ sơ."""
    host = await people()
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, hour + 1, member(host.code))
    code = r.json()["code"]
    await collect(staff, code)
    async with SessionLocal() as s:
        await s.execute(
            update(Booking).where(Booking.code == code).values(customer_ref=f"phone:{host.phone}")
        )
        await s.commit()
    body = (await host.client.get(f"{MA}/payments")).json()
    assert code in [i["code"] for i in body["items"]]

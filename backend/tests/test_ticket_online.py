"""T-023: mua vé sự kiện online (QR), lịch hội viên đánh dấu sân của mình, đơn của mình."""

import asyncio
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.api import expire_holds
from app.modules.booking_engine.models import Checkout, Hold, Ticket
from app.modules.members.models import Customer
from tests import test_play_rooms as base
from tests.conftest import API, idem, unique_phone
from tests.helpers_booking import BK, book, member, new_court, now, random_phone, today
from tests.helpers_web import WEB, checkout, phone_token, simulate, tomorrow, web_calendar
from tests.test_online_payments import drain_outbox, shift_expiry

people = base.people  # fixture: hội viên có tài khoản liên kết

MA = f"{API}/member-area"
FD = f"{API}/front-desk"


async def new_event(
    admin,
    *,
    day: date | None = None,
    hours: tuple[int, int] = (9, 11),
    capacity: int = 8,
    price: int = 50_000,
    name: str = "Giao lưu tối",
) -> dict:
    court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": (day or tomorrow()).isoformat(),
            "start_hour": hours[0],
            "end_hour": hours[1],
            "name": name,
            "capacity": capacity,
            "ticket_price": price,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return {**r.json(), "court": court}


async def buy(client, code: str, seats: int = 1, *, phone=None, name="Khách Mua Vé", **extra):
    body = {"event_code": code, "seats": seats, "full_name": name, "as_member": False, **extra}
    if not body["as_member"]:
        body["phone"] = phone = phone or random_phone()
        if "phone_token" not in body:
            body["phone_token"] = await phone_token(client, phone)
    return await client.post(f"{WEB}/event-checkouts", json=body, headers=idem())


async def event_info(client, code: str) -> dict:
    r = await client.get(f"{WEB}/events/{code}")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def error(r) -> str:
    return r.json()["detail"]["code"]


# ------------------------------------------------------------------ xem sự kiện (AC5, AC22)


async def test_event_info_public_and_calendar_event_code(anon, admin):
    ev = await new_event(admin, capacity=12, name="Giao lưu cuối tuần")
    info = await event_info(anon, ev["code"])
    assert info == {
        "code": ev["code"],
        "name": "Giao lưu cuối tuần",
        "play_date": tomorrow().isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "resource_names": [ev["court"]["name"]],
        "ticket_price": 50_000,
        "capacity": 12,
        "taken": 0,
        "max_seats": 10,  # min(còn lại, 10)
        "can_buy": True,
        "reason": None,
        "my_tickets": None,  # khách chưa đăng nhập: không có vé của tôi
        "hold_minutes": 5,
    }
    cal = (await web_calendar(anon)).json()
    row = next(x for x in cal["resources"] if x["code"] == ev["court"]["code"])
    slots = {s["start_hour"]: s for s in row["slots"]}
    assert slots[9]["event_code"] == slots[10]["event_code"] == ev["code"]  # ô nào cũng mở
    assert slots[12]["event_code"] is None

    # Đã có người mua: công khai không lộ tên / SĐT người mua
    phone = random_phone()
    assert (await buy(anon, ev["code"], 2, phone=phone, name="Người Mua Bí Mật")).status_code == 201
    r = await anon.get(f"{WEB}/events/{ev['code']}")
    assert r.json()["taken"] == 2 and r.json()["max_seats"] == 10
    assert "Người Mua" not in r.text and phone not in r.text
    assert (await anon.get(f"{WEB}/events/BK-20000101-999")).status_code == 404


# ------------------------------------------- mua vé -> tiền về -> vé (AC8, AC10, AC13, AC14, AC19)


async def test_guest_buys_tickets_and_payment_creates_tickets(anon, admin):
    ev = await new_event(admin, capacity=5, price=60_000)
    phone = random_phone()
    r = await buy(anon, ev["code"], 3, phone=phone, name="Lê Văn Vé")
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["kind"] == "ticket" and co["status"] == "pending" and co["items"] == []
    assert re.fullmatch(rf"BK-{tomorrow():%Y%m%d}-\d{{3}}", co["order_code"])
    assert co["pay_ref"] == co["order_code"].replace("-", "")
    assert co["amount"] == 180_000 and co["bank"] is not None
    assert co["customer"] == {
        "full_name": "Lê Văn Vé",
        "phone_masked": co["customer"]["phone_masked"],
    }
    assert phone not in r.text
    assert co["event"] == {
        "code": ev["code"],
        "name": "Giao lưu tối",
        "play_date": tomorrow().isoformat(),
        "start_time": "09:00",
        "end_time": "11:00",
        "resource_names": [ev["court"]["name"]],
        "seats": 3,
        "ticket_price": 60_000,
        "ticket_codes": [],
    }
    # Ghế đang giữ tính vào chỗ đã chiếm (lịch quản trị, lịch công khai, chi tiết)
    s = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert s["taken"] == 3 and [h["seats"] for h in s["active_holds"]] == [3]
    assert (await event_info(anon, ev["code"]))["max_seats"] == 2

    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["kind"] == "ticket" and view["status"] == "paid" and view["bank"] is None
    codes = [f"{ev['code']}-V01", f"{ev['code']}-V02", f"{ev['code']}-V03"]
    assert view["event"]["ticket_codes"] == codes

    s = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert s["taken"] == 3 and s["active_holds"] == []
    tickets = sorted(s["tickets"], key=lambda t: t["code"])
    assert [t["code"] for t in tickets] == codes
    assert {(t["source"], t["payment_status"], t["amount"]) for t in tickets} == {
        ("online", "paid", 60_000)
    }
    async with SessionLocal() as db:
        rows = list(await db.scalars(select(Ticket).where(Ticket.code.in_(codes))))
        assert {(t.payment_method, t.customer_kind, t.customer_ref) for t in rows} == {
            ("online_transfer", "temp", f"phone:{phone}")
        }
        hold = await db.scalar(select(Hold).join(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
        assert (hold.kind, hold.status, hold.seats) == ("seat", "converted", 3)
        row = await db.scalar(
            select(AuditLog).where(
                AuditLog.action == "ticket.online.paid", AuditLog.entity_code == co["pay_ref"]
            )
        )
    assert row.actor_type == "system"
    assert row.detail["order_code"] == co["order_code"] and row.detail["codes"] == codes

    # Lịch sử giao dịch (Admin) có vé online
    day = tomorrow().isoformat()
    r = await admin.get(f"{BK}/transactions", params={"q": ev["code"], "from": day, "to": day})
    assert r.status_code == 200, r.text
    assert all(c in r.text for c in codes)

    # Outbox ticket.online_paid -> hồ sơ tạm theo SĐT (AC19)
    await drain_outbox()
    async with SessionLocal() as db:
        created = await db.scalar(select(Customer).where(Customer.phone == phone))
    assert created.kind == "temp" and created.full_name == "Lê Văn Vé"


async def test_member_buys_as_member_sees_my_tickets_and_history(admin, people):
    host = await people("Phạm Mua Vé")
    ev = await new_event(admin, capacity=4)
    # Họ tên / SĐT gửi lên bị bỏ qua; không cần phone_token
    r = await buy(
        host.client, ev["code"], 2, as_member=True, full_name="Tên Khác", phone=unique_phone()
    )
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["customer"]["full_name"] == "Phạm Mua Vé"  # từ hồ sơ, không phải "Tên Khác"
    assert (await event_info(host.client, ev["code"]))["my_tickets"] == []
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"

    info = await event_info(host.client, ev["code"])
    assert info["my_tickets"] == [
        {"code": f"{ev['code']}-V01", "pay_status": "paid"},
        {"code": f"{ev['code']}-V02", "pay_status": "paid"},
    ]
    async with SessionLocal() as db:
        t = await db.scalar(select(Ticket).where(Ticket.code == f"{ev['code']}-V01"))
    assert (t.customer_kind, t.customer_ref, t.member_code) == (
        "member",
        str(host.customer_id),
        host.code,
    )
    # Lịch hội viên: ô sự kiện có vé (AC6)
    r = await host.client.get(f"{MA}/booking-calendar", params={"date": tomorrow().isoformat()})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["resources"] if x["code"] == ev["court"]["code"])
    slot = next(s for s in row["slots"] if s["start_hour"] == 9)
    assert slot["state"] == "event" and slot["event_code"] == ev["code"] and slot["has_ticket"]
    # Lịch sử thanh toán + hóa đơn (AC13)
    items = (await host.client.get(f"{MA}/payments", params={"kind": "ticket"})).json()["items"]
    mine = [i for i in items if i["code"].startswith(ev["code"])]
    assert len(mine) == 2 and {(i["method"], i["channel"]) for i in mine} == {("QR", "online")}
    r = await host.client.get(f"{MA}/payments/{ev['code']}-V01")
    assert r.status_code == 200 and r.json()["amount"] == 50_000


async def test_as_member_requires_active_linked_member(anon, customer, admin):
    ev = await new_event(admin)
    body = {"event_code": ev["code"], "seats": 1, "as_member": True}
    for client in (anon, customer):
        r = await client.post(f"{WEB}/event-checkouts", json=body, headers=idem())
        assert r.status_code == 403 and error(r) == "E-HV-8"


# ------------------------------------------------------------------ chỗ cuối, song song (AC9)


async def test_last_seat_concurrent_only_one_wins(anon, admin):
    ev = await new_event(admin, capacity=1)
    phones = [random_phone(), random_phone()]
    tokens = [await phone_token(anon, p) for p in phones]
    results = await asyncio.gather(
        *(
            buy(anon, ev["code"], 1, phone=p, phone_token=t)
            for p, t in zip(phones, tokens, strict=True)
        )
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    lost = next(r for r in results if r.status_code == 409)
    assert lost.json()["detail"]["code"] == "E-WEB-10"
    assert lost.json()["detail"]["message"] == "Sự kiện đã hết chỗ."
    info = await event_info(anon, ev["code"])
    assert (info["taken"], info["can_buy"], info["reason"]) == (1, False, "full")


async def test_counter_cannot_take_held_seat(anon, admin, staff):
    hour = now().hour + 1
    if hour >= 23:
        pytest.skip("Cần sự kiện hôm nay chưa bắt đầu")
    ev = await new_event(admin, day=today(), hours=(hour, hour + 1), capacity=2)
    assert (await buy(anon, ev["code"], 2)).status_code == 201
    r = await staff.post(
        f"{FD}/sessions/{ev['code']}/tickets",
        json={"customer": member()},
        headers=idem(),
    )
    assert r.status_code == 409 and error(r) == "E-024"


# ------------------------------------------------------------------ lỗi mua (AC7, AC12, AC22)


async def test_buy_seats_validation(anon, admin):
    ev = await new_event(admin, capacity=3)
    for seats in (0, 11):
        r = await buy(anon, ev["code"], seats)
        assert r.status_code == 422 and error(r) == "E-WEB-1"
    r = await buy(anon, ev["code"], 4)
    assert r.status_code == 409 and error(r) == "E-WEB-10"
    assert r.json()["detail"]["remaining"] == 3
    assert (await buy(anon, "BK-20000101-998", 1)).status_code == 404


async def test_buy_needs_phone_token_of_same_phone(anon, admin):
    ev = await new_event(admin)
    a, b = random_phone(), random_phone()
    r = await buy(anon, ev["code"], 1, phone=b, phone_token=await phone_token(anon, a))
    assert r.status_code == 403 and error(r) == "E-WEB-8"
    r = await buy(anon, ev["code"], 1, phone=b, phone_token=None)
    assert r.status_code == 403 and error(r) == "E-WEB-8"


async def test_one_pending_checkout_per_phone_shared_with_courts(anon, admin):
    ev = await new_event(admin)
    phone = random_phone()
    assert (await buy(anon, ev["code"], 1, phone=phone)).status_code == 201
    r = await buy(anon, ev["code"], 1, phone=phone)
    assert r.status_code == 409 and error(r) == "E-WEB-4"
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 15)], phone=phone)
    assert r.status_code == 409 and error(r) == "E-WEB-4"


async def test_free_and_deleted_events_not_sold(anon, admin):
    # Giá 0 -> đăng ký tại quầy
    free = await new_event(admin, price=0)
    info = await event_info(anon, free["code"])
    assert (info["can_buy"], info["reason"], info["max_seats"]) == (False, "free", 0)
    r = await buy(anon, free["code"], 1)
    assert r.status_code == 409 and error(r) == "E-WEB-11"

    # Đã xóa
    gone = await new_event(admin)
    r = await admin.request(
        "DELETE", f"{BK}/sessions/{gone['code']}", json={"version": gone["version"]}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (await event_info(anon, gone["code"]))["reason"] == "deleted"
    r = await buy(anon, gone["code"], 1)
    assert r.status_code == 409 and error(r) == "E-WEB-9"


async def test_started_event_not_sold(anon, admin):
    hour = now().hour
    if hour >= 23:
        pytest.skip("Cần khung giờ đang diễn ra trong ngày")
    ev = await new_event(admin, day=today(), hours=(hour, hour + 1))
    info = await event_info(anon, ev["code"])
    assert (info["can_buy"], info["reason"]) == (False, "started")
    r = await buy(anon, ev["code"], 1)
    assert r.status_code == 409 and error(r) == "E-WEB-9"


# ------------------------------------------------------------------ thiếu / trễ / hết hạn (AC11)


async def test_partial_then_full(anon, admin):
    ev = await new_event(admin)
    co = (await buy(anon, ev["code"], 2)).json()
    assert await simulate(admin, co["pay_ref"], 50_000) == "partial"
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "pending" and view["event"]["ticket_codes"] == []
    assert await simulate(admin, co["pay_ref"], 50_000 + 5_000) == "applied"
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "paid" and len(view["event"]["ticket_codes"]) == 2


async def test_expiry_releases_seats_and_late_money_refunds(anon, admin):
    ev = await new_event(admin, capacity=2)
    co = (await buy(anon, ev["code"], 2)).json()
    # Trong ân hạn: ghế vẫn giữ, tiền về vẫn nhận
    await shift_expiry(co["pay_ref"], 30)
    async with SessionLocal() as db:
        await expire_holds(db)
        await db.commit()
    assert (await event_info(anon, ev["code"]))["reason"] == "full"
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"

    ev2 = await new_event(admin, capacity=2)
    late = (await buy(anon, ev2["code"], 2)).json()
    await shift_expiry(late["pay_ref"], 90)
    async with SessionLocal() as db:
        assert await expire_holds(db) >= 1
        await db.commit()
    view = (await anon.get(f"{WEB}/checkouts/{late['token']}")).json()
    assert view["status"] == "expired"
    info = await event_info(anon, ev2["code"])
    assert (info["taken"], info["can_buy"]) == (0, True)  # nhả ghế
    assert await simulate(admin, late["pay_ref"], late["amount"]) == "refund_needed"
    async with SessionLocal() as db:
        n = await db.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.code.like(f"{ev2['code']}-%"))
        )
    assert n == 0


# ------------------------------------------------------------------ tra cứu vé (AC21)


async def test_lookup_ticket_order_and_ticket_code(anon, admin, staff):
    ev = await new_event(admin)
    phone = random_phone()
    co = (await buy(anon, ev["code"], 2, phone=phone, name="Tra Cứu Vé")).json()

    async def lookup(code, p=phone):
        return await anon.post(f"{WEB}/lookup", json={"code": code, "phone": p})

    r = await lookup(co["order_code"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["kind"], d["status"], d["items"]) == ("ticket", "pending", [])
    assert d["pending"]["pay_ref"] == co["pay_ref"] and d["event"]["tickets"] == []
    assert phone not in r.text

    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    for code in (co["order_code"], f"{ev['code']}-V02", co["pay_ref"]):
        r = await lookup(code)
        assert r.status_code == 200, (code, r.text)
        d = r.json()
        assert (d["kind"], d["status"], d["order_code"]) == ("ticket", "paid", co["order_code"])
        assert d["event"]["seats"] == 2 and d["event"]["name"] == "Giao lưu tối"
        assert d["event"]["tickets"] == [
            {"code": f"{ev['code']}-V01", "pay_status": "paid"},
            {"code": f"{ev['code']}-V02", "pay_status": "paid"},
        ]
        assert d["amount"] == 100_000 and d["paid_at"]
    # Sai SĐT -> cùng 404
    r = await lookup(f"{ev['code']}-V01", random_phone())
    assert r.status_code == 404 and error(r) == "E-WEB-7"
    r = await lookup(co["order_code"], random_phone())
    assert r.status_code == 404 and error(r) == "E-WEB-7"


# ------------------------------------------------------------------ ô "Đã đặt" (AC1, AC2, AC4)


async def test_member_calendar_marks_own_booking_and_order_detail(anon, staff, admin, people):
    host, other = await people("Hội Viên Có Sân"), await people()
    court = await new_court(admin)
    hour = now().hour
    if hour >= 23:
        pytest.skip("Cần khung giờ trong ngày")
    mine = await book(staff, court["code"], hour, hour + 1, member(host.code))
    theirs = await book(staff, court["code"], hour + 1, hour + 2, member(other.code))
    assert mine.status_code == theirs.status_code == 201, mine.raw.text
    order_code = mine.json()["order_code"]

    r = await host.client.get(f"{MA}/booking-calendar", params={"date": today().isoformat()})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    row = next(x for x in r.json()["resources"] if x["code"] == court["code"])
    slots = {s["start_hour"]: s for s in row["slots"]}
    assert (slots[hour]["mine"], slots[hour]["order_code"]) == (True, order_code)
    other_slot = slots[hour + 1]
    assert other_slot["state"] == "booked" and other_slot["mine"] is False
    assert other_slot["order_code"] is None
    assert theirs.json()["order_code"] not in r.text

    r = await host.client.get(f"{MA}/bookings/{order_code}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["order_code"], d["source"], d["pay_status"]) == (order_code, "counter", "unpaid")
    assert d["play_date"] == today().isoformat()
    [item] = d["items"]
    assert item["code"] == mine.json()["code"] and item["hours"] == 1
    assert item["pay_status"] == "unpaid" and item["amount"] == d["amount"]
    assert "phone" not in r.text.lower() and host.phone not in r.text

    # Của người khác / đoán mã -> 404; chưa đăng nhập -> 401
    r = await host.client.get(f"{MA}/bookings/{theirs.json()['order_code']}")
    assert r.status_code == 404 and error(r) == "E-NOT-FOUND"
    assert (await host.client.get(f"{MA}/bookings/BK-20000101-001")).status_code == 404
    assert (await anon.get(f"{MA}/bookings/{order_code}")).status_code == 401
    assert (
        await anon.get(f"{MA}/booking-calendar", params={"date": today().isoformat()})
    ).status_code == 401


async def test_member_calendar_past_day(people):
    host = await people()
    r = await host.client.get(
        f"{MA}/booking-calendar", params={"date": (today() - timedelta(days=1)).isoformat()}
    )
    assert r.status_code == 422 and error(r) == "E-WEB-2"

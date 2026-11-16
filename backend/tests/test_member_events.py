"""T-045: "Sự kiện sắp tới" ở khu hội viên – 14 ngày tới, chỗ còn lại, vé của tôi, riêng tư."""

from datetime import timedelta

from tests import test_play_rooms as base
from tests.helpers_booking import now, today
from tests.helpers_web import simulate, tomorrow
from tests.test_play_rooms import MA
from tests.test_ticket_online import buy, new_event

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

EVENTS = f"{MA}/events"


async def events(client, **params) -> list[dict]:
    r = await client.get(EVENTS, params=params)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-cache, private" and r.headers["etag"]
    return r.json()


async def test_upcoming_events_window_seats_my_tickets_and_privacy(anon, admin, people):
    me = await people("Người Xem Sự Kiện")
    mine = await new_event(admin, capacity=5, price=50_000, name="Giao lưu có vé")
    co = (await buy(me.client, mine["code"], 2, as_member=True)).json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    held = (await buy(anon, mine["code"], 1, name="Người Giữ Bí Mật")).json()  # ghế đang giữ
    assert held["status"] == "pending"

    full = await new_event(admin, capacity=1, name="Đủ chỗ")
    paid = (await buy(anon, full["code"], 1, name="Người Mua Bí Mật")).json()
    assert await simulate(admin, paid["pay_ref"], paid["amount"]) == "applied"
    free = await new_event(admin, price=0, name="Miễn phí")
    later = await new_event(admin, day=today() + timedelta(days=15), name="Ngoài 14 ngày")
    hour = now().hour
    started = (
        await new_event(admin, day=today(), hours=(hour, hour + 1), name="Đã bắt đầu")
        if hour < 23
        else None
    )

    items = await events(me.client)
    by_code = {e["code"]: e for e in items}
    assert {mine["code"], full["code"], free["code"]} <= set(by_code)
    assert later["code"] not in by_code  # ngoài 14 ngày
    if started:
        assert started["code"] not in by_code  # đã bắt đầu
    assert [e["start_at"] for e in items] == sorted(e["start_at"] for e in items)

    e = by_code[mine["code"]]
    assert (e["capacity"], e["taken"], e["remaining"]) == (5, 3, 2)  # 2 vé + 1 ghế đang giữ
    assert (e["my_ticket_count"], e["can_buy"], e["reason"]) == (2, True, None)
    assert e["play_date"] == tomorrow().isoformat() and (e["start_time"], e["end_time"]) == (
        "09:00",
        "11:00",
    )
    assert e["resource_names"] == [mine["court"]["name"]]
    assert (by_code[full["code"]]["can_buy"], by_code[full["code"]]["reason"]) == (False, "full")
    assert by_code[full["code"]]["remaining"] == 0
    assert (by_code[free["code"]]["can_buy"], by_code[free["code"]]["reason"]) == (False, "free")
    text = str(items)
    assert "Bí Mật" not in text and "phone" not in text  # không lộ người mua

    assert later["code"] in {x["code"] for x in await events(me.client, days=20)}
    # Tổng quan: tối đa 3, cùng shape
    o = (await me.client.get(f"{MA}/overview")).json()
    assert len(o["upcoming_events"]) <= 3
    assert all(set(x) == set(e) for x in o["upcoming_events"])


async def test_events_etag_and_access(anon, customer, people):
    me = await people()
    r = await me.client.get(EVENTS)
    assert r.status_code == 200
    again = await me.client.get(EVENTS, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    for days in (0, 32):
        assert (await me.client.get(EVENTS, params={"days": days})).status_code == 422
    assert (await anon.get(EVENTS)).status_code == 401
    r = await customer.get(EVENTS)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"

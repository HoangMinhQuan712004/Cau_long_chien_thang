# ruff: noqa: E501, F811
"""QA T-023 phía hội viên: lịch hội viên (AC1, AC3, AC4), đơn của mình (AC2, AC4), mua vé `as_member`, vé vào Lịch sử thanh toán,
màn sự kiện quản trị, Lịch sử giao dịch, Báo cáo doanh thu (AC13), audit + outbox (AC14), ngoài phạm vi: không lộ booking người khác.
"""

import uuid

from sqlalchemy import String, select

from app.core.db import SessionLocal
from app.modules.booking_engine.models import OutboxEvent
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, member, new_court, random_phone, safe_hour, temp, today
from tests.helpers_web import WEB, simulate, tomorrow
from tests.qa_rooms import people  # noqa: F401  (fixture: hội viên có tài khoản liên kết)
from tests.qa_tickets import buy, code_of, info, mk_event, q, today_event  # noqa: F401
from tests.test_online_payments import drain_outbox

MA = f"{API}/member-area"
CAL = f"{MA}/booking-calendar"


async def slot_of(client, court_code: str, hour: int, day=None) -> dict:
    r = await client.get(CAL, params={"date": (day or today()).isoformat()})
    assert r.status_code == 200, r.text
    res = next(x for x in r.json()["resources"] if x["code"] == court_code)
    return next(s for s in res["slots"] if s["start_hour"] == hour)


async def counter_order(admin, host_code: str, *, hour: int | None = None, customer=None) -> dict:
    """Đặt quầy hôm nay cho hội viên trên sân mới; trả {court, hour, order_code, item_code}."""
    court = await new_court(admin)
    h = hour if hour is not None else await safe_hour()
    r = await book(admin, court["code"], h, h + 1, customer or member(host_code))
    assert r.status_code == 201, r.text
    body = r.json()
    blk = body["bookings"][0] if "bookings" in body else body
    return {"court": court, "hour": h, "order_code": blk["order_code"], "item_code": blk["code"]}


# ============================================================ AC1 lịch hội viên


async def test_ac1_member_calendar_marks_only_my_slots_and_hides_others(admin, people, anon):
    me, other = await people("QA Tôi"), await people("QA Người Khác")
    mine = await counter_order(admin, me.code)
    theirs = await counter_order(admin, other.code, hour=mine["hour"])
    s_mine = await slot_of(me.client, mine["court"]["code"], mine["hour"])
    assert (
        s_mine["mine"] is True
        and s_mine["order_code"] == mine["order_code"]
        and s_mine["state"] == "booked"
    )
    s_other = await slot_of(me.client, theirs["court"]["code"], theirs["hour"])
    assert (
        s_other["state"] == "booked" and s_other["mine"] is False and s_other["order_code"] is None
    )
    assert s_other["event_code"] is None and s_other["has_ticket"] is False
    r = await me.client.get(CAL, params={"date": today().isoformat()})
    assert theirs["order_code"] not in r.text and theirs["item_code"] not in r.text
    assert other.phone not in r.text and "QA Người Khác" not in r.text
    # API công khai không bao giờ có order_code / mine, kể cả khi gọi bằng cookie hội viên
    for client in (anon, me.client):
        pub = await client.get(f"{WEB}/calendar", params={"date": today().isoformat()})
        assert pub.status_code == 200
        assert mine["order_code"] not in pub.text and theirs["order_code"] not in pub.text
        for res in pub.json()["resources"]:
            for s in res["slots"]:
                assert "order_code" not in s and "mine" not in s and "has_ticket" not in s


async def test_ac1_member_calendar_access_rules_and_past_date(admin, people, anon, customer):
    me = await people("QA Lịch")
    assert (await anon.get(CAL, params={"date": today().isoformat()})).status_code == 401
    r = await customer.get(CAL, params={"date": today().isoformat()})
    assert r.status_code == 403 and code_of(r) == "E-HV-8"
    r = await me.client.get(CAL, params={"date": "2020-01-01"})
    assert r.status_code == 422 and code_of(r) == "E-WEB-2"
    assert (await me.client.get(CAL, params={"date": "không-phải-ngày"})).status_code == 422
    ok = await me.client.get(CAL, params={"date": tomorrow().isoformat()})
    assert ok.status_code == 200 and "online_enabled" in ok.json() and "hold_minutes" in ok.json()


async def test_ac1_event_slots_expose_event_code_and_has_ticket_after_buying(admin, people):
    me = await people("QA Có Vé")
    ev = await mk_event(admin, capacity=5, price=20_000)
    s = await slot_of(me.client, ev["court"]["code"], 9, tomorrow())
    assert (
        s["event_code"] == ev["code"]
        and s["has_ticket"] is False
        and s["mine"] is False
        and s["order_code"] is None
    )
    co = (await buy(me.client, ev["code"], 1, as_member=True, name=me.name)).json()
    await simulate(admin, co["pay_ref"], co["amount"])
    for h in (9, 10):
        s = await slot_of(me.client, ev["court"]["code"], h, tomorrow())
        assert s["has_ticket"] is True and s["event_code"] == ev["code"], (
            "ô nào của sự kiện cũng có dấu Có vé"
        )
    other = await people("QA Không Vé")
    assert (await slot_of(other.client, ev["court"]["code"], 9, tomorrow()))["has_ticket"] is False


# ============================================================ AC2 / AC3 / AC4 đơn của mình


async def test_ac2_my_order_detail_unpaid_counter_then_paid_invoice(admin, people):
    me = await people("QA Đơn Của Tôi")
    o = await counter_order(admin, me.code)
    r = await me.client.get(f"{MA}/bookings/{o['order_code']}")
    assert r.status_code == 200 and "no-store" in r.headers.get("cache-control", "")
    d = r.json()
    assert (
        d["order_code"] == o["order_code"]
        and d["source"] == "counter"
        and d["pay_status"] == "unpaid"
    )
    assert d["play_date"] == today().isoformat() and d["amount"] > 0 and len(d["items"]) == 1
    it = d["items"][0]
    assert (
        it["code"] == o["item_code"]
        and it["resource_name"] == o["court"]["name"]
        and it["hours"] == 1
        and it["pay_status"] == "unpaid"
    )
    assert me.phone not in r.text, "không trả SĐT"
    # chưa thanh toán → chưa có hóa đơn trong Lịch sử thanh toán
    assert (await me.client.get(f"{MA}/payments/{it['code']}")).status_code == 404
    # quầy thu tiền → Đã thanh toán + hóa đơn đọc được
    c = await admin.post(
        f"{BK}/orders/{o['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert c.status_code == 200, c.text
    d2 = (await me.client.get(f"{MA}/bookings/{o['order_code']}")).json()
    assert d2["pay_status"] == "paid" and d2["items"][0]["pay_status"] == "paid"
    assert (await me.client.get(f"{MA}/payments/{d2['items'][0]['code']}")).status_code == 200


async def test_ac3_ac4_other_peoples_orders_are_404_identical_to_missing(admin, people, anon):
    me, other = await people("QA Người Xem"), await people("QA Chủ Đơn")
    theirs = await counter_order(admin, other.code)
    answers = []
    for path in (theirs["order_code"], theirs["item_code"], "BK-20000101-999"):
        r = await me.client.get(f"{MA}/bookings/{path}")
        assert r.status_code == 404 and code_of(r) == "E-NOT-FOUND", (path, r.status_code)
        answers.append(r.json())
    assert all(a == answers[0] for a in answers), (
        "mã của người khác và mã không tồn tại trả giống hệt nhau"
    )
    for bad in ("BK-bậy", "x" * 50):
        assert (await me.client.get(f"{MA}/bookings/{bad}")).status_code in (404, 422), bad
    assert (await me.client.get(f"{MA}/payments/{theirs['item_code']}")).status_code == 404
    assert (await anon.get(f"{MA}/bookings/{theirs['order_code']}")).status_code == 401
    assert (await other.client.get(f"{MA}/bookings/{theirs['order_code']}")).status_code == 200, (
        "chủ đơn vẫn xem được"
    )


async def test_ac4_temp_profile_booking_is_not_visible_to_a_member_with_the_same_name(
    admin, people
):
    me = await people("QA Trùng Tên")
    o = await counter_order(admin, "", customer=temp("QA Trùng Tên", random_phone()))
    assert (await me.client.get(f"{MA}/bookings/{o['order_code']}")).status_code == 404


# ============================================================ mua vé bằng as_member; AC10, AC13, AC14


async def test_as_member_needs_a_linked_active_member(admin, anon, customer):
    ev = await mk_event(admin)
    r = await buy(customer, ev["code"], 1, as_member=True, name="Khách chưa là hội viên")
    assert r.status_code == 403 and code_of(r) == "E-HV-8"
    r = await buy(anon, ev["code"], 1, as_member=True, name="Không đăng nhập")
    assert r.status_code in (401, 403), r.text
    assert (await info(anon, ev["code"])).json()["taken"] == 0


async def test_ac13_member_ticket_flows_into_history_admin_screens_and_reports(admin, people):
    me = await people("QA Mua Vé Hội Viên")
    ev = await today_event(admin, capacity=6, price=45_000, name="QA Sự kiện hội viên")
    base = (await admin.get(f"{API}/admin/reports/overview")).json()["revenue"]
    co = (await buy(me.client, ev["code"], 2, as_member=True, name=me.name)).json()
    assert co["kind"] == "ticket" and co["amount"] == 90_000 and co["event"]["seats"] == 2
    d = (await info(me.client, ev["code"])).json()
    assert d["taken"] == 2 and d["my_tickets"] == [], "chưa trả: chưa có vé"
    await simulate(admin, co["pay_ref"], co["amount"])
    await drain_outbox()
    d = (await info(me.client, ev["code"])).json()
    assert {t["code"]: t["pay_status"] for t in d["my_tickets"]} == {
        f"{ev['code']}-V01": "paid",
        f"{ev['code']}-V02": "paid",
    }
    # vé gắn vào hồ sơ hội viên (as_member), nguồn online
    rows = await q(
        "SELECT member_code, customer_kind, source::text AS src FROM booking.ticket WHERE code LIKE :c",
        c=f"{ev['code']}-V%",
    )
    assert [(r["member_code"], r["customer_kind"], r["src"]) for r in rows] == [
        (me.code, "member", "online")
    ] * 2
    # Lịch sử thanh toán của hội viên + hóa đơn
    pays = (await me.client.get(f"{MA}/payments", params={"kind": "ticket"})).json()
    assert pays["items"], pays
    code = pays["items"][0]["code"]
    assert (await me.client.get(f"{MA}/payments/{code}")).status_code == 200
    # Màn sự kiện quản trị: vé thường, nguồn Online
    sess = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert sess["taken"] == 2 and sorted(t["source"] for t in sess["tickets"]) == [
        "online",
        "online",
    ]
    assert {t["payment_status"] for t in sess["tickets"]} == {"paid"} and sess["active_holds"] == []
    # Lịch sử giao dịch (Admin)
    tx = (
        await admin.get(
            f"{BK}/transactions",
            params={"q": ev["code"], "from": today().isoformat(), "to": today().isoformat()},
        )
    ).json()
    tickets = [r for r in tx["rows"] if r["kind"] == "ticket" and r["code"].startswith(ev["code"])]
    assert len(tickets) == 2 and all(
        r["source"] == "online" and r["payment_status"] == "paid" and r["amount"] == 45_000
        for r in tickets
    )
    # Báo cáo doanh thu: cộng đúng một lần
    after = (await admin.get(f"{API}/admin/reports/overview")).json()["revenue"]
    assert after["current"] - base["current"] == 90_000, (base, after)


async def test_ac14_audit_and_outbox_for_online_ticket_payment(admin, people):
    me = await people("QA Audit Vé")
    ev = await mk_event(admin, capacity=4, price=33_000)
    base = (await q("SELECT coalesce(max(id),0) AS m FROM audit_log"))[0]["m"]
    co = (await buy(me.client, ev["code"], 2, as_member=True, name=me.name)).json()
    await simulate(admin, co["pay_ref"], co["amount"])
    rows = await q(
        "SELECT actor_type, detail::text AS d FROM audit_log WHERE action='ticket.online.paid' AND id > :b",
        b=base,
    )
    assert len(rows) == 1 and rows[0]["actor_type"] == "system"
    d = rows[0]["d"]
    assert co["order_code"] in d and f"{ev['code']}-V01" in d and f"{ev['code']}-V02" in d
    assert me.phone not in d and me.phone[1:] not in d, "không SĐT đầy đủ trong nhật ký"
    async with SessionLocal() as s:
        kinds = list(
            await s.scalars(
                select(OutboxEvent.event_type).where(
                    OutboxEvent.payload.cast(String).like(f"%{ev['code']}%")
                )
            )
        )
    assert "ticket.online_paid" in kinds and kinds.count("ticket.created") == 2, kinds
    await simulate(admin, co["pay_ref"], co["amount"])  # gửi lại
    again = await q(
        "SELECT count(*) AS n FROM audit_log WHERE action='ticket.online.paid' AND id > :b", b=base
    )
    assert again[0]["n"] == 1, "tiền về lặp lại không ghi nhật ký lần hai"


async def test_checkout_token_is_the_buyers_secret(admin, people, anon):
    me = await people("QA Token")
    ev = await mk_event(admin)
    co = (await buy(me.client, ev["code"], 1, as_member=True, name=me.name)).json()
    assert (await anon.get(f"{WEB}/checkouts/{uuid.uuid4().hex}")).status_code == 404
    assert (await anon.get(f"{WEB}/checkouts/{co['token']}")).status_code == 200

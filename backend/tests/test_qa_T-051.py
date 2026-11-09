# ruff: noqa: E501
"""QA T-051 (API, AC1–AC14): Admin hủy booking / buổi định kỳ / đơn / vé – góc nhìn độc lập với ``test_booking_cancel.py``.

Dùng đồng hồ thật (ngày mai hoặc giờ kế tiếp hôm nay), không đóng băng đồng hồ. Ưu tiên: AC3 khung trống + đặt lại,
AC5 báo cáo, AC12 tiền về trễ, AC13 đồng thời; thêm: Nhân viên không thấy ``cancel`` ở mọi phản hồi, Danh sách sân loại
phòng đã hủy trong ngày thật, thông báo mỗi phòng một lần (sự kiện + job), thông báo chủ vé là hội viên.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core import events
from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Allocation, Booking, OutboxEvent
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.common import Me
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import (
    BK,
    book,
    book_order,
    new_court,
    random_phone,
    safe_hour,
    temp,
    today,
)
from tests.helpers_web import WEB, checkout, simulate, tomorrow
from tests.qa_tickets import buy, mk_event, tickets_of
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, notifications, post

people = base.people
FD = f"{API}/front-desk"
REASON = "QA khách báo bận"


@pytest.fixture
def clock(monkeypatch):
    """Đóng băng đồng hồ engine ở 00:30 ngày mai (đặt quầy chỉ cho "hôm nay" của engine).
    Chỉ ảnh hưởng engine; báo cáo / phòng chơi vẫn dùng giờ thật."""
    day = tomorrow()
    frozen = datetime(day.year, day.month, day.day, 0, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)


def code_of(r) -> str:
    return r.json()["detail"]["code"]


async def new_booking(staff, admin, hour=10, day=None, customer=None, court=None) -> dict:
    court = court or await new_court(admin)
    r = await book(
        staff,
        court["code"],
        hour,
        customer=customer or temp("QA Khách Hủy", random_phone()),
        day=day or tomorrow(),
    )
    assert r.status_code == 201, r.text
    return {**r.json(), "court": court}


async def cancel(client, code, version=1, reason=REASON, headers=None, **extra):
    return await client.post(
        f"{FD}/items/{code}/cancel",
        json={"reason": reason, "version": version, **extra},
        headers=headers or idem(),
    )


async def collect(client, code, version=1):
    return await client.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": version}, headers=idem()
    )


async def row_of(code: str) -> Booking:
    async with SessionLocal() as s:
        return await s.scalar(select(Booking).where(Booking.code == code))


async def active_allocations(code: str) -> int:
    async with SessionLocal() as s:
        bid = await s.scalar(select(Booking.id).where(Booking.code == code))
        return await s.scalar(
            select(func.count())
            .select_from(Allocation)
            .where(Allocation.booking_id == bid, Allocation.active)
        )


def cancel_actions(node, path="") -> list[str]:
    """Mọi chỗ trong JSON có khóa ``actions`` chứa ``cancel``."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "actions" and isinstance(v, list) and "cancel" in v:
                found.append(path or "$")
            found += cancel_actions(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += cancel_actions(v, f"{path}[{i}]")
    return found


# ---------------------------------------------------------------- AC1: ai thấy / gọi được "hủy"


async def test_ac1_staff_never_sees_cancel_in_any_response_admin_does(admin, staff):
    """Nhân viên chỉ đặt quầy cho hôm nay -> dùng các khung chưa bắt đầu trong ngày."""
    h = await safe_hour() + 1
    if h + 3 > 23:
        pytest.skip("không còn đủ khung giờ chưa bắt đầu trong ngày")
    court = await new_court(admin)
    day = today()
    seen: dict[str, list] = {"staff": [], "admin": []}

    async def probe(label, client, r):
        assert r.status_code in (200, 201), (label, r.status_code, r.text)
        seen["staff" if client is staff else "admin"].append((label, cancel_actions(r.json())))

    created = await book(
        staff, court["code"], h, customer=temp("QA Nhân Viên", random_phone()), day=day
    )
    assert created.status_code == 201, created.text
    code = created.json()["code"]
    order = await book_order(
        staff,
        [(court["code"], h + 1, h + 2), (court["code"], h + 2, h + 3)],
        customer=temp("QA Đơn NV", random_phone()),
        day=day,
    )
    assert order.status_code == 201, order.text
    ev = await mk_event(admin, day=tomorrow(), hours=(15, 17), capacity=3)
    await probe("create-booking", staff, created)
    await probe("create-order", staff, order)
    for client in (staff, admin):
        await probe("get-item", client, await client.get(f"{BK}/items/{code}"))
        await probe(
            "calendar", client, await client.get(f"{BK}/calendar", params={"date": day.isoformat()})
        )
        await probe("session", client, await client.get(f"{BK}/sessions/{ev['code']}"))
        await probe(
            "transactions",
            client,
            await client.get(
                f"{BK}/transactions", params={"from": day.isoformat(), "to": day.isoformat()}
            ),
        )
    await probe("collect", staff, await collect(staff, order.json()["bookings"][0]["code"]))
    leaks = [(label, hits) for label, hits in seen["staff"] if hits]
    assert not leaks, f"Nhân viên thấy 'cancel' trong actions: {leaks}"
    admin_get = next(h_ for label, h_ in seen["admin"] if label == "get-item")
    assert admin_get, "Admin phải thấy cancel ở GET /booking/items/{code} của mục chưa bắt đầu"


async def test_ac1_other_roles_cannot_cancel_anything(admin, staff, anon, customer, clock):
    b = await new_booking(staff, admin)
    code, order = b["code"], b["order_code"]
    for who, expected in ((anon, 401), (customer, 403), (staff, 403)):
        assert (await cancel(who, code)).status_code == expected, who
        assert (await who.get(f"{FD}/orders/{order}/cancel-preview")).status_code == expected
        r = await who.post(
            f"{FD}/orders/{order}/cancel", json={"reason": REASON, "codes": [code]}, headers=idem()
        )
        assert r.status_code == expected
    assert (await row_of(code)).payment_status != "cancelled"
    # Không có Idempotency-Key -> bị từ chối, không hủy
    r = await admin.post(f"{FD}/items/{code}/cancel", json={"reason": REASON, "version": 1})
    assert r.status_code in (400, 422)
    assert (await row_of(code)).payment_status != "cancelled"


async def test_ac2_input_validation_boundaries(admin, staff, clock):
    b = await new_booking(staff, admin)
    code = b["code"]
    for bad in ("", "   ", "\n\t", "x" * 201):
        r = await cancel(admin, code, reason=bad)
        assert r.status_code == 422 and code_of(r) == "E-001", repr(bad[:5])
    r = await admin.post(f"{FD}/items/{code}/cancel", json={"version": 1}, headers=idem())
    assert r.status_code == 422, "thiếu lý do"
    r = await admin.post(f"{FD}/items/{code}/cancel", json={"reason": REASON}, headers=idem())
    assert r.status_code == 422, "thiếu version"
    assert (await cancel(admin, "BK-20990101-999-01")).status_code == 404
    assert (await row_of(code)).payment_status != "cancelled"
    # đúng 200 ký tự được; khoảng trắng thừa bị cắt
    r = await cancel(admin, code, reason="  " + "ạ" * 200 + "  ")
    assert r.status_code == 200 and len(r.json()["payment"]["cancel_reason"]) == 200


# ---------------------------------------------------------------- AC3: khung trống và đặt lại


async def test_ac3_slot_is_free_everywhere_and_neighbours_keep_their_hours(
    admin, staff, anon, clock
):
    court = await new_court(admin)
    day = tomorrow()
    a = await new_booking(staff, admin, hour=10, day=day, court=court)
    n = await new_booking(staff, admin, hour=11, day=day, court=court)  # liền kề
    p = await new_booking(staff, admin, hour=9, day=day, court=court)  # liền kề trước

    # Đặt trùng bị chặn khi chưa hủy
    two = await book(
        staff, court["code"], 10, 12, customer=temp("QA Chen", random_phone()), day=day
    )
    assert two.status_code == 409
    assert (await cancel(admin, a["code"])).status_code == 200

    assert await active_allocations(a["code"]) == 0
    assert await active_allocations(n["code"]) == 1 and await active_allocations(p["code"]) == 1
    cal = (await admin.get(f"{BK}/calendar", params={"date": day.isoformat()})).json()
    codes = [bl["code"] for bl in cal["blocks"]]
    assert a["code"] not in codes and n["code"] in codes and p["code"] in codes
    # Đặt cả khung 10–12 vẫn bị chặn vì 11–12 còn người; đặt đúng 10–11 thì được
    two = await book(
        staff, court["code"], 10, 12, customer=temp("QA Chen 2", random_phone()), day=day
    )
    assert two.status_code == 409
    again = await book(
        staff, court["code"], 10, customer=temp("QA Đặt Lại", random_phone()), day=day
    )
    assert again.status_code == 201 and again.json()["code"] != a["code"]
    # Đặt chồng lên buổi vừa đặt lại vẫn bị constraint chặn
    third = await book(
        staff, court["code"], 10, customer=temp("QA Thứ Ba", random_phone()), day=day
    )
    assert third.status_code == 409 and code_of(third) == "E-003"

    # Hủy hai buổi liền nhau -> đặt được một khối 2 giờ
    assert (await cancel(admin, again.json()["code"])).status_code == 200
    assert (await cancel(admin, n["code"])).status_code == 200
    block = await book(
        staff, court["code"], 10, 12, customer=temp("QA Hai Giờ", random_phone()), day=day
    )
    assert block.status_code == 201, block.text
    # Buổi 9–10 không bị ảnh hưởng
    assert (await row_of(p["code"])).payment_status == "unpaid"
    assert await active_allocations(p["code"]) == 1


async def test_ac3_online_rebooking_of_a_freed_slot_and_public_calendar(admin, staff, anon, clock):
    court = await new_court(admin)
    day = tomorrow()
    b = await new_booking(staff, admin, hour=19, day=day, court=court)
    blocked = await checkout(anon, [(court["code"], 19)], day=day)
    assert blocked.status_code == 409, "khung đã có người đặt"
    assert (await cancel(admin, b["code"])).status_code == 200
    ok = await checkout(anon, [(court["code"], 19)], day=day)
    assert ok.status_code == 201, ok.text
    cal = await anon.get(f"{WEB}/calendar", params={"date": day.isoformat()})
    assert cal.status_code == 200 and b["code"] not in cal.text
    # Khung đang được giữ chỗ online thì không đặt chồng được dù booking cũ đã hủy
    blocked = await book(
        staff, court["code"], 19, customer=temp("QA Chen Giữ", random_phone()), day=day
    )
    assert blocked.status_code == 409


async def test_ac3_cancelled_booking_is_terminal_never_revives(admin, staff, clock):
    b = await new_booking(staff, admin)
    code = b["code"]
    assert (await cancel(admin, code)).status_code == 200
    assert (await collect(admin, code, version=2)).status_code == 409
    r = await admin.post(
        f"{BK}/items/{code}/uncollectible", json={"reason": "x", "version": 2}, headers=idem()
    )
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"
    r = await cancel(admin, code, version=2)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"
    item = (await admin.get(f"{BK}/items/{code}")).json()
    assert item["actions"] == [] and item["payment"]["payment_status"] == "cancelled"
    assert await active_allocations(code) == 0


# ---------------------------------------------------------------- AC5: báo cáo (ngày chơi, đồng hồ thật)


async def test_ac5_report_revenue_daily_and_heatmap_drop_exactly_the_cancelled_session(
    admin, staff
):
    h = await safe_hour() + 2
    if h > 22:
        pytest.skip("không còn khung giờ chưa bắt đầu trong ngày")
    paid = await new_booking(staff, admin, hour=h, day=today())
    amount = paid["payment"]["amount"]
    assert (await collect(admin, paid["code"])).status_code == 200
    url = f"{API}/admin/reports/overview"
    yday = (today() - timedelta(days=1)).isoformat()
    before = (await admin.get(url, params={"from": yday, "to": today().isoformat()})).json()

    r = await cancel(admin, paid["code"], version=2, refund_confirmed=True)
    assert r.status_code == 200, r.text
    after = (await admin.get(url, params={"from": yday, "to": today().isoformat()})).json()

    assert after["revenue"]["current"] == before["revenue"]["current"] - amount
    daily_b = {d["date"]: d["revenue"] for d in before["daily"]}
    daily_a = {d["date"]: d["revenue"] for d in after["daily"]}
    assert daily_a[today().isoformat()] == daily_b[today().isoformat()] - amount
    assert daily_a[yday] == daily_b[yday], "ngày đã qua không đổi"
    assert after["bookings"]["current"] == before["bookings"]["current"] - 1
    booked_b = sum(c["booked_hours"] for row in before["heatmap"]["cells"] for c in row)
    booked_a = sum(c["booked_hours"] for row in after["heatmap"]["cells"] for c in row)
    assert booked_a == pytest.approx(booked_b - 1), "công suất giảm đúng 1 giờ"
    court_b = next(c for c in before["courts"] if c["code"] == paid["court"]["code"])["revenue"]
    court_a = next(c for c in after["courts"] if c["code"] == paid["court"]["code"])["revenue"]
    assert court_a == court_b - amount
    # Khoản chưa thu rồi hủy: không đổi doanh thu
    unpaid = await new_booking(staff, admin, hour=h, day=today())
    mid = (await admin.get(url, params={"from": yday, "to": today().isoformat()})).json()
    assert (await cancel(admin, unpaid["code"])).status_code == 200
    end = (await admin.get(url, params={"from": yday, "to": today().isoformat()})).json()
    assert end["revenue"]["current"] == mid["revenue"]["current"] == after["revenue"]["current"]


# ---------------------------------------------------------------- AC9: trận đấu


async def test_ac9_matches_no_longer_block_and_finished_results_survive(
    admin, staff, people, clock
):
    """T-052 đổi T-051: E-PAY-8 đã bỏ. Chưa tới giờ + trận `finished` vẫn hủy được; trận đã xong giữ
    nguyên và vẫn ở Lịch sử chơi (chỉ đọc); trận `drawn` -> `abandoned`; phòng không còn ở Danh sách sân."""
    host, other = await people("QA Chủ Trận"), await people("QA Người Kia")
    court = await new_court(admin)
    a = await new_booking(
        staff, admin, hour=8, day=tomorrow(), court=court, customer={"member_code": host.code}
    )
    b = await new_booking(
        staff, admin, hour=9, day=tomorrow(), court=court, customer={"member_code": host.code}
    )
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, [a["code"], b["code"]])
        await s.commit()
        ra = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == a["code"]))
        rb = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == b["code"]))
    await add_match(ra.id, 1, [host.customer_id], [other.customer_id], status="finished", win="a")
    await add_match(rb.id, 1, [host.customer_id], [other.customer_id], status="drawn", win="a")
    month = tomorrow().strftime("%Y-%m")

    async def history() -> dict:
        r = await host.client.get(f"{MA}/play-history", params={"month": month})
        assert r.status_code == 200, r.text
        return r.json()

    before = await history()
    r = await cancel(admin, a["code"])
    assert r.status_code == 200, r.text  # không còn E-PAY-8
    assert (await row_of(a["code"])).payment_status == "cancelled"
    assert await active_allocations(a["code"]) == 0
    after = await history()
    assert after["summary"] == before["summary"], "số trận / thắng / thua không đổi sau khi hủy"
    assert any(i["room_id"] == ra.id and i["matches"] == 1 for i in after["items"])
    ms = (await host.client.get(f"{MA}/rooms/{ra.id}/matches")).json()
    assert ms["total"] == 1
    assert (await host.client.get(f"{MA}/rooms/{ra.id}/ranking")).status_code == 200
    assert (await host.client.get(f"{MA}/rooms/{ra.id}")).status_code == 200
    listed = (await host.client.get(f"{MA}/rooms", params={"scope": "all"})).json()["items"]
    assert ra.id not in [x["id"] for x in listed], "không hiện ở Danh sách sân"

    r = await cancel(admin, b["code"])
    assert r.status_code == 200, r.text
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **await _outbox(b["code"])})
    async with SessionLocal() as s:
        m = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == rb.id))
        fin = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == ra.id))
    assert m.status == "abandoned" and fin.status == "finished"
    # phòng không có trận đã xong: ẩn như T-051
    assert (await host.client.get(f"{MA}/rooms/{rb.id}")).status_code == 404


# ---------------------------------------------------------------- AC10/AC11: phòng, danh sách sân, thông báo


async def _room(admin, staff, host, hour, day):
    b = await new_booking(staff, admin, hour=hour, day=day, customer={"member_code": host.code})
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, [b["code"]])
        await s.commit()
        room = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == b["code"]))
    assert room is not None
    return b, room


async def _outbox(code: str) -> dict:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "booking.cancelled")
        )
        payload = next((r.payload for r in rows if r.payload["code"] == code), None)
    assert payload is not None, f"không có sự kiện booking.cancelled cho {code}"
    return payload


async def test_list_rooms_today_drops_cancelled_room_without_worker(admin, staff, people):
    h = await safe_hour() + 2
    if h > 22:
        pytest.skip("không còn khung giờ chưa bắt đầu trong ngày")
    host = await people("QA Chủ Hôm Nay")
    b, room = await _room(admin, staff, host, h, today())
    for scope in ("all", "mine"):
        r = await host.client.get(f"{MA}/rooms", params={"scope": scope})
        assert r.status_code == 200, r.text
        assert room.id in [x["id"] for x in r.json()["items"]], scope
    assert (await cancel(admin, b["code"])).status_code == 200
    for scope in ("all", "mine"):
        r = await host.client.get(f"{MA}/rooms", params={"scope": scope})
        assert r.status_code == 200, r.text
        assert room.id not in [x["id"] for x in r.json()["items"]], scope
    assert (await host.client.get(f"{MA}/rooms/{room.id}")).status_code == 404


def _me(hv) -> Me:
    return Me(0, hv.customer_id)


async def test_room_notifications_are_sent_once_even_if_event_and_job_both_run(
    admin, staff, people, clock
):
    owner, guest = await people("QA Chủ Đơn"), await people("QA Khách Phòng")
    b, room = await _room(admin, staff, owner, 14, tomorrow())
    r = await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    assert r.status_code == 200, r.text
    assert (await cancel(admin, b["code"])).status_code == 200
    payload = await _outbox(b["code"])
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    async with SessionLocal() as s:
        await lifecycle._close_any_cancelled(s, datetime.now(UTC))
        await s.commit()
    async with SessionLocal() as s:  # job chạy lần hai cũng không báo thêm
        await lifecycle._close_any_cancelled(s, datetime.now(UTC))
        await s.commit()

    def texts(d):
        return [n["text"] for n in d["items"]]

    closed = "đã bị hủy nên phòng đã đóng"
    got = [t for t in texts(await notifications(guest.client)) if closed in t]
    assert len(got) == 1, got
    owned = texts(await notifications(owner.client))
    assert len([t for t in owned if "đã bị sân hủy" in t]) == 1, owned
    assert not [t for t in owned if closed in t], "chủ đơn chỉ nhận một thông báo"
    assert not any(REASON in t for t in owned + texts(await notifications(guest.client)))
    async with SessionLocal() as s:
        assert (await s.get(PlayRoom, room.id)).status == "closed"


async def test_member_ticket_owner_gets_one_notification_without_reason(admin, people):
    hv = await people("QA Chủ Vé Hội Viên")
    ev = await mk_event(admin, day=tomorrow(), hours=(9, 11), capacity=2)
    r = await buy(hv.client, ev["code"], seats=1, as_member=True)
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    [ticket] = [t["code"] for t in await tickets_of(ev["code"])]
    assert (await cancel(admin, ticket, refund_confirmed=True)).status_code == 200
    payload = await _outbox(ticket)
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    items = [
        n for n in (await notifications(hv.client))["items"] if n["kind"] == "booking.cancelled"
    ]
    assert items, "chủ vé là hội viên phải nhận thông báo hủy"
    assert len([n for n in items if ticket in n["text"] or co["order_code"] in n["text"]]) <= 2
    text = items[0]["text"]
    refund = f"{co['amount']:,}".replace(",", ".")
    assert "đã bị sân hủy" in text and f"hoàn {refund} đ" in text, text
    assert REASON not in text
    # Vé của hội viên đã hủy không còn trong vé của tôi
    mine = await hv.client.get(f"{MA}/tickets")
    if mine.status_code == 200:
        assert ticket not in mine.text


# ---------------------------------------------------------------- AC12: tiền về trễ


async def test_ac12_late_money_replays_and_never_disturbs_the_rebooked_slot(
    anon, admin, staff, clock
):
    court = await new_court(admin)
    day = tomorrow()
    r = await checkout(anon, [(court["code"], 18)], day=day, phone=random_phone())
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    async with SessionLocal() as s:
        old = await s.scalar(select(Booking).where(Booking.code.like(f"{co['order_code']}-%")))
    assert (await cancel(admin, old.code, refund_confirmed=True)).status_code == 200
    # Khung được đặt lại bởi người khác
    fresh = await book(
        staff, court["code"], 18, customer=temp("QA Người Mới", random_phone()), day=day
    )
    assert fresh.status_code == 201
    # Tiền về trễ (cả khi webhook gửi lặp): không tạo booking, không đụng booking mới
    for _ in range(2):
        assert await simulate(admin, co["pay_ref"], co["amount"]) != "applied", (
            "tiền về sau khi hủy không được áp dụng lại"
        )
    async with SessionLocal() as s:
        same = list(
            await s.scalars(select(Booking).where(Booking.code.like(f"{co['order_code']}-%")))
        )
        new_row = await s.scalar(select(Booking).where(Booking.code == fresh.json()["code"]))
    assert [b.payment_status for b in same] == ["cancelled"]
    assert new_row.payment_status == "unpaid" and await active_allocations(new_row.code) == 1
    assert await active_allocations(old.code) == 0
    # Sổ tiền vào: khoản đã thu rồi hủy có đúng 1 dòng thu + 1 dòng hoàn; tiền về trễ không ghi thêm dòng
    wide = {
        "from": (day - timedelta(days=3)).isoformat(),
        "to": (day + timedelta(days=3)).isoformat(),
        "q": old.code,
    }
    tx = (await admin.get(f"{BK}/transactions", params=wide)).json()
    assert sorted(e["kind"] for e in tx["items"]) == ["in", "refund"], tx["items"]
    assert sum(e["amount"] if e["kind"] == "in" else -e["amount"] for e in tx["items"]) == 0
    assert all([i["code"] for i in e["items"]] == [old.code] for e in tx["items"])
    assert await simulate(admin, co["pay_ref"], co["amount"]) != "applied"
    again = (await admin.get(f"{BK}/transactions", params=wide)).json()
    assert again["total"] == tx["total"] == 2, "tiền về trễ vào 'cần xử lý', không vào sổ"


# ---------------------------------------------------------------- AC13: đồng thời


async def test_ac13_parallel_cancels_exactly_one_wins_one_audit_one_event(admin, staff, clock):
    b = await new_booking(staff, admin)
    code = b["code"]
    res = await asyncio.gather(*[cancel(admin, code) for _ in range(6)])
    codes = sorted(r.status_code for r in res)
    assert codes.count(200) == 1 and all(c in (200, 409) for c in codes), [r.text for r in res]
    for r in res:
        if r.status_code == 409:
            assert code_of(r) in ("E-PAY-6", "E-012")
    async with SessionLocal() as s:
        audits = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payment.cancelled", AuditLog.entity_code == code)
        )
        events_n = await s.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.event_type == "booking.cancelled",
                OutboxEvent.payload["code"].astext == code,
            )
        )
    assert audits == 1 and events_n == 1
    # Cùng Idempotency-Key chạy song song: kết quả giống nhau, vẫn một lần hủy
    c = await new_booking(staff, admin)
    key = idem()
    same = await asyncio.gather(*[cancel(admin, c["code"], headers=key) for _ in range(4)])
    assert {r.status_code for r in same} <= {200, 409}
    assert any(r.status_code == 200 for r in same)
    assert (await row_of(c["code"])).payment_status == "cancelled"
    async with SessionLocal() as s:
        audits = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payment.cancelled", AuditLog.entity_code == c["code"])
        )
    assert audits == 1


async def test_ac13_cancel_races_with_rebooking_and_collect_leave_consistent_data(
    admin, staff, clock
):
    b = await new_booking(staff, admin, hour=7)
    code, court = b["code"], b["court"]["code"]
    cancel_r, book_r, collect_r = await asyncio.gather(
        cancel(admin, code),
        book(staff, court, 7, customer=temp("QA Đua Đặt", random_phone()), day=tomorrow()),
        collect(admin, code),
    )
    row = await row_of(code)
    assert row.payment_status in ("cancelled", "paid")
    if row.payment_status == "cancelled":
        assert cancel_r.status_code == 200 and collect_r.status_code == 409
        assert row.paid_at is None and await active_allocations(code) == 0
    else:
        assert cancel_r.status_code == 409 and collect_r.status_code == 200
        assert row.cancelled_at is None and await active_allocations(code) == 1
        assert book_r.status_code == 409, "booking cũ còn nguyên nên khung không trống"
    # Không bao giờ có hai booking còn hiệu lực cùng khung
    async with SessionLocal() as s:
        active = await s.scalar(
            select(func.count())
            .select_from(Allocation)
            .join(Booking, Booking.id == Allocation.booking_id)
            .where(
                Allocation.active,
                Booking.resource_id == row.resource_id,
                Booking.play_date == row.play_date,
                Booking.start_at == row.start_at,
            )
        )
    assert active == 1


async def test_ac13_order_cancel_races_with_single_block_cancel(admin, staff, clock):
    court = await new_court(admin)
    r = await book_order(
        staff,
        [(court["code"], 8, 9), (court["code"], 10, 11), (court["code"], 12, 13)],
        customer=temp("QA Đơn Đua", random_phone()),
        day=tomorrow(),
    )
    assert r.status_code == 201, r.text
    order = r.json()
    codes = [b["code"] for b in order["bookings"]]
    whole, single = await asyncio.gather(
        admin.post(
            f"{FD}/orders/{order['order_code']}/cancel",
            json={"reason": REASON, "codes": codes},
            headers=idem(),
        ),
        cancel(admin, codes[1]),
    )
    assert whole.status_code in (200, 409, 422) and single.status_code in (200, 409), (
        whole.text,
        single.text,
    )
    assert whole.status_code != 500 and single.status_code != 500
    async with SessionLocal() as s:
        rows = list(await s.scalars(select(Booking).where(Booking.code.in_(codes))))
        audits = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payment.cancelled", AuditLog.entity_code.in_(codes))
        )
    if whole.status_code == 200:
        assert all(b.payment_status == "cancelled" for b in rows)
        assert audits == 3, "mỗi khối đúng một dòng nhật ký, kể cả khi hủy lẻ cùng lúc"
        done = set(whole.json()["cancelled"]) | {s_["code"] for s_ in whole.json()["skipped"]}
        assert done == set(codes)
    assert len({b.code for b in rows if b.payment_status == "cancelled"}) == audits


# ---------------------------------------------------------------- AC6/AC7: hủy lẻ, hủy cả đơn


async def test_ac7_order_cancel_requires_refund_for_the_whole_command_and_keeps_totals(
    admin, staff, clock
):
    court = await new_court(admin)
    r = await book_order(
        staff,
        [(court["code"], 8, 9), (court["code"], 10, 11)],
        customer=temp("QA Đơn Hoàn", random_phone()),
        day=tomorrow(),
    )
    order = r.json()
    paid, unpaid = [b["code"] for b in order["bookings"]]
    assert (await collect(admin, paid)).status_code == 200
    pre = (await admin.get(f"{FD}/orders/{order['order_code']}/cancel-preview")).json()
    amounts = {b["code"]: b["payment"]["amount"] for b in order["bookings"]}
    assert pre["refund_total"] == amounts[paid] and pre["unpaid_total"] == amounts[unpaid]
    url = f"{FD}/orders/{order['order_code']}/cancel"
    r = await admin.post(url, json={"reason": REASON, "codes": [paid, unpaid]}, headers=idem())
    assert r.status_code == 422 and code_of(r) == "E-PAY-7"
    for code in (paid, unpaid):
        assert (await row_of(code)).payment_status != "cancelled", (
            "chặn cả lệnh, không hủy một phần"
        )
    r = await admin.post(
        url,
        json={"reason": REASON, "codes": [paid, unpaid], "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["refund_total"] == amounts[paid]
    assert sorted(r.json()["cancelled"]) == sorted([paid, unpaid])
    # Gọi lại cho đơn đã hủy hết: không 500, không hủy hai lần
    again = await admin.post(
        url, json={"reason": REASON, "codes": [paid], "refund_confirmed": True}, headers=idem()
    )
    assert again.status_code in (200, 409, 422) and again.status_code != 500
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payment.cancelled", AuditLog.entity_code.in_([paid, unpaid]))
        )
    assert n == 2


async def test_owner_notification_is_idempotent_when_the_event_is_delivered_twice(
    admin, staff, people, clock
):
    owner = await people("QA Chủ Đơn Phát Lại")
    b, _ = await _room(admin, staff, owner, 15, tomorrow())
    assert (await cancel(admin, b["code"])).status_code == 200
    payload = await _outbox(b["code"])
    for _ in range(2):
        await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    got = [n for n in (await notifications(owner.client))["items"] if "đã bị sân hủy" in n["text"]]
    assert len(got) == 1, got

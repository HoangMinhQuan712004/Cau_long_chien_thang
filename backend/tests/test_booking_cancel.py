"""T-051: Admin hủy booking, vé, đơn (ADR-013): chỗ, tiền, nơi đọc, phòng chơi, thông báo.

Đồng hồ của engine đóng băng ở 00:30 **ngày mai**: mọi khung trong ngày đó còn chưa bắt đầu dù test
chạy lúc mấy giờ, và phòng chơi của ngày đó chưa hết hạn theo giờ thật.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core import events
from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import ADMIN_ONLY, Perm
from app.modules.auth.roles import HIDDEN
from app.modules.booking_engine import api as engine
from app.modules.booking_engine import common, report_occupancy, report_revenue
from app.modules.booking_engine.models import Allocation, Booking, OutboxEvent
from app.modules.booking_engine.tenant import current_tenant_id
from app.modules.play_rooms import api as rooms_api
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomRequest
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, book_order, member, new_court, random_phone, temp
from tests.helpers_web import WEB, checkout, simulate
from tests.qa_tickets import buy, mk_event, tickets_of
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, notifications, post
from tests.test_recurring_list import create, listing

people = base.people

FD = f"{API}/front-desk"
DAY = (datetime.now(settings.tz) + timedelta(days=1)).date()
REASON = "Khách báo bận"


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=settings.tz)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """``clock(h, m)`` đặt giờ engine trong ngày ``DAY``."""
    state = {"now": at(0, 30)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(hour: int, minute: int = 0) -> None:
        state["now"] = at(hour, minute)

    return set_time


def code_of(r) -> str:
    return r.json()["detail"]["code"]


async def new_booking(admin, staff, hour=10, customer=None) -> dict:
    court = await new_court(admin)
    r = await book(
        staff, court["code"], hour, customer=customer or temp("Khách Hủy", random_phone()), day=DAY
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


async def calendar_codes(client) -> list[str]:
    r = await client.get(f"{BK}/calendar", params={"date": DAY.isoformat()})
    assert r.status_code == 200, r.text
    return [b["code"] for b in r.json()["blocks"]]


async def outbox_payload(code: str) -> dict:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "booking.cancelled")
        )
        return next(r.payload for r in rows if r.payload["code"] == code)


async def audit_rows(code: str) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "payment.cancelled", AuditLog.entity_code == code
                )
            )
        )


# ------------------------------------------------------------------ hủy một mục (AC1, AC3, AC9)


async def test_cancel_frees_slot_and_rebooking_gets_a_new_code(admin, staff):
    b = await new_booking(admin, staff)
    code = b["code"]
    court = b["court"]["code"]
    assert code in await calendar_codes(admin)
    assert "cancel" in (await admin.get(f"{BK}/items/{code}")).json()["actions"]

    r = await cancel(admin, code, reason=f"  {REASON} ")
    assert r.status_code == 200, r.text
    item = r.json()
    pay = item["payment"]
    assert pay["payment_status"] == "cancelled" and pay["cancel_reason"] == REASON
    assert pay["cancelled_at"] and pay["cancelled_by_label"] and pay["refund_amount"] == 0
    assert item["actions"] == [] and item["version"] == 2

    assert code not in await calendar_codes(admin)
    async with SessionLocal() as s:
        booking = await s.scalar(select(Booking).where(Booking.code == code))
        alloc = await s.scalar(select(Allocation).where(Allocation.booking_id == booking.id))
    assert alloc.active is False

    again = await book(staff, court, 10, customer=temp("Khách Mới", random_phone()), day=DAY)
    assert again.status_code == 201, again.text
    assert again.json()["code"] != code
    # Khung vừa đặt lại vẫn được exclusion constraint giữ
    third = await book(staff, court, 10, customer=temp("Khách Ba", random_phone()), day=DAY)
    assert third.status_code == 409 and code_of(third) == "E-003"

    rows = await audit_rows(code)
    assert len(rows) == 1 and rows[0].detail["amount"] == b["payment"]["amount"]
    assert rows[0].detail["refund_amount"] == 0
    payload = await outbox_payload(code)
    assert payload["kind"] == "booking" and payload["was_paid"] is False
    assert payload["order_code"] == b["order_code"]
    # Payload được ghi log: không có khách / SĐT
    assert "customer_ref" not in payload and "phone" not in str(payload).lower()


async def test_only_admin_can_cancel(admin, staff):
    b = await new_booking(admin, staff)
    code, order = b["code"], b["order_code"]
    # Nhân viên không thấy nút, kể cả trong phản hồi lúc đặt
    assert b["actions"] == ["collect"]
    assert "cancel" not in (await staff.get(f"{BK}/items/{code}")).json()["actions"]
    assert (await cancel(staff, code)).status_code == 403
    assert (await staff.get(f"{FD}/orders/{order}/cancel-preview")).status_code == 403
    r = await staff.post(
        f"{FD}/orders/{order}/cancel", json={"reason": REASON, "codes": [code]}, headers=idem()
    )
    assert r.status_code == 403
    # Không gán được qua màn Phân quyền
    assert Perm.BOOKING_CANCEL in ADMIN_ONLY and Perm.BOOKING_CANCEL in HIDDEN


async def test_cancel_rules(admin, staff, clock):
    b = await new_booking(admin, staff)
    code = b["code"]
    for reason, message in (("   ", "Vui lòng nhập"), ("x" * 201, "tối đa 200")):
        r = await cancel(admin, code, reason=reason)
        assert r.status_code == 422 and code_of(r) == "E-001", r.text
        assert message in r.json()["detail"]["message"]
    r = await cancel(admin, code, version=9)
    assert r.status_code == 409 and code_of(r) == "E-012"

    # Đã thu: bắt buộc xác nhận hoàn
    assert (await collect(admin, code)).status_code == 200
    r = await cancel(admin, code, version=2)
    assert r.status_code == 422 and code_of(r) == "E-PAY-7"

    # Đúng giờ bắt đầu là đã bắt đầu
    clock(10)
    r = await cancel(admin, code, version=2, refund_confirmed=True)
    assert r.status_code == 422 and code_of(r) == "E-PAY-5"
    assert "cancel" not in (await admin.get(f"{BK}/items/{code}")).json()["actions"]
    clock(9, 59)

    key = idem()
    r = await cancel(admin, code, version=2, refund_confirmed=True, headers=key)
    assert r.status_code == 200, r.text
    pay = r.json()["payment"]
    amount = b["payment"]["amount"]
    assert pay["refund_amount"] == amount and pay["paid_at"] and pay["payment_method"] == "cash"
    # Gửi lại cùng key: không hủy hai lần
    again = await cancel(admin, code, version=2, refund_confirmed=True, headers=key)
    assert again.status_code == 200 and again.json()["version"] == r.json()["version"]
    assert len(await audit_rows(code)) == 1

    # Trạng thái cuối
    r = await cancel(admin, code, version=3, refund_confirmed=True)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"
    r = await collect(admin, code, version=3)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"
    r = await admin.post(
        f"{BK}/items/{code}/uncollectible", json={"reason": "x", "version": 3}, headers=idem()
    )
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"


async def test_uncollectible_cannot_be_cancelled(admin, staff, clock):
    b = await new_booking(admin, staff)
    clock(11)
    r = await admin.post(
        f"{BK}/items/{b['code']}/uncollectible",
        json={"reason": "Khách bỏ về", "version": 1},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    r = await cancel(admin, b["code"], version=2)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"


async def test_cancel_and_collect_race_has_one_winner(admin, staff):
    """AC13: khóa dòng -> chỉ một bên thắng; bên kia thấy trạng thái mới."""
    b = await new_booking(admin, staff)
    code = b["code"]
    results = await asyncio.gather(cancel(admin, code), collect(admin, code))
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == code))
    if results[0].status_code == 200:
        assert row.payment_status == "cancelled" and row.paid_at is None
    else:
        assert row.payment_status == "paid" and row.cancelled_at is None


# ------------------------------------------------------------------ tiền (AC4, AC5)


async def _report(court_id: int):
    tid = current_tenant_id()
    async with SessionLocal() as s:
        ctx = await common.context(s, tid)
        totals = await report_revenue.totals(s, tid, DAY, DAY)
        slots = await report_occupancy._booked_slots(s, ctx, tid, [court_id], [DAY])
    return totals, len(list(slots))


async def test_transactions_and_reports_drop_cancelled(admin, staff):
    paid = await new_booking(admin, staff, hour=8)
    unpaid = await new_booking(admin, staff, hour=9)
    assert (await collect(admin, paid["code"])).status_code == 200
    async with SessionLocal() as s:
        court_id = await s.scalar(select(Booking.resource_id).where(Booking.code == paid["code"]))
    params = {"from": DAY.isoformat(), "to": DAY.isoformat()}
    before = (await admin.get(f"{BK}/transactions", params=params)).json()["cards"]
    totals_before, slots_before = await _report(court_id)

    assert (await cancel(admin, paid["code"], version=2, refund_confirmed=True)).status_code == 200
    assert (await cancel(admin, unpaid["code"])).status_code == 200

    out = (await admin.get(f"{BK}/transactions", params=params)).json()
    cards = out["cards"]
    amount = paid["payment"]["amount"]
    other = unpaid["payment"]["amount"]
    assert cards["paid"]["amount"] == before["paid"]["amount"] - amount
    assert cards["unpaid"]["amount"] == before["unpaid"]["amount"] - other
    assert cards["cancelled"]["amount"] == before["cancelled"]["amount"] + amount + other
    assert cards["cancelled"]["count"] == before["cancelled"]["count"] + 2

    only = await admin.get(f"{BK}/transactions", params={**params, "status": "cancelled"})
    assert only.status_code == 200
    rows = {r["code"]: r for r in only.json()["rows"]}
    assert rows[paid["code"]]["cancel_reason"] == REASON
    assert rows[paid["code"]]["cancelled_by"]
    assert rows[paid["code"]]["refund_amount"] == amount
    assert rows[unpaid["code"]]["refund_amount"] == 0
    # Lọc theo phương thức chỉ lấy khoản còn Đã thanh toán
    by_method = await admin.get(f"{BK}/transactions", params={**params, "method": "cash"})
    assert paid["code"] not in [r["code"] for r in by_method.json()["rows"]]

    totals_after, slots_after = await _report(court_id)
    assert totals_after.revenue == totals_before.revenue - amount
    assert slots_after == slots_before - 1


# ------------------------------------------------------------------ đơn (AC6, AC7)


async def test_order_preview_and_cancel(admin, staff, clock):
    court = await new_court(admin)
    r = await book_order(
        staff,
        [(court["code"], 8, 9), (court["code"], 12, 13), (court["code"], 15, 16)],
        customer=temp("Khách Đơn", random_phone()),
        day=DAY,
    )
    assert r.status_code == 201, r.text
    order = r.json()
    code = order["order_code"]
    early, paid, unpaid = [b["code"] for b in order["bookings"]]
    assert (await collect(admin, paid)).status_code == 200
    clock(9)  # khối đầu đã bắt đầu

    preview = (await admin.get(f"{FD}/orders/{code}/cancel-preview")).json()
    assert [i["code"] for i in preview["cancellable"]] == [paid, unpaid]
    assert preview["skipped"] == [{"code": early, "reason": "started"}]
    amounts = {b["code"]: b["payment"]["amount"] for b in order["bookings"]}
    assert preview["refund_total"] == amounts[paid] and preview["unpaid_total"] == amounts[unpaid]

    async def run(codes, **extra):
        return await admin.post(
            f"{FD}/orders/{code}/cancel",
            json={"reason": REASON, "codes": codes, **extra},
            headers=idem(),
        )

    r = await run([])
    assert r.status_code == 422 and code_of(r) == "E-001"
    r = await run([paid, "BK-KHONG-CO"], refund_confirmed=True)
    assert r.status_code == 422 and code_of(r) == "E-001"
    # Có khối đã thu mà chưa xác nhận: không hủy một phần
    r = await run([paid, unpaid])
    assert r.status_code == 422 and code_of(r) == "E-PAY-7"
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == unpaid))
    assert row.payment_status == "unpaid"

    # Khối đầu gửi kèm vẫn vào skipped; khối đã chơi giữ nguyên
    r = await run([early, paid, unpaid], refund_confirmed=True)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["cancelled"] == [paid, unpaid] and out["refund_total"] == amounts[paid]
    assert out["skipped"] == [{"code": early, "reason": "started"}]
    assert len(await audit_rows(paid)) == 1 and len(await audit_rows(unpaid)) == 1
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == early))
    assert row.payment_status == "unpaid"

    # Trạng thái đơn theo khối còn lại
    listed = (await admin.get(f"{FD}/orders", params={"q": code})).json()["items"][0]
    assert listed["status"] == "unpaid" and listed["blocks"] == 1
    assert listed["total"] == amounts[early]

    r = await admin.get(f"{FD}/orders/KHONG-CO/cancel-preview")
    assert r.status_code == 404 and code_of(r) == "E-BOOK-3"


async def test_recurring_totals_only_count_live_sessions(admin):
    court = await new_court(admin)
    phone = random_phone()
    start = DAY + timedelta(days=1)
    created = await create(admin, court, f"Định kỳ {uuid.uuid4().hex[:6]}", phone, start, (1,), 10)
    code = created["order_code"]

    async def row():
        data = await listing(admin, q=code)
        return data["items"][0], data["counts"]

    before, counts_before = await row()
    async with SessionLocal() as s:
        blocks = list(
            await s.scalars(
                select(Booking).where(Booking.code.like(f"{code}-%")).order_by(Booking.seq)
            )
        )
    first = blocks[0]
    assert first.list_amount is not None

    r = await cancel(admin, first.code)
    assert r.status_code == 200, r.text
    after, _ = await row()
    assert after["sessions"] == before["sessions"] - 1
    assert after["total"] == before["total"] - first.amount
    assert after["original_amount"] == before["original_amount"] - first.list_amount
    assert after["discount_amount"] == before["discount_amount"] - (
        first.list_amount - first.amount
    )
    assert after["status"] == "unpaid"
    # Các buổi khác không đổi
    async with SessionLocal() as s:
        rest = await s.scalar(select(Booking).where(Booking.code == blocks[1].code))
    assert rest.payment_status == "unpaid" and rest.amount == blocks[1].amount

    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={"reason": REASON, "codes": [b.code for b in blocks]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == [{"code": first.code, "reason": "cancelled"}]
    gone, counts = await row()
    assert gone["status"] == "cancelled" and gone["sessions"] == 0 and gone["total"] == 0
    assert gone["resource_code"] == court["code"]  # dòng vẫn đọc được
    assert counts["cancelled"] == counts_before["cancelled"] + 1
    filtered = await listing(admin, q=code, status="cancelled")
    assert [i["order_code"] for i in filtered["items"]] == [code]


# ------------------------------------------------------------------ vé (AC8)


async def _today_session(admin, capacity=1) -> tuple[dict, dict]:
    court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": DAY.isoformat(),
            "start_hour": 14,
            "end_hour": 16,
            "name": f"Sự kiện {uuid.uuid4().hex[:5]}",
            "capacity": capacity,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json(), court


async def _register(staff, code):
    return await staff.post(
        f"{FD}/sessions/{code}/tickets",
        json={"customer": temp("Khách Vé", random_phone())},
        headers=idem(),
    )


async def test_ticket_cancel_frees_seat_keeps_code_sequence(admin, staff, clock):
    clock(13)  # bán vé tại quầy hôm đó
    ev, court = await _today_session(admin)
    code = ev["code"]
    r = await _register(staff, code)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["code"].endswith("-V01") and "cancel" not in first["actions"]
    item = (await admin.get(f"{BK}/items/{first['code']}")).json()
    assert "cancel" in item["actions"]
    full = await _register(staff, code)
    assert full.status_code == 409 and code_of(full) == "E-024"
    # Đang có vé: không xóa được sự kiện
    r = await admin.request(
        "DELETE", f"{BK}/sessions/{code}", json={"version": ev["version"]}, headers=idem()
    )
    assert r.status_code == 409 and code_of(r) == "E-023"

    r = await cancel(admin, first["code"])
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "ticket"
    payload = await outbox_payload(first["code"])
    assert payload["kind"] == "ticket" and payload["order_code"] is None

    view = (await admin.get(f"{BK}/sessions/{code}")).json()
    assert view["taken"] == 0 and view["is_full"] is False
    assert view["tickets"][0]["payment_status"] == "cancelled"  # Admin vẫn thấy

    # Sự kiện vẫn chiếm sân
    r = await book(staff, court["code"], 14, customer=temp("Chen", random_phone()), day=DAY)
    assert r.status_code == 409

    # Vé đã hủy không cản xóa sự kiện
    r = await admin.request(
        "DELETE", f"{BK}/sessions/{code}", json={"version": view["version"]}, headers=idem()
    )
    assert r.status_code == 200, r.text


async def test_rebought_ticket_gets_next_number(admin, staff, clock):
    clock(13)
    ev, _ = await _today_session(admin)
    first = (await _register(staff, ev["code"])).json()
    assert (await cancel(admin, first["code"])).status_code == 200
    r = await _register(staff, ev["code"])
    assert r.status_code == 201, r.text
    assert r.json()["code"].endswith("-V02")  # chỗ trả lại, mã không dùng lại


# ------------------------------------------------------------------ phòng chơi (AC10)


async def _room_of(admin, staff, host) -> tuple[dict, PlayRoom]:
    b = await new_booking(admin, staff, customer=member(host.code))
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, [b["code"]])
        await s.commit()
        room = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == b["code"]))
    assert room is not None
    return b, room


@pytest.mark.parametrize("status", ["playing", "finished"])
async def test_booking_with_played_match_cannot_be_cancelled(admin, staff, people, status):
    host = await people("Chủ Phòng")
    b, room = await _room_of(admin, staff, host)
    await add_match(room.id, 1, [host.customer_id], [-1], status=status, win="a")

    r = await cancel(admin, b["code"])
    assert r.status_code == 422 and code_of(r) == "E-PAY-8", r.text
    assert "đã có trận đấu" in r.json()["detail"]["message"]
    preview = (await admin.get(f"{FD}/orders/{b['order_code']}/cancel-preview")).json()
    assert preview["cancellable"] == []
    assert preview["skipped"] == [{"code": b["code"], "reason": "played"}]
    r = await admin.post(
        f"{FD}/orders/{b['order_code']}/cancel",
        json={"reason": REASON, "codes": [b["code"]]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["cancelled"] == []
    assert r.json()["skipped"] == [{"code": b["code"], "reason": "played"}]
    async with SessionLocal() as s:
        row = await s.scalar(select(Booking).where(Booking.code == b["code"]))
    assert row.payment_status == "unpaid"


async def test_cancel_closes_room_and_notifies(admin, staff, people):
    owner, guest, asker = await people("Chủ Đơn"), await people("Khách"), await people("Xin Vào")
    b, room = await _room_of(admin, staff, owner)
    r = await post(asker.client, f"/{room.id}/join-requests", {"version": room.version})
    assert r.status_code == 200, r.text
    r = await post(
        owner.client, f"/{room.id}/invites", {"phone": guest.phone, "version": r.json()["version"]}
    )
    assert r.status_code == 200, r.text
    # Trận đã bốc không cản hủy
    await add_match(room.id, 1, [owner.customer_id], [guest.customer_id], status="drawn", win="a")
    assert (await owner.client.get(f"{MA}/rooms/{room.id}")).status_code == 200
    async with SessionLocal() as s:
        assert await rooms_api.my_rooms(s, owner.customer_id)

    r = await cancel(admin, b["code"])
    assert r.status_code == 200, r.text

    # Chưa chạy worker: trang phòng đã 404, không còn ở danh sách của tôi
    assert (await owner.client.get(f"{MA}/rooms/{room.id}")).status_code == 404
    async with SessionLocal() as s:
        assert await rooms_api.my_rooms(s, owner.customer_id) == []
        assert await rooms_api.room_id_for_booking(s, owner.customer_id, b["code"]) is None
        # Job bù không tạo lại phòng
        assert await engine.room_sources(s, [b["code"]]) == []

    payload = await outbox_payload(b["code"])
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})

    async with SessionLocal() as s:
        fresh = await s.get(PlayRoom, room.id)
        requests = list(
            await s.scalars(select(PlayRoomRequest).where(PlayRoomRequest.room_id == room.id))
        )
        match = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == room.id))
    assert fresh.status == "closed"
    assert {q.status for q in requests} == {"cancelled"}
    assert match.status == "abandoned"

    def texts(data: dict) -> list[str]:
        return [n["text"] for n in data["items"]]

    closed = "đã bị hủy nên phòng đã đóng"
    mine = texts(await notifications(owner.client))
    assert any(f"({b['order_code']}) đã bị sân hủy." in t for t in mine)
    assert not any(closed in t for t in mine)  # chủ đơn chỉ nhận một câu
    assert not any(REASON in t for t in mine)
    for person in (guest, asker):
        got = [t for t in texts(await notifications(person.client)) if closed in t]
        assert len(got) == 1, got
        assert b["court"]["name"] in got[0]

    # Sự kiện phát lại: không báo hai lần
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    assert len([t for t in texts(await notifications(guest.client)) if closed in t]) == 1


async def test_match_slipped_in_during_cancel_is_abandoned_and_hidden(admin, staff, people):
    """Trận lọt vào lúc đang hủy: ``playing`` -> abandoned; lưới job mỗi phút đóng phòng khi lỡ
    sự kiện; ``finished`` lọt vào cũng không vào Lịch sử chơi."""
    host = await people("Chủ Phòng")
    b, room = await _room_of(admin, staff, host)
    b2, room2 = await _room_of(admin, staff, host)
    assert (await cancel(admin, b["code"])).status_code == 200
    assert (await cancel(admin, b2["code"])).status_code == 200
    await add_match(room.id, 1, [host.customer_id], [-1], status="playing", win="a")
    await add_match(room2.id, 1, [host.customer_id], [-1], status="finished", win="a")

    async with SessionLocal() as s:
        assert await lifecycle._close_any_cancelled(s, datetime.now(UTC)) >= 2
        await s.commit()
    async with SessionLocal() as s:
        match = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == room.id))
        assert match.status == "abandoned"
        assert (await s.get(PlayRoom, room2.id)).status == "closed"
        kept = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == room2.id))
        assert kept.status == "finished"
        month = f"{DAY.year:04d}-{DAY.month:02d}"
        stats = await rooms_api.month_stats(s, host.customer_id, month)
    assert stats.matches == 0 and stats.sessions == 0


# ------------------------------------------------------------------ khách, hội viên (AC11, AC12)


async def test_member_views(admin, staff, people):
    hv = await people("Hội Viên Hủy")
    paid = await new_booking(admin, staff, hour=8, customer=member(hv.code))
    unpaid = await new_booking(admin, staff, hour=9, customer=member(hv.code))
    live = await new_booking(admin, staff, hour=11, customer=member(hv.code))
    assert (await collect(admin, paid["code"])).status_code == 200
    assert (await collect(admin, live["code"])).status_code == 200
    assert (await cancel(admin, paid["code"], version=2, refund_confirmed=True)).status_code == 200
    assert (await cancel(admin, unpaid["code"])).status_code == 200
    for b in (paid, unpaid):
        await events.publish(events.BOOKING_CANCELLED, await outbox_payload(b["code"]))

    # Thông báo: mã đơn, số hoàn khi đã thu, không lý do
    got = [n["text"] for n in (await notifications(hv.client))["items"]]
    amount = f"{paid['payment']['amount']:,}".replace(",", ".")
    assert any(
        f"({paid['order_code']}) đã bị sân hủy. Sân ghi nhận hoàn {amount} đ." in t for t in got
    )
    assert any(f"({unpaid['order_code']}) đã bị sân hủy." in t for t in got)
    assert not any(REASON in t for t in got)

    # Lịch sử thanh toán: đã thu rồi hủy vẫn hiện, không cộng vào tổng; chưa thu thì không hiện
    now = datetime.now(settings.tz)
    r = await hv.client.get(f"{MA}/payments", params={"month": f"{now.year}-{now.month:02d}"})
    assert r.status_code == 200, r.text
    data = r.json()
    by_code = {i["code"]: i for i in data["items"]}
    assert by_code[paid["code"]]["cancelled"] is True
    assert by_code[paid["code"]]["refund_amount"] == paid["payment"]["amount"]
    assert unpaid["code"] not in by_code
    assert by_code[live["code"]]["cancelled"] is False
    assert data["summary"]["total"] == live["payment"]["amount"]
    assert data["summary"]["count"] == 1
    detail = await hv.client.get(f"{MA}/payments/{paid['code']}")
    assert detail.status_code == 200 and detail.json()["cancelled"] is True
    assert REASON not in detail.text

    # Buổi sắp tới, thống kê: loại buổi đã hủy
    refs = [str(hv.customer_id), f"phone:{hv.phone}"]
    async with SessionLocal() as s:
        codes = [u.code for u in await engine.upcoming_bookings(s, refs, datetime.now(UTC))]
        stats = await engine.customer_stats(s, refs)
        recent = await engine.customer_bookings(s, refs, 10)
    assert codes == [live["code"]]
    assert sum(v.bookings for v in stats.values()) == 1
    assert sum(v.listed for v in stats.values()) == 3
    assert {r.code: r.payment_status for r in recent}[paid["code"]] == "cancelled"

    # Lịch hội viên: ô đã hủy không còn là "của tôi"
    r = await hv.client.get(f"{API}/web/booking/calendar", params={"date": DAY.isoformat()})
    assert r.status_code == 200, r.text
    court = next(c for c in r.json()["resources"] if c["code"] == paid["court"]["code"])
    assert next(x for x in court["slots"] if x["start_hour"] == 8)["state"] == "free"


async def test_temp_customer_gets_no_notification_and_lookup_hides_reason(admin, staff, anon):
    phone = random_phone()
    b = await new_booking(admin, staff, customer=temp("Khách Tạm", phone))
    assert (await cancel(admin, b["code"])).status_code == 200
    await events.publish(events.BOOKING_CANCELLED, await outbox_payload(b["code"]))

    r = await anon.post(f"{WEB}/lookup", json={"code": b["order_code"], "phone": phone})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "cancelled" and d["amount"] == 0 and d["hours"] == 0
    assert d["items"][0]["status"] == "cancelled"
    assert d["items"][0]["amount"] == b["payment"]["amount"]
    assert REASON not in r.text and "cancel_reason" not in r.text


async def test_late_money_after_cancel_needs_refund(anon, admin):
    court = await new_court(admin)
    phone = random_phone()
    r = await checkout(anon, [(court["code"], 19)], day=DAY, phone=phone)
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    async with SessionLocal() as s:
        booking = await s.scalar(select(Booking).where(Booking.code.like(f"{co['order_code']}-%")))
    code = booking.code
    assert booking.payment_status == "paid"

    r = await cancel(admin, code)
    assert r.status_code == 422 and code_of(r) == "E-PAY-7"
    r = await cancel(admin, code, refund_confirmed=True)
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["payment_method"] == "online_transfer"
    assert r.json()["payment"]["refund_amount"] == booking.amount

    # Tiền về trễ: không tạo booking, không chiếm chỗ, vào đường cần hoàn
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "refund_needed"
    async with SessionLocal() as s:
        same = list(
            await s.scalars(select(Booking).where(Booking.code.like(f"{co['order_code']}-%")))
        )
        active = await s.scalar(
            select(Allocation).where(Allocation.booking_id == booking.id, Allocation.active)
        )
    assert len(same) == 1 and same[0].payment_status == "cancelled" and active is None

    # Trang thanh toán: lượt vẫn paid, khối ghi Đã hủy
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "paid" and view["items"][0]["cancelled"] is True
    # Tra cứu: Đã hủy
    r = await anon.post(f"{WEB}/lookup", json={"code": co["order_code"], "phone": phone})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # Khung đặt lại được
    r = await checkout(anon, [(court["code"], 19)], day=DAY)
    assert r.status_code == 201, r.text


async def test_checks_on_cancelled_columns(admin, staff):
    """DB chặn dữ liệu mâu thuẫn dù code có sai."""
    b = await new_booking(admin, staff)
    for values in (
        {"payment_status": "cancelled"},  # thiếu lý do
        {"refund_amount": b["payment"]["amount"] + 1},
        {"refund_amount": -1},
    ):
        with pytest.raises(Exception, match="ck_booking"):
            async with SessionLocal() as s:
                await s.execute(update(Booking).where(Booking.code == b["code"]).values(**values))
                await s.commit()


async def test_online_ticket_partial_cancel(anon, admin):
    ev = await mk_event(admin, day=DAY, hours=(9, 11), capacity=2)
    phone = random_phone()
    r = await buy(anon, ev["code"], seats=2, phone=phone)
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    first, second = [t["code"] for t in await tickets_of(ev["code"])]
    assert (await cancel(admin, first, refund_confirmed=True)).status_code == 200

    # Chỗ trả lại; trang thanh toán và tra cứu thấy đúng vé đã hủy
    view = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert view["taken"] == 1
    page = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert page["status"] == "paid" and page["event"]["ticket_codes"] == [first, second]
    assert page["event"]["cancelled_ticket_codes"] == [first]
    r = await anon.post(f"{WEB}/lookup", json={"code": co["order_code"], "phone": phone})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "paid" and d["amount"] == ev["ticket_price"]
    assert {t["code"]: t["pay_status"] for t in d["event"]["tickets"]} == {
        first: "cancelled",
        second: "paid",
    }

    assert (await cancel(admin, second, refund_confirmed=True)).status_code == 200
    r = await anon.post(f"{WEB}/lookup", json={"code": second, "phone": phone})
    assert r.json()["status"] == "cancelled" and r.json()["amount"] == 0

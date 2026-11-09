# ruff: noqa: E501
"""QA T-052 (API, AC1–AC11): Admin hủy buổi đang chơi / đã qua (đổi T-051). Góc nhìn độc lập với ``test_booking_cancel.py``.

Đóng băng đồng hồ engine trong ngày mai, đặt giờ đến sát hai phía của mốc bắt đầu và mốc ``end_at`` (giây).
Dùng lại helper của ``test_qa_T-051.py`` (tên có dấu gạch nên nạp bằng importlib).
"""

import asyncio
import importlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core import events
from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine import common, report_occupancy, report_revenue
from app.modules.booking_engine.tenant import current_tenant_id
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, book_order, member, new_court, random_phone, temp
from tests.helpers_web import checkout, simulate, tomorrow
from tests.qa_tickets import buy, mk_event, tickets_of
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, notifications, post

t51 = importlib.import_module("tests.test_qa_T-051")
cancel, collect, row_of, active_allocations = (
    t51.cancel,
    t51.collect,
    t51.row_of,
    t51.active_allocations,
)
new_booking, _room, _outbox, code_of, REASON = (
    t51.new_booking,
    t51._room,
    t51._outbox,
    t51.code_of,
    t51.REASON,
)

people = base.people
FD = f"{API}/front-desk"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DAY = tomorrow()


def at(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, h, m, s, tzinfo=TZ)


@pytest.fixture
def clock(monkeypatch):
    """``clock(h, m, s)`` đặt giờ engine trong ngày mai (mặc định 00:30)."""
    state = {"now": at(0, 30)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(h: int, m: int = 0, s: int = 0) -> None:
        state["now"] = at(h, m, s)

    return set_time


async def totals(day=DAY, court_id: int | None = None) -> tuple[int, int]:
    """(doanh thu, số khung đã đặt của sân) theo ngày chơi; không truyền sân thì số khung = 0."""
    tid = current_tenant_id()
    async with SessionLocal() as s:
        ctx = await common.context(s, tid)
        rev = await report_revenue.totals(s, tid, day, day)
        slots = (
            len(list(await report_occupancy._booked_slots(s, ctx, tid, [court_id], [day])))
            if court_id is not None
            else 0
        )
    return rev.revenue, slots


async def item(client, code):
    r = await client.get(f"{BK}/items/{code}")
    assert r.status_code == 200, r.text
    return r.json()


async def audits(code: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "payment.cancelled", AuditLog.entity_code == code)
        )


# ---------------------------------------------------------------- AC1/AC6: nút Hủy + cancel_phase, sát hai mốc


async def test_ac1_ac6_phase_and_actions_at_both_sides_of_start_and_end(admin, staff, clock):
    court = await new_court(admin)
    paid = await new_booking(staff, admin, hour=10, day=DAY, court=court)
    unpaid = await new_booking(staff, admin, hour=10, day=DAY, court=await new_court(admin))
    assert (await collect(admin, paid["code"])).status_code == 200

    async def view(code, client=admin):
        i = await item(client, code)
        return i["cancel_phase"], "cancel" in i["actions"]

    # (giờ, pha khoản đã thu, khoản chưa thu có hủy được không)
    steps = [
        ((9, 59, 59), "before", True),
        ((10, 0, 0), "playing", False),  # đúng giờ bắt đầu: đã bắt đầu
        ((10, 59, 59), "playing", False),
        ((11, 0, 0), "past", False),  # đúng end_at: đã qua
        ((11, 0, 1), "past", False),
        ((23, 59, 59), "past", False),  # không giới hạn thời gian
    ]
    for t, phase, unpaid_ok in steps:
        clock(*t)
        assert await view(paid["code"]) == (phase, True), t
        assert await view(unpaid["code"]) == (("before", True) if unpaid_ok else (None, False)), t
        assert await view(paid["code"], staff) == (None, False), "Nhân viên không thấy"
        assert (
            await cancel(staff, paid["code"], version=2, refund_confirmed=True)
        ).status_code == 403

    # Chưa thu mà đã tới giờ -> E-PAY-5 (thông điệp mới); đã hủy / không thu được -> E-PAY-6
    r = await cancel(admin, unpaid["code"])
    assert r.status_code == 422 and code_of(r) == "E-PAY-5", r.text
    assert "Không thu được" in r.json()["detail"]["message"]
    assert (await row_of(unpaid["code"])).payment_status == "unpaid"
    u = await admin.post(
        f"{BK}/items/{unpaid['code']}/uncollectible",
        json={"reason": "Khách bỏ về", "version": 1},
        headers=idem(),
    )
    assert u.status_code == 200 and u.json()["cancel_phase"] is None
    r = await cancel(admin, unpaid["code"], version=2)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"

    # Khoản đã thu ở mọi pha hủy được (đã qua cuối ngày)
    r = await cancel(admin, paid["code"], version=2)
    assert r.status_code == 422 and code_of(r) == "E-PAY-7", "vẫn bắt buộc xác nhận hoàn"
    r = await cancel(admin, paid["code"], version=2, refund_confirmed=True)
    assert r.status_code == 200 and r.json()["cancel_phase"] is None
    r = await cancel(admin, paid["code"], version=3, refund_confirmed=True)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"


# ---------------------------------------------------------------- AC3: doanh thu đúng ngày chơi


async def test_ac3_past_cancel_deducts_only_the_play_day_and_capacity(admin, staff, anon, clock):
    court = await new_court(admin)
    other_court = await new_court(admin)
    past = await new_booking(staff, admin, hour=8, day=DAY, court=court)
    assert (await collect(admin, past["code"])).status_code == 200
    amount = past["payment"]["amount"]
    # Một khoản đã thu ở NGÀY KHÁC (đặt online ngày kia) – không được đổi
    next_day = DAY + timedelta(days=1)
    co = await checkout(anon, [(other_court["code"], 20)], day=next_day, phone=random_phone())
    assert co.status_code == 201, co.text
    assert await simulate(admin, co.json()["pay_ref"], co.json()["amount"]) == "applied"

    court_id = (await row_of(past["code"])).resource_id
    rev_b, slots_b = await totals(DAY, court_id)
    other_b, _ = await totals(next_day)
    params = {"from": DAY.isoformat(), "to": DAY.isoformat()}
    cards_b = (await admin.get(f"{BK}/transactions", params=params)).json()["cards"]

    clock(13)  # buổi 8–9h đã qua từ lâu
    assert (await item(admin, past["code"]))["cancel_phase"] == "past"
    r = await cancel(admin, past["code"], version=2, refund_confirmed=True)
    assert r.status_code == 200, r.text
    assert r.json()["payment"]["refund_amount"] == amount

    rev_a, slots_a = await totals(DAY, court_id)
    other_a, _ = await totals(next_day)
    assert rev_a == rev_b - amount, "trừ đúng ngày chơi"
    assert other_a == other_b, "ngày khác không đổi"
    assert slots_b == 1 and slots_a == 0, "công suất ngày đó giảm"
    cards_a = (await admin.get(f"{BK}/transactions", params=params)).json()["cards"]
    assert cards_a["paid"]["amount"] == cards_b["paid"]["amount"] - amount
    assert cards_a["cancelled"]["amount"] == cards_b["cancelled"]["amount"] + amount
    assert cards_a["cancelled"]["count"] == cards_b["cancelled"]["count"] + 1
    # Lọc theo mã: bảng 8 dòng / trang, các test khác cũng hủy buổi cùng ngày trên CSDL dùng chung
    filtered = {**params, "status": "cancelled", "q": past["code"]}
    rows = (await admin.get(f"{BK}/transactions", params=filtered)).json()["rows"]
    row = next(x for x in rows if x["code"] == past["code"])
    assert row["cancel_reason"] == REASON and row["refund_amount"] == amount and row["cancelled_by"]
    assert await audits(past["code"]) == 1
    # Khung đã qua không hiện trên lịch và không ảnh hưởng ai đặt được
    cal = (await admin.get(f"{BK}/calendar", params={"date": DAY.isoformat()})).json()
    assert past["code"] not in [b["code"] for b in cal["blocks"]]


# ---------------------------------------------------------------- AC4: đang chơi -> sân trống luôn


async def test_ac4_playing_cancel_frees_court_next_hours_and_same_hour_follows_booking_rule(
    admin, staff, clock
):
    court = await new_court(admin)
    b = await new_booking(staff, admin, hour=10, day=DAY, court=court)
    assert (await collect(admin, b["code"])).status_code == 200
    clock(10, 30)
    assert (await item(admin, b["code"]))["cancel_phase"] == "playing"
    r = await cancel(admin, b["code"], version=2, refund_confirmed=True)
    assert r.status_code == 200, r.text
    assert await active_allocations(b["code"]) == 0
    cal = (await admin.get(f"{BK}/calendar", params={"date": DAY.isoformat()})).json()
    assert b["code"] not in [x["code"] for x in cal["blocks"]]
    # Giờ kế tiếp đặt được ngay
    for h in (11, 12):
        nxt = await book(staff, court["code"], h, customer=temp("QA Sau", random_phone()), day=DAY)
        assert nxt.status_code == 201, (h, nxt.text)
    # Khung đang dở: theo đúng quy tắc đặt sân hiện có (so với một sân chưa từng có booking)
    control = await book(
        staff,
        (await new_court(admin))["code"],
        10,
        customer=temp("QA Đối Chứng", random_phone()),
        day=DAY,
    )
    again = await book(
        staff, court["code"], 10, customer=temp("QA Cùng Giờ", random_phone()), day=DAY
    )
    assert again.status_code == control.status_code, (again.text, control.text)
    if again.status_code == 201:
        assert again.json()["code"] != b["code"]
    # Trạng thái cuối
    r = await cancel(admin, b["code"], version=3, refund_confirmed=True)
    assert r.status_code == 409 and code_of(r) == "E-PAY-6"


# ---------------------------------------------------------------- AC4/AC5/AC7: phòng, trận, lịch sử chơi


async def test_ac4_ac5_ac7_history_numbers_unchanged_in_every_phase_and_rooms_readable(
    admin, staff, people, clock
):
    host, mate, guest = (
        await people("QA Chủ Lịch Sử"),
        await people("QA Đồng Đội"),
        await people("QA Xin Vào"),
    )
    plan = {"before": 12, "playing": 10, "past": 8}
    rooms = {}
    for phase, hour in plan.items():
        b, room = await _room(admin, staff, host, hour, DAY)
        assert (await collect(admin, b["code"])).status_code == 200
        await add_match(
            room.id, 1, [host.customer_id], [mate.customer_id], status="finished", win="a"
        )
        if phase != "past":
            await add_match(
                room.id, 2, [host.customer_id], [mate.customer_id], status="drawn", win="a"
            )
        rooms[phase] = (b, room)
    # người xin vào phòng "playing" để kiểm thông báo một lần
    asked = await post(
        guest.client,
        f"/{rooms['playing'][1].id}/join-requests",
        {"version": rooms["playing"][1].version},
    )
    assert asked.status_code == 200, asked.text

    month = DAY.strftime("%Y-%m")
    rank_params = {"period": "month", "date": DAY.isoformat()}

    async def snapshot():
        h = await host.client.get(f"{MA}/play-history", params={"month": month})
        m = await mate.client.get(f"{MA}/play-history", params={"month": month})
        rk = await host.client.get(f"{MA}/speed-ranking", params=rank_params)
        return h.json(), m.json(), rk.json()

    before = await snapshot()
    assert before[0]["summary"]["matches"] == 3 and before[0]["summary"]["sessions"] == 3

    times = {"before": (0, 30), "playing": (10, 30), "past": (13, 0)}
    for phase in ("before", "playing", "past"):
        b, room = rooms[phase]
        clock(*times[phase])
        r = await cancel(admin, b["code"], version=2, refund_confirmed=True)
        assert r.status_code == 200, (phase, r.text)
        payload = await _outbox(b["code"])
        assert payload["past"] == (phase == "past")
        for _ in range(2):  # sự kiện giao lại: không báo trùng
            await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})

    after = await snapshot()
    assert after[0]["summary"] == before[0]["summary"], "số trận / thắng / thua không đổi"
    assert after[1]["summary"] == before[1]["summary"]
    assert {i["room_id"] for i in after[0]["items"]} == {r.id for _, r in rooms.values()}
    assert after[2] == before[2], "bảng xếp hạng tốc độ không đổi"

    async with SessionLocal() as s:
        statuses = {
            phase: {
                m.no: m.status
                for m in await s.scalars(select(PlayMatch).where(PlayMatch.room_id == room.id))
            }
            for phase, (_, room) in rooms.items()
        }
        room_status = {
            phase: (await s.get(PlayRoom, room.id)).status for phase, (_, room) in rooms.items()
        }
    assert statuses["before"] == {1: "finished", 2: "abandoned"}
    assert statuses["playing"] == {1: "finished", 2: "abandoned"}
    assert statuses["past"] == {1: "finished"}
    assert room_status["before"] == "closed" and room_status["playing"] == "closed"
    assert room_status["past"] != "closed", "buổi đã qua: phòng không bị đóng vì hủy"

    # Popup chi tiết (T-050) mở được: cả người trong phòng lẫn đồng đội; phòng không còn ở Danh sách sân
    listed = [
        x["id"]
        for x in (await host.client.get(f"{MA}/rooms", params={"scope": "all"})).json()["items"]
    ]
    for phase, (_, room) in rooms.items():
        assert room.id not in listed, phase
        for who in (host, mate):
            m = await who.client.get(f"{MA}/rooms/{room.id}/matches")
            r = await who.client.get(f"{MA}/rooms/{room.id}/ranking")
            assert m.status_code == 200 and r.status_code == 200, (phase, m.text)
            assert m.json()["total"] == 1
    # Thông báo: người xin vào phòng "playing" nhận đúng 1; phòng đã qua không báo ai
    closed = "đã bị hủy nên phòng đã đóng"
    assert sum(closed in n["text"] for n in (await notifications(guest.client))["items"]) == 1
    # Phòng đã hủy ở pha before/playing là chỉ đọc: ghi -> 409 E-ROOM-1
    for phase in ("before", "playing"):
        room = rooms[phase][1]
        cur = (await host.client.get(f"{MA}/rooms/{room.id}")).json()
        w = await post(host.client, f"/{room.id}/leave", {"version": cur["version"]})
        assert w.status_code == 409 and code_of(w) == "E-ROOM-1", (phase, w.text)


# ---------------------------------------------------------------- AC8: Hủy đơn không đổi


async def test_ac8_order_cancel_preview_keeps_started_and_played_blocks(
    admin, staff, people, clock
):
    host = await people("QA Chủ Đơn Nhiều Khối")
    court = await new_court(admin)
    r = await book_order(
        staff,
        [(court["code"], 8, 9), (court["code"], 12, 13), (court["code"], 15, 16)],
        customer=member(host.code),
        day=DAY,
    )
    assert r.status_code == 201, r.text
    order = r.json()
    started, played, later = [b["code"] for b in order["bookings"]]
    async with SessionLocal() as s:
        from app.modules.play_rooms import lifecycle

        await lifecycle.ensure_for_codes(s, [played])
        await s.commit()
        room = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == played))
    await add_match(room.id, 1, [host.customer_id], [-1], status="finished", win="a")
    for code in (started, played, later):
        assert (await collect(admin, code)).status_code == 200
    clock(9)  # khối 8–9h đã qua (đúng end_at)
    pre = (await admin.get(f"{FD}/orders/{order['order_code']}/cancel-preview")).json()
    assert [i["code"] for i in pre["cancellable"]] == [later]
    assert {s_["code"]: s_["reason"] for s_ in pre["skipped"]} == {
        started: "started",
        played: "played",
    }
    run = await admin.post(
        f"{FD}/orders/{order['order_code']}/cancel",
        json={"reason": REASON, "codes": [later], "refund_confirmed": True},
        headers=idem(),
    )
    assert run.status_code == 200, run.text
    assert (await row_of(started)).payment_status == "paid", "buổi đã bắt đầu giữ nguyên"
    assert (await row_of(later)).payment_status == "cancelled"
    # Cố ý đưa mã buổi đã bắt đầu vào lệnh hủy đơn -> không hủy, vào skipped hoặc bị từ chối
    run = await admin.post(
        f"{FD}/orders/{order['order_code']}/cancel",
        json={"reason": REASON, "codes": [started], "refund_confirmed": True},
        headers=idem(),
    )
    assert run.status_code == 200, run.text
    assert run.json()["cancelled"] == [], run.text
    assert {s_["code"]: s_["reason"] for s_ in run.json()["skipped"]} == {started: "started"}
    assert (await row_of(started)).payment_status == "paid"
    # Từng buổi đã bắt đầu thì hủy trong popup
    one = await cancel(admin, started, version=2, refund_confirmed=True)
    assert one.status_code == 200, one.text


# ---------------------------------------------------------------- AC9: hội viên


async def test_ac9_member_payment_history_and_single_notification_for_a_playing_cancel(
    admin, staff, people, clock
):
    hv = await people("QA Hội Viên Đang Chơi")
    b = await new_booking(staff, admin, hour=10, day=DAY, customer=member(hv.code))
    assert (await collect(admin, b["code"])).status_code == 200
    clock(10, 20)
    assert (await cancel(admin, b["code"], version=2, refund_confirmed=True)).status_code == 200
    payload = await _outbox(b["code"])
    for _ in range(2):
        await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    refund = f"{b['payment']['amount']:,}".replace(",", ".")
    mine = [
        n["text"] for n in (await notifications(hv.client))["items"] if "đã bị sân hủy" in n["text"]
    ]
    assert len(mine) == 1 and f"hoàn {refund} đ" in mine[0] and REASON not in mine[0], mine
    r = await hv.client.get(f"{MA}/payments", params={"month": f"{DAY.year}-{DAY.month:02d}"})
    assert r.status_code == 200, r.text
    data = r.json()
    row = {i["code"]: i for i in data["items"]}.get(b["code"])
    assert row and row["cancelled"] is True and row["refund_amount"] == b["payment"]["amount"]
    assert data["summary"]["total"] == 0 and data["summary"]["count"] == 0, (
        "không cộng vào tổng đã trả"
    )
    assert REASON not in r.text


# ---------------------------------------------------------------- AC10: vé


async def test_ac10_paid_online_ticket_cancels_when_playing_and_past_event_keeps_court(
    admin, staff, anon, clock
):
    ev = await mk_event(admin, day=DAY, hours=(9, 11), capacity=2)
    co = await buy(anon, ev["code"], seats=2, phone=random_phone())
    assert co.status_code == 201, co.text
    assert await simulate(admin, co.json()["pay_ref"], co.json()["amount"]) == "applied"
    first, second = [t["code"] for t in await tickets_of(ev["code"])]
    rev_b, _ = await totals(DAY)
    price = ev["ticket_price"]

    clock(10)  # sự kiện đang diễn ra
    assert (await item(admin, first))["cancel_phase"] == "playing"
    assert (await cancel(admin, first, refund_confirmed=True)).status_code == 200
    clock(11)  # đúng end_at: đã qua
    assert (await item(admin, second))["cancel_phase"] == "past"
    assert (await cancel(staff, second, refund_confirmed=True)).status_code == 403
    assert (await cancel(admin, second, refund_confirmed=True)).status_code == 200
    rev_a, _ = await totals(DAY)
    assert rev_a == rev_b - 2 * price, "trừ đúng ngày chơi của sự kiện"
    view = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert view["taken"] == 0 and {t["payment_status"] for t in view["tickets"]} == {"cancelled"}
    assert await audits(first) == 1 and await audits(second) == 1


# ---------------------------------------------------------------- AC11: đồng thời


async def test_ac11_parallel_cancels_of_a_past_paid_booking_deduct_once(admin, staff, clock):
    court = await new_court(admin)
    b = await new_booking(staff, admin, hour=8, day=DAY, court=court)
    assert (await collect(admin, b["code"])).status_code == 200
    clock(13)
    rev_b, _ = await totals(DAY)
    res = await asyncio.gather(
        *[cancel(admin, b["code"], version=2, refund_confirmed=True) for _ in range(5)]
    )
    assert sorted(r.status_code for r in res).count(200) == 1, [r.text for r in res]
    assert all(r.status_code in (200, 409) for r in res)
    rev_a, _ = await totals(DAY)
    assert rev_a == rev_b - b["payment"]["amount"], "chỉ trừ một lần"
    assert await audits(b["code"]) == 1


async def test_ac11_cancel_vs_uncollectible_on_started_unpaid_never_cancels(admin, staff, clock):
    b = await new_booking(staff, admin, hour=10, day=DAY)
    clock(10, 30)
    res = await asyncio.gather(
        cancel(admin, b["code"]),
        admin.post(
            f"{BK}/items/{b['code']}/uncollectible",
            json={"reason": "Bỏ về", "version": 1},
            headers=idem(),
        ),
    )
    cancelled, unc = res
    assert cancelled.status_code in (409, 422) and code_of(cancelled) in (
        "E-PAY-5",
        "E-PAY-6",
        "E-012",
    )
    assert unc.status_code == 200
    row = await row_of(b["code"])
    assert row.payment_status == "uncollectible" and row.cancelled_at is None


async def test_ac11_cancel_vs_save_result_on_a_playing_room_stays_consistent(
    admin, staff, people, clock
):
    host = await people("QA Chủ Lưu Kết Quả")
    b, room = await _room(admin, staff, host, 10, DAY)
    assert (await collect(admin, b["code"])).status_code == 200
    await add_match(room.id, 1, [host.customer_id], [-1], status="playing", win="a")
    clock(10, 30)
    version = (await host.client.get(f"{MA}/rooms/{room.id}")).json()["version"]
    cancelled, saved = await asyncio.gather(
        cancel(admin, b["code"], version=2, refund_confirmed=True),
        post(
            host.client,
            f"/{room.id}/matches/1/result",
            {"score_a": 21, "score_b": 9, "version": version},
        ),
    )
    assert cancelled.status_code == 200, cancelled.text
    assert saved.status_code in (200, 409), saved.text
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **await _outbox(b["code"])})
    async with SessionLocal() as s:
        match = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == room.id))
    assert match.status == ("finished" if saved.status_code == 200 else "abandoned")
    hist = (
        await host.client.get(f"{MA}/play-history", params={"month": DAY.strftime("%Y-%m")})
    ).json()
    got = [i for i in hist["items"] if i["room_id"] == room.id]
    assert (len(got) == 1) == (match.status == "finished"), (
        "trận đã lưu xong thì còn ở Lịch sử chơi"
    )
    # không thể hủy xong rồi vẫn thu thêm
    assert (await collect(admin, b["code"], version=3)).status_code in (409, 422)


# ---------------------------------------------------------------- phòng: ghi được hay không, hai phía của end_at


@pytest.mark.parametrize(
    ("when", "writable"),
    [((10, 59, 59), False), ((11, 0, 0), True), ((11, 0, 1), True), ((10, 0, 0), False)],
)
async def test_room_writes_after_cancel_depend_on_which_side_of_end_at(
    admin, staff, people, clock, when, writable
):
    """Hủy trước end_at: phòng đóng, ghi -> 409 E-ROOM-1. Hủy từ end_at: phòng còn mở và ghi được
    (tới khi hết hạn); không có trận đã xong thì 404 khi đóng. Buổi 10–11h."""
    host, guest = await people("QA Chủ Mốc"), await people("QA Khách Mốc")
    b, room = await _room(admin, staff, host, 10, DAY)
    assert (await collect(admin, b["code"])).status_code == 200
    clock(*when)
    r = await cancel(admin, b["code"], version=2, refund_confirmed=True)
    assert r.status_code == 200, r.text
    payload = await _outbox(b["code"])
    assert payload["past"] == writable
    await events.publish(events.BOOKING_CANCELLED, {"tenant_id": 1, **payload})
    async with SessionLocal() as s:
        from app.modules.play_rooms import lifecycle

        await lifecycle._close_any_cancelled(s, at(*when))  # job lưới an toàn
        await s.commit()
        status = (await s.get(PlayRoom, room.id)).status
    ask = await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    if writable:
        assert status == "open", "hủy từ end_at: sự kiện và job đều không đóng phòng"
        # Người trong phòng còn ghi được, nhưng không nhận thêm người (T-054: booking đã hủy = kết thúc)
        assert ask.status_code == 409 and code_of(ask) == "E-ROOM-1", ask.text
        fmt = await host.client.put(
            f"{MA}/rooms/{room.id}/format",
            json={"format": "1v1", "version": room.version},
            headers=idem(),
        )
        assert fmt.status_code == 200, fmt.text
    else:
        assert status == "closed"
        assert ask.status_code in (404, 409), ask.text
        if ask.status_code == 409:
            assert code_of(ask) == "E-ROOM-1"
    closed = "đã bị hủy nên phòng đã đóng"
    got = [n for n in (await notifications(host.client))["items"] if closed in n["text"]]
    assert not got, "chủ đơn chỉ nhận câu 'đã bị sân hủy', không nhận thêm câu đóng phòng"
    mine = [
        n["text"]
        for n in (await notifications(host.client))["items"]
        if "đã bị sân hủy" in n["text"]
    ]
    assert len(mine) == 1

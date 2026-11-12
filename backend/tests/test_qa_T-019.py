# ruff: noqa: E501
"""QA T-019 (mã chung cho một lượt đặt, ADR-010): AC1-AC8 viết từ spec `T-019-ma-chung-luot-dat.md`.

Tái dùng helper của test_qa_T-006 / test_qa_T-008 (cùng seed, cùng sân tạo riêng cho từng test).
"""

import asyncio
import importlib
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime

from app.core.config import settings
from app.modules.booking_engine import common
from tests.conftest import API, idem, vn_today

t6 = importlib.import_module("tests.test_qa_T-006")
t8 = importlib.import_module("tests.test_qa_T-008")
sepay = t8.sepay  # fixture: cấu hình SePay thử

FD = f"{API}/front-desk"
BK = f"{API}/booking"
ORDER = re.compile(r"BK-\d{8}-\d{3}")
CHILD = re.compile(r"BK-\d{8}-\d{3}-\d{2}")


def counter_day() -> date:
    """Đặt quầy chỉ cho ngày hôm nay (E-AUTH-2 nếu ngày khác)."""
    return vn_today()


_MORNING = {"depth": 0, "real": None}


@asynccontextmanager
async def morning(hour: int = 6):
    """Trong khối này engine coi như đang là ``hour`` (mặc định 06:00) hôm nay: 06:00 → khung 8h–13h ở tương lai (T-067).

    Trước đây ``h()`` bỏ qua 21 test sau ~18h vì "không đủ giờ trong ngày". Chỉ áp cho lúc ĐẶT (request tạo
    đơn quầy); đếm lồng nhau để các request song song (``asyncio.gather``) không dẫm lên nhau."""
    if _MORNING["depth"] == 0:
        _MORNING["real"] = common.datetime
        day = vn_today()
        frozen_now = datetime(day.year, day.month, day.day, hour, tzinfo=settings.tz)

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen_now.astimezone(tz)

        common.datetime = Frozen
    _MORNING["depth"] += 1
    try:
        yield
    finally:
        _MORNING["depth"] -= 1
        if _MORNING["depth"] == 0:
            common.datetime = _MORNING["real"]


def h(n: int) -> int:
    """Giờ trong ngày cho khối đặt quầy (8h–13h): luôn là tương lai vì ``counter()`` đặt trong ``morning()``."""
    return 8 + n


def block(code: str, start: int, end: int) -> dict:
    return {"resource_code": code, "start_hour": start, "end_hour": end}


async def counter(client, blocks, *, customer=None, d: date | None = None, extra=None):
    body = {
        "date": (d or counter_day()).isoformat(),
        "blocks": blocks,
        "customer": customer or {"temp": {"full_name": "QA Đơn Quầy", "phone": t8.phone()}},
        **(extra or {}),
    }
    async with morning():
        return await client.post(f"{FD}/bookings", json=body, headers=idem())


async def counter_ok(client, blocks, **kw) -> dict:
    r = await counter(client, blocks, **kw)
    assert r.status_code == 201, r.text
    return r.json()


async def courts(admin, n: int) -> list[str]:
    return [(await t8.court(admin))["code"] for _ in range(n)]


async def db(query: str, **params):
    return await t8.sql(query, **params)


def err(r, status: int, code: str) -> None:
    assert r.status_code == status and t8.code_of(r) == code, (status, code, r.status_code, r.text)


# ============================================================ AC1 cấp mã


async def test_ac1_counter_one_order_children_numbered_by_court_then_start(admin):
    a, b = await courts(admin, 2)
    blocks = [
        block(b, h(3), h(4)),
        block(a, h(3), h(4)),
        block(a, h(0), h(1)),
        block(b, h(0), h(1)),
    ]
    order = await counter_ok(admin, blocks)
    assert ORDER.fullmatch(order["order_code"]), order["order_code"]
    codes = [x["code"] for x in order["bookings"]]
    assert codes == [f"{order['order_code']}-{n:02d}" for n in (1, 2, 3, 4)], codes
    # đánh số theo sân (a trước b) rồi theo giờ bắt đầu
    rows = await db(
        "SELECT b.code, r.code AS court, b.start_at FROM booking.booking b "
        "JOIN booking.resource r ON r.id=b.resource_id WHERE b.code = ANY(:c) ORDER BY b.code",
        c=codes,
    )
    assert [r["court"] for r in rows] == [a, a, b, b]
    assert rows[0]["start_at"] < rows[1]["start_at"] and rows[2]["start_at"] < rows[3]["start_at"]


async def test_ac1_order_codes_are_sequential_per_play_date_and_never_reused(admin):
    (a,) = await courts(admin, 1)
    d = counter_day()
    first = await counter_ok(admin, [block(a, h(0), h(1))], d=d)
    second = await counter_ok(admin, [block(a, h(1), h(2))], d=d)
    n1, n2 = (int(o["order_code"].rsplit("-", 1)[1]) for o in (first, second))
    assert n2 == n1 + 1 and first["order_code"].startswith(f"BK-{d:%Y%m%d}-")
    third = await counter_ok(admin, [block(a, h(2), h(3))], d=d)
    assert int(third["order_code"].rsplit("-", 1)[1]) == n2 + 1


async def test_ac1_event_codes_share_the_daily_sequence_with_orders(admin):
    (a,) = await courts(admin, 1)
    async with morning():
        ev = await t6.new_session(admin, [a], hour=h(0))
    assert ev.status_code == 201, ev.text
    ev_code = ev.json()["code"]
    assert ORDER.fullmatch(ev_code) and not CHILD.fullmatch(ev_code), "AC5: event code unchanged"
    (b,) = await courts(admin, 1)
    order = await counter_ok(admin, [block(b, h(0), h(1))])
    assert order["order_code"].rsplit("-", 1)[0] == ev_code.rsplit("-", 1)[0], (
        "same play date prefix"
    )
    assert order["order_code"] != ev_code and int(order["order_code"][-3:]) > int(ev_code[-3:])


# ============================================================ AC2 online


async def test_ac2_example_two_courts_two_ranges_one_order_four_blocks(anon, admin, sepay):
    c2, c3 = await courts(admin, 2)
    sl = t8.slots(c2, 11, 12, 15, 16) + t8.slots(c3, 11, 12, 15, 16)
    co = await t8.make_checkout(anon, sl)
    assert ORDER.fullmatch(co["order_code"]) and co["pay_ref"] == co["order_code"].replace("-", "")
    assert len(co["items"]) == 4
    assert [i["code"] for i in co["items"]] == [f"{co['order_code']}-{n:02d}" for n in (1, 2, 3, 4)]
    assert sum(i["amount"] for i in co["items"]) == co["amount"]
    qr = co["bank"]["qr_url"]
    assert co["pay_ref"] in qr and not any(i["code"].replace("-", "") in qr for i in co["items"])
    assert (await t8.pay(anon, co)).status_code == 200
    done = await t8.get_checkout(anon, co["token"])
    assert done["status"] == "paid" and done["order_code"] == co["order_code"]
    rows = await db(
        "SELECT b.code, b.payment_status FROM booking.booking b "
        "JOIN booking.booking_order o ON o.id=b.order_id WHERE o.code=:o ORDER BY b.seq",
        o=co["order_code"],
    )
    assert len(rows) == 4 and {r["payment_status"] for r in rows} == {"paid"}


async def test_ac2_underpaid_creates_no_order_and_exact_remainder_does_not_complete_alone(
    anon, admin, sepay
):
    (c,) = await courts(admin, 1)
    co = await t8.make_checkout(anon, t8.slots(c, 9, 10))
    r = await t8.pay(anon, co, amount=co["amount"] - 1000)
    assert r.status_code == 200
    assert (
        await db(
            "SELECT count(*) AS n FROM booking.booking_order WHERE code=:o", o=co["order_code"]
        )
    )[0]["n"] == 0, "T-019: the order is created only when the money is complete"
    pending = await t8.get_checkout(anon, co["token"])
    assert pending["status"] in ("pending", "expired") and pending["order_code"] == co["order_code"]


async def test_ac2_expired_checkout_leaves_no_order_and_code_is_dropped(anon, admin, sepay):
    (c,) = await courts(admin, 1)
    co = await t8.make_checkout(anon, t8.slots(c, 9))
    await t8.age_checkout(co["pay_ref"], 5 * 60 + 100)
    await t8.run_expiry()
    assert (
        await db(
            "SELECT count(*) AS n FROM booking.booking_order WHERE code=:o", o=co["order_code"]
        )
    )[0]["n"] == 0
    again = await t8.make_checkout(anon, t8.slots(c, 9))
    assert ORDER.fullmatch(again["order_code"])


# ============================================================ AC3 tra cứu


async def test_ac3_lookup_by_order_or_child_code_returns_the_whole_order(anon, admin, sepay):
    a, b = await courts(admin, 2)
    ph = t8.phone()
    co = await t8.make_checkout(anon, t8.slots(a, 9, 10) + t8.slots(b, 14), ph=ph)
    await t8.pay(anon, co)
    child = co["items"][1]["code"]
    for ident in (co["order_code"], child, child.lower(), child.replace("-", "")):
        r = await t8.lookup(anon, ident, ph)
        assert r.status_code == 200, (ident, r.text)
        d = r.json()
        assert d["order_code"] == co["order_code"] and d["status"] == "paid"
        assert len(d["items"]) == 2 and d["hours"] == 3 and d["amount"] == co["amount"]
        assert ph not in json.dumps(d) and d["phone_masked"].count("x") >= 3
    wrong = await t8.lookup(anon, co["order_code"], t8.phone())
    unknown = await t8.lookup(anon, "BK-20200101-999", ph)
    err(wrong, 404, "E-WEB-7")
    assert wrong.json() == unknown.json(), "no enumeration oracle"


async def test_ac3_lookup_order_status_follows_its_blocks(anon, admin, sepay):
    """Còn khối chưa thu -> unpaid; tất cả đã thu -> paid (đơn quầy)."""
    a, b = await courts(admin, 2)
    ph = t8.phone()
    order = await counter_ok(
        admin,
        [block(a, h(0), h(1)), block(b, h(0), h(1))],
        customer={"temp": {"full_name": "QA Tra", "phone": ph}},
    )
    assert (await t8.lookup(anon, order["order_code"], ph)).json()["status"] == "unpaid"
    first = order["bookings"][0]
    r = await admin.post(
        f"{BK}/items/{first['code']}/collect",
        json={"method": "cash", "version": first["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (await t8.lookup(anon, order["order_code"], ph)).json()["status"] == "unpaid", (
        "one block still unpaid"
    )
    done = await admin.post(
        f"{BK}/orders/{order['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert done.status_code == 200, done.text
    assert (await t8.lookup(anon, order["order_code"], ph)).json()["status"] == "paid"


# ============================================================ AC4 quầy


async def test_ac4_blocks_validation(admin):
    (a,) = await courts(admin, 1)
    cust = {"temp": {"full_name": "QA Hợp Lệ", "phone": t8.phone()}}
    r = await counter(admin, [], customer=cust)
    assert r.status_code == 422
    r = await counter(admin, [block(a, h(i % 6), h(i % 6 + 1)) for i in range(21)], customer=cust)
    assert r.status_code == 422, "more than 20 blocks"
    r = await counter(admin, [block(a, h(1), h(3)), block(a, h(2), h(4))], customer=cust)
    assert r.status_code == 422 and t8.code_of(r) == "E-001", "overlapping blocks of one court"
    both = await counter(
        admin, [block(a, h(0), h(1))], customer=cust,
        extra={"resource_code": a, "start_hour": h(0), "end_hour": h(1)},
    )  # fmt: skip
    assert both.status_code == 422, "old single-block fields together with blocks[]"
    n = (
        await db(
            "SELECT count(*) AS n FROM booking.booking b JOIN booking.resource r ON r.id=b.resource_id WHERE r.code=:c",
            c=a,
        )
    )[0]["n"]
    assert n == 0, "nothing created by invalid requests"


async def test_ac4_adjacent_blocks_of_one_court_merge_into_one(admin):
    (a,) = await courts(admin, 1)
    order = await counter_ok(
        admin, [block(a, h(0), h(1)), block(a, h(1), h(3)), block(a, h(4), h(5))]
    )
    assert len(order["bookings"]) == 2, "9-10 + 10-12 merge into 9-12; 14-15 stays"
    rows = await db(
        "SELECT extract(epoch FROM end_at-start_at)/3600 AS h FROM booking.booking WHERE code = ANY(:c) ORDER BY seq",
        c=[x["code"] for x in order["bookings"]],
    )
    assert [int(r["h"]) for r in rows] == [3, 1]


async def test_ac4_all_or_nothing_on_conflict(admin):
    a, b = await courts(admin, 2)
    await counter_ok(admin, [block(b, h(3), h(4))])  # chiếm trước b 12-13
    r = await counter(admin, [block(a, h(0), h(1)), block(b, h(3), h(4)), block(a, h(5), h(6))])
    assert r.status_code == 409 and t8.code_of(r) == "E-003", r.text
    conflicts = r.json()["detail"]["conflicts"]
    assert {(c["resource_code"], c["start_hour"]) for c in conflicts} == {(b, h(3))}
    n = (
        await db(
            "SELECT count(*) AS n FROM booking.booking b JOIN booking.resource r ON r.id=b.resource_id WHERE r.code=:c",
            c=a,
        )
    )[0]["n"]
    assert n == 0, "the other blocks were not created"


async def test_ac4_legacy_single_block_form_still_works_and_returns_order(admin):
    (a,) = await courts(admin, 1)
    async with morning():
        r = await admin.post(
            f"{FD}/bookings",
            json={"resource_code": a, "date": counter_day().isoformat(), "start_hour": h(0), "end_hour": h(1),
                  "customer": {"temp": {"full_name": "QA Một Khối", "phone": t8.phone()}}},
            headers=idem(),
        )  # fmt: skip
    assert r.status_code == 201, r.text
    body = r.json()
    assert ORDER.fullmatch(body["order_code"]) and len(body["bookings"]) == 1
    assert body["bookings"][0]["code"] == f"{body['order_code']}-01"


async def test_ac4_double_submit_with_same_idempotency_key_creates_one_order(admin):
    (a,) = await courts(admin, 1)
    key = idem()
    body = {
        "date": counter_day().isoformat(), "blocks": [block(a, h(0), h(1))],
        "customer": {"temp": {"full_name": "QA Idem", "phone": t8.phone()}},
    }  # fmt: skip
    async with morning():
        r1 = await admin.post(f"{FD}/bookings", json=body, headers=key)
        r2 = await admin.post(f"{FD}/bookings", json=body, headers=key)
    assert r1.status_code == 201 and r2.status_code == 201
    o1, o2 = r1.json(), r2.json()
    assert o1["order_code"] == o2["order_code"]
    n = (
        await db(
            "SELECT count(*) AS n FROM booking.booking WHERE code=:c", c=o1["bookings"][0]["code"]
        )
    )[0]["n"]
    assert n == 1


async def test_ac4_concurrent_orders_for_same_slot_only_one_wins(admin):
    (a,) = await courts(admin, 1)
    res = await asyncio.gather(
        *[
            counter(
                admin,
                [block(a, h(0), h(1))],
                customer={"temp": {"full_name": f"QA R{i}", "phone": t8.phone()}},
            )
            for i in range(5)
        ]
    )
    codes = sorted(r.status_code for r in res)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes


async def test_ac4_collect_whole_order_rules(admin, staff, anon, customer):
    a, b, c = await courts(admin, 3)
    order = await counter_ok(
        admin, [block(a, h(0), h(1)), block(b, h(0), h(1)), block(c, h(0), h(1))]
    )
    oc = order["order_code"]
    url = f"{BK}/orders/{oc}/collect"
    # quyền
    assert (await anon.post(url, json={"method": "cash"}, headers=idem())).status_code == 401
    assert (await customer.post(url, json={"method": "cash"}, headers=idem())).status_code == 403
    # chuyển khoản chưa hỗ trợ; thiếu Idempotency-Key
    err(await admin.post(url, json={"method": "transfer"}, headers=idem()), 422, "E-PAY-0")
    assert (await admin.post(url, json={"method": "cash"})).status_code in (400, 422)
    # khối 1 không thu được, khối 2 đã thu lẻ -> thu cả đơn chỉ thu khối 3
    b1, b2, b3 = order["bookings"]
    async with morning(20):  # khối 8h–13h đã tới giờ (Không thu được chỉ cho khối đã bắt đầu)
        r = await admin.post(
            f"{BK}/items/{b1['code']}/uncollectible",
            json={"reason": "QA", "version": b1["version"]},
            headers=idem(),
        )
    assert r.status_code == 200, r.text
    r = await admin.post(
        f"{BK}/items/{b2['code']}/collect",
        json={"method": "cash", "version": b2["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    key = idem()
    done = await staff.post(url, json={"method": "cash"}, headers=key)  # NV được thu tiền
    assert done.status_code == 200, done.text
    body = done.json()
    assert (
        body["order_code"] == oc
        and body["collected"] == [b3["code"]]
        and body["amount"] == b3["payment"]["amount"]
    )
    states = {x["code"]: x["payment"]["payment_status"] for x in body["bookings"]}
    assert states == {b1["code"]: "uncollectible", b2["code"]: "paid", b3["code"]: "paid"}, (
        "other blocks untouched"
    )
    replay = await staff.post(url, json={"method": "cash"}, headers=key)
    assert replay.status_code == 200 and replay.json() == body, (
        "same Idempotency-Key -> same answer"
    )
    err(await admin.post(url, json={"method": "cash"}, headers=idem()), 409, "E-BOOK-4")
    err(
        await admin.post(
            f"{BK}/orders/BK-20200101-999/collect", json={"method": "cash"}, headers=idem()
        ),
        404,
        "E-BOOK-3",
    )


async def test_ac4_collect_order_is_atomic_under_concurrent_requests(admin):
    a, b = await courts(admin, 2)
    order = await counter_ok(admin, [block(a, h(0), h(1)), block(b, h(0), h(1))])
    url = f"{BK}/orders/{order['order_code']}/collect"
    res = await asyncio.gather(
        *[admin.post(url, json={"method": "cash"}, headers=idem()) for _ in range(4)]
    )
    statuses = sorted(r.status_code for r in res)
    assert statuses.count(200) == 1 and set(statuses) <= {200, 409}, statuses
    paid = (
        await db(
            "SELECT count(*) AS n FROM booking.booking WHERE code = ANY(:c) AND payment_status='paid'",
            c=[x["code"] for x in order["bookings"]],
        )
    )[0]["n"]
    assert paid == 2


async def test_ac4_search_by_order_code_and_child_code(admin, staff):
    a, b = await courts(admin, 2)
    order = await counter_ok(admin, [block(a, h(0), h(1)), block(b, h(0), h(1))])
    oc, children = order["order_code"], [x["code"] for x in order["bookings"]]
    for who in (admin, staff):
        r = await who.get(f"{BK}/search", params={"code": oc})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == "order" and d["order_code"] == oc and d["codes"] == children
        r = await who.get(f"{BK}/search", params={"code": children[1].lower()})
        assert (
            r.json()["kind"] == "booking"
            and r.json()["code"] == children[1]
            and r.json()["order_code"] == oc
        )
    assert (await admin.get(f"{BK}/search", params={"code": "BK-20200101-999"})).status_code in (
        404,
        422,
    )


async def test_ac4_item_detail_by_child_code_and_single_block_order_code(admin):
    (a,) = await courts(admin, 1)
    order = await counter_ok(admin, [block(a, h(0), h(1))])
    by_child = await admin.get(f"{BK}/items/{order['bookings'][0]['code']}")
    by_order = await admin.get(f"{BK}/items/{order['order_code']}")
    assert by_child.status_code == 200 and by_order.status_code == 200
    assert by_order.json()["code"] == by_child.json()["code"], (
        "one-block order code opens that block"
    )
    assert by_child.json()["order_code"] == order["order_code"]


async def test_ac4_calendar_and_transactions_carry_order_code(admin):
    a, b = await courts(admin, 2)
    d = counter_day()
    order = await counter_ok(admin, [block(a, h(0), h(1)), block(b, h(0), h(1))], d=d)
    cal = await t6.calendar(admin, d)
    blocks = {
        x["code"]: x
        for x in cal["blocks"]
        if x.get("code") in {y["code"] for y in order["bookings"]}
    }
    assert len(blocks) == 2 and all(x["order_code"] == order["order_code"] for x in blocks.values())
    for x in order["bookings"]:
        await admin.post(
            f"{BK}/items/{x['code']}/collect",
            json={"method": "cash", "version": x["version"]},
            headers=idem(),
        )
    tx = await admin.get(f"{BK}/transactions", params={"q": order["order_code"]})
    assert tx.status_code == 200, tx.text
    entries = [r for r in tx.json()["items"] if r.get("order_code") == order["order_code"]]
    assert len(entries) == 2, tx.json()["items"]  # thu từng khối = mỗi lần thu một dòng sổ
    codes = [i["code"] for e in entries for i in e["items"]]
    assert sorted(codes) == sorted(x["code"] for x in order["bookings"])
    assert all(c.startswith(order["order_code"] + "-") for c in codes), (
        "transactions show order + child code"
    )


# ============================================================ AC5 sự kiện và vé giữ nguyên


async def test_ac5_event_and_ticket_codes_unchanged(admin):
    (a,) = await courts(admin, 1)
    ev = await t6.new_session(admin, [a], capacity=3, hour=t6.usable_hour())
    assert ev.status_code == 201, ev.text
    code = ev.json()["code"]
    assert ORDER.fullmatch(code) and not CHILD.fullmatch(code)
    tk = await admin.post(
        f"{FD}/sessions/{code}/tickets",
        json={"customer": {"temp": {"full_name": "QA Vé", "phone": t8.phone()}}},
        headers=idem(),
    )
    if tk.status_code == 201:
        assert re.fullmatch(rf"{code}-V\d{{2}}", tk.json()["code"]), tk.json()["code"]


# ============================================================ AC8 audit + outbox


async def test_ac8_audit_and_outbox_carry_order_code_and_no_phone(anon, admin, sepay):
    a, b = await courts(admin, 2)
    ph = t8.phone()
    order = await counter_ok(
        admin,
        [block(a, h(0), h(1)), block(b, h(0), h(1))],
        customer={"temp": {"full_name": "QA Audit", "phone": ph}},
    )
    oc = order["order_code"]
    audit = await db(
        "SELECT action, detail::text AS d FROM audit_log WHERE detail::text LIKE :p", p=f"%{oc}%"
    )
    actions = {r["action"] for r in audit}
    assert "booking.counter.create" in actions, actions
    assert all(
        "password" not in r["d"].lower() for r in audit
    )  # PR #22: SĐT đầy đủ trong nhật ký là chấp nhận (BR-007)
    ev = await db(
        "SELECT event_type, payload::text AS p FROM booking.outbox WHERE payload::text LIKE :p AND event_type = 'booking.created'",
        p=f"%{oc}%",
    )
    assert len(ev) == 2, "booking.created is emitted once per block, counter included"
    for e in ev:
        pl = json.loads(e["p"])
        assert (
            pl["order_code"] == oc
            and CHILD.fullmatch(pl["code"])
            and ph not in e["p"]
            and "customer_ref" not in e["p"]
        )
    # online
    co = await t8.make_checkout(anon, t8.slots(a, 15, 16), ph=t8.phone())
    assert (await t8.pay(anon, co)).status_code == 200
    paid = await db(
        "SELECT payload::text AS p FROM booking.outbox WHERE event_type='booking.online_paid' AND payload::text LIKE :p",
        p=f"%{co['order_code']}%",
    )
    assert paid, "booking.online_paid is emitted"
    pl = json.loads(paid[0]["p"])
    assert pl["order_code"] == co["order_code"] and pl["codes"] == [i["code"] for i in co["items"]]


async def test_ac8_collect_order_is_audited(admin):
    a, b = await courts(admin, 2)
    order = await counter_ok(admin, [block(a, h(0), h(1)), block(b, h(0), h(1))])
    r = await admin.post(
        f"{BK}/orders/{order['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200
    rows = await db(
        "SELECT detail::text AS d FROM audit_log WHERE action='payment.collect_order' AND detail::text LIKE :p",
        p=f"%{order['order_code']}%",
    )
    assert len(rows) == 1


# ============================================================ AC6 migration trên dữ liệu cũ + ràng buộc không đổi


async def test_ac6_exclusion_constraint_still_blocks_overlap_across_orders(admin):
    (a,) = await courts(admin, 1)
    await counter_ok(admin, [block(a, h(0), h(2))])
    r = await counter(admin, [block(a, h(1), h(3))])
    assert r.status_code == 409 and t8.code_of(r) == "E-003"
    r = await counter(admin, [block(a, h(2), h(3))])
    assert r.status_code == 201, "[start, end) ranges: 9-11 and 11-12 do not overlap"


async def test_ac6_every_booking_belongs_to_an_order_with_unique_child_numbers():
    bad = await db("SELECT count(*) AS n FROM booking.booking WHERE order_id IS NULL")
    assert bad[0]["n"] == 0
    dup = await db(
        "SELECT order_id, seq FROM booking.booking GROUP BY order_id, seq HAVING count(*) > 1"
    )
    assert dup == []
    wrong = await db(
        "SELECT b.code FROM booking.booking b JOIN booking.booking_order o ON o.id=b.order_id "
        "WHERE o.code ~ '^BK-[0-9]{8}-[0-9]{3}$' "  # bỏ dòng test khác nạp thẳng bằng mã giả (BK-TEST-001…)
        "AND b.code <> o.code || '-' || lpad(b.seq::text, 2, '0') LIMIT 5"
    )
    assert wrong == [], "child code = order code + '-' + 2-digit seq"


async def test_ac6_pending_checkout_codes_are_unique():
    rows = await db(
        "SELECT order_code, count(*) FROM booking.checkout GROUP BY order_code HAVING count(*) > 1"
    )
    assert rows == []

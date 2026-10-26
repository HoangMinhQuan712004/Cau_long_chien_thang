"""QA acceptance tests for T-006 (counter booking, sessions, tickets, collection, history).

Source of truth: board/tasks/T-006-dat-san-quan-tri.md (AC1-AC24, SEC1-SEC9).
Tests talk to the public HTTP contract only. UI-only criteria (drag selection, countdown,
30 s auto refresh, toasts, mobile layout) are verified by hand / on the dev link
(see qa/T-006-report.md).

ASSUMED CONTRACT (the spec leaves response shapes open; adjust section 1 at BE handoff):
  * coded errors: 4xx + {"detail": {"code": "E-xxx", ...}} (exact status not asserted)
  * POST /front-desk/bookings -> 201 {code, amount, payment_status, version, ...}
  * POST /booking/sessions -> 201 {code, ...}
  * GET /booking/sessions/{code} -> {name, taken, capacity, version, tickets[], can}
  * POST /front-desk/sessions/{code}/tickets -> 201 {code, amount, version, ...}
  * GET /booking/items/{code} -> pinned by ARCHITECT: {kind, code, version, customer{}, schedule{},
    payment{amount, payment_status, ...}, note?, actions[]} (item() adds flat amount/payment_status)
  * GET /booking/calendar -> blocks[] with `code`, `type`, `payment_status`,
    `resource_code`; `unpaid_count`
  * GET /booking/transactions -> {rows[], page, total,
    cards{paid,unpaid,uncollectible:{amount,count}}}
  * members live in table `customer` (kind, member_code, phone, full_name, is_active)
Test resources are created fresh per test and open 00:00-24:00, so any hour of today is usable
and tests never collide on slots (the DB is shared across the whole test session).
"""

import asyncio
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import SessionLocal
from tests.conftest import API, ORIGIN

B = f"{API}/booking"
FD = f"{API}/front-desk"
MEMBERS = f"{API}/members"
EVIL = "https://evil.example"
XSS = "<script>alert(1)</script>"
FAKE_CODE = "BK-20200101-999"


# ---------------------------------------------------------------------------
# 1. Contract helpers
# ---------------------------------------------------------------------------


def key() -> str:
    return str(uuid.uuid4())


def now_local() -> datetime:
    return datetime.now(settings.tz)


def today() -> date:
    return now_local().date()


def code_of(resp) -> str | None:
    try:
        detail = resp.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return None
    return detail.get("code") if isinstance(detail, dict) else None


# HTTP status per error code, pinned by ARCHITECT (spec section 4)
ERR_STATUS = {
    **dict.fromkeys(("E-003", "E-010", "E-012", "E-018", "E-023", "E-024"), 409),
    **dict.fromkeys(("E-001", "E-002", "E-004", "E-009", "E-013", "E-016", "E-019", "E-020"), 422),
    "E-021": 404,
}


def assert_err(resp, code: str) -> None:
    want = ERR_STATUS.get(code)
    if want is not None:
        assert resp.status_code == want, (code, want, resp.status_code, resp.text)
    else:
        assert 400 <= resp.status_code < 500, (resp.status_code, resp.text)
    assert code_of(resp) == code, (code, resp.status_code, resp.text)


def _flatten_payment(resp) -> None:
    """ItemOut nests amount/payment_status under `payment`; add flat aliases for readability."""
    if not 200 <= resp.status_code < 300 or "json" not in resp.headers.get("content-type", ""):
        return
    data = resp.json()
    if isinstance(data, dict) and isinstance(data.get("payment"), dict):
        flat = {
            "amount": data["payment"].get("amount"),
            "payment_status": data["payment"].get("payment_status"),
        }
        resp._content = json.dumps({**flat, **data}).encode()


async def w(client, method, path, body=None, *, k="auto", **kw):
    """Write request with an Idempotency-Key (k=None -> no header)."""
    headers = dict(kw.pop("headers", {}))
    if k == "auto":
        headers["Idempotency-Key"] = key()
    elif k is not None:
        headers["Idempotency-Key"] = k
    resp = await client.request(method, path, json=body, headers=headers, **kw)
    _flatten_payment(resp)
    return resp


def phone() -> str:
    return "09" + str(uuid.uuid4().int)[:8]


def temp(name: str | None = None, ph: str | None = None, note: str | None = None) -> dict:
    t = {"full_name": name or f"QA Khách {uuid.uuid4().hex[:5]}", "phone": ph or phone()}
    if note is not None:
        t["note"] = note
    return {"temp": t}


async def new_resource(adm, *, close="24:00") -> dict:
    r = await w(
        adm,
        "POST",
        f"{B}/resources",
        {
            "name": f"QA {uuid.uuid4().hex[:8]}",
            "resource_type_code": "thuong",
            "open_time": "00:00",
            "close_time": close,
            "peak_bands": [["17:00", "21:00"]],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def usable_hour(offset: int = 0) -> int:
    """An hour of today whose frame is not over yet (in progress is allowed, BR-011)."""
    h = now_local().hour + offset
    if h > 23:
        pytest.skip("too late in the day for a same-day frame")
    return h


def booking_body(res_code: str, hour: int, customer: dict | None = None, day: date | None = None):
    return {
        "resource_code": res_code,
        "date": (day or today()).isoformat(),
        "start_hour": hour,
        "end_hour": hour + 1,
        "customer": customer if customer is not None else temp(),
    }


async def book(client, res_code: str, hour: int | None = None, customer=None, **kw):
    h = usable_hour() if hour is None else hour
    return await w(client, "POST", f"{FD}/bookings", booking_body(res_code, h, customer), **kw)


async def new_booking(adm, hour: int | None = None, customer=None):
    res = await new_resource(adm)
    r = await book(adm, res["code"], hour, customer)
    assert r.status_code == 201, r.text
    return res, r.json()


async def new_session(adm, resources: list[str], *, capacity=3, price=50000, name=None, hour=None):
    h = usable_hour() if hour is None else hour
    r = await w(
        adm,
        "POST",
        f"{B}/sessions",
        {
            "resource_codes": resources,
            "date": today().isoformat(),
            "start_hour": h,
            "end_hour": h + 1,
            "name": name or f"QA sự kiện {uuid.uuid4().hex[:5]}",
            "capacity": capacity,
            "ticket_price": price,
        },
    )
    return r


async def item(client, code: str) -> dict:
    r = await client.get(f"{B}/items/{code}")
    assert r.status_code == 200, r.text
    data = r.json()
    pay = data.get("payment", {})  # spec: payment{amount, payment_status, ...}; keep flat aliases
    return {"amount": pay.get("amount"), "payment_status": pay.get("payment_status"), **data}


async def calendar(client, day: date | None = None) -> dict:
    r = await client.get(f"{B}/calendar", params={"date": (day or today()).isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


async def audit_rows(where: str = "TRUE", params: dict | None = None):
    async with SessionLocal() as s:
        res = await s.execute(
            text(f"SELECT * FROM audit_log WHERE {where} ORDER BY id DESC"), params or {}
        )
        return res.mappings().all()


async def member_row(active: bool = True):
    async with SessionLocal() as s:
        res = await s.execute(
            text(
                "SELECT member_code, full_name, phone FROM customer "
                "WHERE kind='member' AND is_active=:a ORDER BY id LIMIT 1"
            ),
            {"a": active},
        )
        return res.mappings().first()


async def all_phones() -> set[str]:
    async with SessionLocal() as s:
        res = await s.execute(text("SELECT phone FROM customer"))
        return {r[0] for r in res}


def walk(data):
    if isinstance(data, dict):
        for k, v in data.items():
            yield k, v
            yield from walk(v)
    elif isinstance(data, list):
        for v in data:
            yield from walk(v)


# ---------------------------------------------------------------------------
# 2. Calendar (AC1-AC3, AC5)
# ---------------------------------------------------------------------------


async def test_ac1_calendar_shape_and_speed(staff):
    t0 = time.perf_counter()
    r = await staff.get(f"{B}/calendar", params={"date": today().isoformat()})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 1.0, f"calendar took {elapsed:.2f}s (NFR-001 server < 1 s)"
    data = r.json()
    for k in ("date", "now", "columns", "resources", "blocks", "unpaid_count", "can"):
        assert k in data, k
    assert data["can"]["counter_book"] is True
    assert data["can"]["create_session"] is False  # staff cannot create events


async def test_ac1_admin_can_create_session(admin):
    assert (await calendar(admin))["can"]["create_session"] is True


async def test_ac2_rows_columns_and_off_hours(admin):
    res = await w(
        admin,
        "POST",
        f"{B}/resources",
        {
            "name": f"QA muộn {uuid.uuid4().hex[:5]}",
            "resource_type_code": "thuong",
            "open_time": "06:00",
            "close_time": "22:00",
            "peak_bands": [["17:00", "21:00"]],
        },
    )
    assert res.status_code == 201, res.text
    code = res.json()["code"]
    data = await calendar(admin)
    row = next(x for x in data["resources"] if x["code"] == code)
    assert 5 in row["off_hours"] and 22 not in row["off_hours"] and 6 not in row["off_hours"]
    assert row["is_active"] is True
    # inactive resource without allocations is not shown
    pr = await admin.get(f"{B}/resources")
    inactive = [x for x in pr.json().get("items", pr.json()) if x.get("is_active") is False]
    shown = {x["code"] for x in data["resources"]}
    for x in inactive:
        assert x["code"] not in shown, "inactive resource without allocation must be hidden"


async def test_ac2_past_and_far_dates(staff):
    # past day: view only (200); next month still viewable; beyond the end of next month rejected
    assert (
        await staff.get(f"{B}/calendar", params={"date": (today() - timedelta(days=3)).isoformat()})
    ).status_code == 200
    far = today() + timedelta(days=120)
    r = await staff.get(f"{B}/calendar", params={"date": far.isoformat()})
    assert r.status_code in (400, 422), r.text
    bad = await staff.get(f"{B}/calendar", params={"date": "2026-13-45"})
    assert bad.status_code == 422


async def test_ac3_block_fields_booking_session_uncollectible(admin):
    res, bk = await new_booking(admin, customer=temp("QA Hiển Thị", "0987654321"))
    blocks = {b["code"]: b for b in (await calendar(admin))["blocks"] if "code" in b}
    b = blocks[bk["code"]]
    assert b["payment_status"] == "unpaid"
    assert "0987654321" not in str(b) and "xxx" in str(b)
    # session block: name + taken/capacity
    r = await new_session(admin, [(await new_resource(admin))["code"]], capacity=2)
    assert r.status_code == 201, r.text
    s = r.json()
    blocks = {b["code"]: b for b in (await calendar(admin))["blocks"] if "code" in b}
    assert s["code"] in blocks and blocks[s["code"]]["type"] == "session"
    # uncollectible block keeps its status
    mark = await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/uncollectible",
        {"reason": "QA", "version": bk["version"]},
    )
    assert mark.status_code == 200, mark.text
    blocks = {b["code"]: b for b in (await calendar(admin))["blocks"] if "code" in b}
    assert blocks[bk["code"]]["payment_status"] == "uncollectible"


async def test_ac5_search_code_normalised(staff, admin):
    res, bk = await new_booking(admin)
    messy = f"  {bk['code'].lower()} "
    r = await staff.get(f"{B}/search", params={"code": messy})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "booking" and r.json()["code"] == bk["code"]
    assert "play_date" in r.json()
    # session + ticket kinds
    s = (await new_session(admin, [(await new_resource(admin))["code"]])).json()
    assert (await staff.get(f"{B}/search", params={"code": s["code"]})).json()["kind"] == "session"
    t = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
    assert t.status_code == 201, t.text
    assert (await staff.get(f"{B}/search", params={"code": t.json()["code"]})).json()[
        "kind"
    ] == "ticket"
    # exact match only: no name / phone / partial search
    for bad in ("QA", "0987654321", bk["code"][:-1], FAKE_CODE):
        r = await staff.get(f"{B}/search", params={"code": bad})
        assert r.status_code == 404, (bad, r.text)
        assert code_of(r) == "E-021"


# ---------------------------------------------------------------------------
# 3. Counter booking (AC8-AC12)
# ---------------------------------------------------------------------------


async def test_ac8_member_booking_and_members_search(staff, admin):
    m = await member_row()
    assert m is not None, "seed must provide members"
    res = await new_resource(admin)
    # search by code / name / phone (case-insensitive, contains)
    for q in (
        m["member_code"],
        m["member_code"].lower(),
        m["full_name"][:4].upper(),
        m["phone"][-4:],
    ):
        r = await staff.get(f"{MEMBERS}/search", params={"q": q})
        assert r.status_code == 200, (q, r.text)
        rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        assert any(x["member_code"] == m["member_code"] for x in rows), q
        assert len(rows) <= 20
    r = await book(staff, res["code"], customer={"member_code": m["member_code"]})
    assert r.status_code == 201, r.text
    bk = r.json()
    assert bk["payment_status"] == "unpaid" and bk["code"].startswith("BK-")
    assert re.fullmatch(r"BK-\d{8}-\d{3}", bk["code"])
    before = (await calendar(staff))["unpaid_count"]
    assert before >= 1


async def test_ac8_member_search_validates_q(staff):
    assert (await staff.get(f"{MEMBERS}/search", params={"q": ""})).status_code == 422
    assert (await staff.get(f"{MEMBERS}/search", params={"q": "x" * 51})).status_code == 422


async def test_ac8_inactive_member_is_listed_with_flag(staff):
    m = await member_row(active=False)
    if not m:
        pytest.skip("seed has no inactive member")
    r = await staff.get(f"{MEMBERS}/search", params={"q": m["member_code"]})
    rows = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
    assert any(x["member_code"] == m["member_code"] and x["is_active"] is False for x in rows)


async def test_ac9_temp_profile_reuse_keeps_old_name_and_note_on_booking(staff, admin):
    ph = phone()
    r1 = await book(
        staff, (await new_resource(admin))["code"], customer=temp("Tên Cũ", ph, "ghi chú 1")
    )
    assert r1.status_code == 201, r1.text
    r2 = await book(
        staff, (await new_resource(admin))["code"], customer=temp("Tên Mới", ph, "ghi chú 2")
    )
    assert r2.status_code == 201, r2.text
    it2 = await item(staff, r2.json()["code"])
    assert "Tên Cũ" in str(it2) and "Tên Mới" not in str(it2), "OQ-21: reuse keeps the old name"
    assert "ghi chú 2" in str(it2), "OQ-18: note is stored on the booking"
    async with SessionLocal() as s:
        n = await s.scalar(text("SELECT count(*) FROM customer WHERE phone=:p"), {"p": ph})
    assert n == 1


async def test_ac9_member_phone_rejected_and_nothing_created(staff, admin):
    m = await member_row()
    assert m is not None, "seed must provide members"
    res = await new_resource(admin)
    before = len(await audit_rows("action LIKE 'member.temp.%'"))
    r = await book(staff, res["code"], customer=temp("Giả hội viên", m["phone"]))
    assert_err(r, "E-018")
    assert len(await audit_rows("action LIKE 'member.temp.%'")) == before
    cal = await calendar(staff)
    assert not [b for b in cal["blocks"] if b.get("resource_code") == res["code"]]


@pytest.mark.parametrize(
    "customer",
    [
        {"temp": {"full_name": "", "phone": "0912345678"}},
        {"temp": {"full_name": "x" * 101, "phone": "0912345678"}},
        {"temp": {"full_name": "Ok", "phone": "123"}},
        {"temp": {"full_name": "Ok", "phone": "09123456789"}},
        {"temp": {"full_name": "Ok", "phone": "abcdefghij"}},
        {"temp": {"full_name": "Ok", "phone": "0912345678", "note": "n" * 501}},
        {"member_code": "NOPE99"},
        {},
    ],
)
async def test_ac9_invalid_customer_rejected(staff, admin, customer):
    res = await new_resource(admin)
    r = await book(staff, res["code"], customer=customer)
    assert r.status_code in (404, 422), r.text


async def test_ac10_two_requests_same_slot_one_wins(staff, admin):
    res = await new_resource(admin)
    h = usable_hour()
    rs = await asyncio.gather(*[book(staff, res["code"], h) for _ in range(2)])
    assert sorted(r.status_code for r in rs)[0] == 201
    losers = [r for r in rs if r.status_code != 201]
    assert len(losers) == 1
    assert_err(losers[0], "E-003")


async def test_sec5_twenty_parallel_bookings_one_success(staff, admin):
    res = await new_resource(admin)
    h = usable_hour()
    rs = await asyncio.gather(*[book(staff, res["code"], h) for _ in range(20)])
    ok = [r for r in rs if r.status_code == 201]
    assert len(ok) == 1, [r.status_code for r in rs]
    assert all(code_of(r) == "E-003" for r in rs if r.status_code != 201)
    async with SessionLocal() as s:
        n = await s.scalar(
            text(
                "SELECT count(*) FROM booking.allocation a JOIN booking.resource r "
                "ON r.id=a.resource_id WHERE r.code=:c AND a.active"
            ),
            {"c": res["code"]},
        )
    assert n == 1


async def test_ac10_adjacent_frames_do_not_collide(staff, admin):
    res = await new_resource(admin)
    h = usable_hour()
    if h > 22:
        pytest.skip("need two hours left today")
    a = await book(staff, res["code"], h)
    b = await book(staff, res["code"], h + 1)
    assert a.status_code == 201 and b.status_code == 201, (a.text, b.text)


async def test_ac11_staff_cannot_book_tomorrow_or_past(staff, admin):
    res = await new_resource(admin)
    tomorrow = booking_body(res["code"], 10, day=today() + timedelta(days=1))
    r = await w(staff, "POST", f"{FD}/bookings", tomorrow)
    assert r.status_code in (403, 422), r.text
    h = now_local().hour
    if h >= 1:
        past = await book(staff, res["code"], h - 1)
        assert_err(past, "E-004")
    # end <= now boundary: the in-progress frame is bookable (BR-011)
    ok = await book(staff, res["code"], h)
    assert ok.status_code == 201, ok.text


async def test_ac11_multi_hour_and_bad_ranges_rejected(staff, admin):
    res = await new_resource(admin)
    h = usable_hour()
    body = booking_body(res["code"], h)
    for start, end in ((h + 1, h), (h, h), (-1, 1), (h, 25)):
        r = await w(staff, "POST", f"{FD}/bookings", {**body, "start_hour": start, "end_hour": end})
        assert r.status_code in (400, 422), (start, end, r.text)
    unknown = await w(staff, "POST", f"{FD}/bookings", {**body, "resource_code": "ZZ999"})
    assert unknown.status_code in (404, 422)


async def test_ac12_amount_is_server_price_and_frozen(admin, staff):
    res = await new_resource(admin)
    h = usable_hour()
    quote = await staff.post(
        f"{B}/quote",
        json={
            "resource_code": res["code"],
            "date": today().isoformat(),
            "start_hour": h,
            "end_hour": h + 1,
        },
    )
    assert quote.status_code == 200, quote.text
    expected = quote.json().get("total_amount", quote.json().get("total"))
    bk = (await book(staff, res["code"], h)).json()
    assert bk["amount"] == expected
    # change the price table, old booking must keep its amount
    cur = (await admin.get(f"{B}/prices")).json()
    bumped = [{**p, "price_per_hour": p["price_per_hour"] + 1000} for p in cur["prices"]]
    put = await w(admin, "PUT", f"{B}/prices", {"version": cur["version"], "prices": bumped})
    assert put.status_code == 200, put.text
    try:
        assert (await item(staff, bk["code"]))["amount"] == expected
        res2 = await new_resource(admin)
        new = (await book(staff, res2["code"], h)).json()
        assert new["amount"] == expected + 1000
    finally:
        cur2 = (await admin.get(f"{B}/prices")).json()
        back = [{**p, "price_per_hour": p["price_per_hour"] - 1000} for p in cur2["prices"]]
        restore = await w(admin, "PUT", f"{B}/prices", {"version": cur2["version"], "prices": back})
        assert restore.status_code == 200, restore.text


# ---------------------------------------------------------------------------
# 4. Sessions and tickets (AC13-AC16)
# ---------------------------------------------------------------------------


async def test_ac13_admin_multi_resource_session_staff_forbidden(admin, staff):
    a, b = await new_resource(admin), await new_resource(admin)
    r = await new_session(admin, [a["code"], b["code"]], capacity=10, price=40000)
    assert r.status_code == 201, r.text
    assert re.fullmatch(r"BK-\d{8}-\d{3}", r.json()["code"])
    blocks = [x for x in (await calendar(admin))["blocks"] if x.get("code") == r.json()["code"]]
    assert blocks, "session block must appear on the calendar"
    h = usable_hour()
    denied = await w(
        staff,
        "POST",
        f"{B}/sessions",
        {
            "resource_codes": [a["code"]],
            "date": today().isoformat(),
            "start_hour": h,
            "end_hour": h + 1,
            "name": "x",
            "capacity": 5,
            "ticket_price": 0,
        },
    )
    assert denied.status_code == 403 and code_of(denied) == "E-AUTH-2"


@pytest.mark.parametrize(
    ("patch", "code"),
    [
        ({"capacity": 0}, "E-009"),
        ({"capacity": 100}, "E-009"),
        ({"ticket_price": -1}, "E-013"),
        ({"name": ""}, "E-001"),
        ({"name": "x" * 101}, "E-001"),
    ],
)
async def test_ac13_session_validation(admin, patch, code):
    res = await new_resource(admin)
    h = usable_hour()
    body = {
        "resource_codes": [res["code"]],
        "date": today().isoformat(),
        "start_hour": h,
        "end_hour": h + 1,
        "name": "QA",
        "capacity": 5,
        "ticket_price": 1000,
        **patch,
    }
    r = await w(admin, "POST", f"{B}/sessions", body)
    assert 400 <= r.status_code < 500, r.text
    got = code_of(r)  # a plain 422 from the schema layer carries no code; a coded error must match
    assert got is None or got == code, (got, code)


async def test_ac13_session_vs_booking_conflicts(admin, staff):
    res, _bk = await new_booking(admin)
    r = await new_session(admin, [res["code"]])
    assert_err(r, "E-010")
    res2 = await new_resource(admin)
    assert (await new_session(admin, [res2["code"]])).status_code == 201
    assert_err(await book(staff, res2["code"]), "E-003")


async def test_ac13_non_adjacent_resources_rejected(admin):
    a = await new_resource(admin)
    await new_resource(admin)  # in between
    c = await new_resource(admin)
    r = await new_session(admin, [a["code"], c["code"]])
    assert 400 <= r.status_code < 500, r.text


async def test_ac14_session_detail(admin, staff):
    res = await new_resource(admin)
    s = (await new_session(admin, [res["code"]], capacity=4, price=30000)).json()
    first = await w(
        staff,
        "POST",
        f"{FD}/sessions/{s['code']}/tickets",
        {"customer": temp("Vé Một", "0900111222")},
    )
    second = await w(
        staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp("Vé Hai")}
    )
    assert first.status_code == second.status_code == 201
    d = (await staff.get(f"{B}/sessions/{s['code']}")).json()
    assert d["taken"] == 2 and d["capacity"] == 4
    tickets = d["tickets"]
    assert [t["code"] for t in tickets][0] == second.json()["code"], "newest first"
    assert "0900111222" not in str(d)
    assert d["can"]["register"] is True
    assert d["can"]["delete"] is False  # staff


async def test_ac15_ticket_code_amount_and_capacity(admin, staff):
    res = await new_resource(admin)
    s = (await new_session(admin, [res["code"]], capacity=2, price=25000)).json()
    t1 = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
    t2 = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
    assert t1.json()["code"] == f"{s['code']}-V01" and t2.json()["code"] == f"{s['code']}-V02"
    assert t1.json()["amount"] == 25000 and t1.json()["payment_status"] == "unpaid"
    t3 = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
    assert_err(t3, "E-024")
    # a free event (price 0) still creates unpaid tickets that need collecting
    free = (await new_session(admin, [(await new_resource(admin))["code"]], price=0)).json()
    t = await w(staff, "POST", f"{FD}/sessions/{free['code']}/tickets", {"customer": temp()})
    assert t.status_code == 201 and t.json()["amount"] == 0


async def test_sec5_twenty_parallel_last_seat_one_success(admin, staff):
    res = await new_resource(admin)
    s = (await new_session(admin, [res["code"]], capacity=3)).json()
    for _ in range(2):
        assert (
            await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
        ).status_code == 201
    rs = await asyncio.gather(
        *[
            w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
            for _ in range(20)
        ]
    )
    assert len([r for r in rs if r.status_code == 201]) == 1, [r.status_code for r in rs]
    assert all(code_of(r) == "E-024" for r in rs if r.status_code != 201)
    assert (await staff.get(f"{B}/sessions/{s['code']}")).json()["taken"] == 3


async def test_ac15_same_customer_can_take_several_tickets(admin, staff):
    s = (await new_session(admin, [(await new_resource(admin))["code"]], capacity=3)).json()
    cust = temp(ph="0933445566")
    for _ in range(2):
        r = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": cust})
        assert r.status_code == 201, r.text


async def test_ac16_delete_session_rules(admin, staff):
    res = await new_resource(admin)
    empty = (await new_session(admin, [res["code"]])).json()
    got = (await admin.get(f"{B}/sessions/{empty['code']}")).json()
    denied = await w(staff, "DELETE", f"{B}/sessions/{empty['code']}", {"version": got["version"]})
    assert denied.status_code == 403
    ok = await w(admin, "DELETE", f"{B}/sessions/{empty['code']}", {"version": got["version"]})
    assert ok.status_code in (200, 204), ok.text
    codes = {b.get("code") for b in (await calendar(admin))["blocks"]}
    assert empty["code"] not in codes
    # the slot is free again, and the code is not reused
    again = (await new_session(admin, [res["code"]])).json()
    assert again["code"] != empty["code"]
    # a session with a ticket cannot be deleted
    t = await w(staff, "POST", f"{FD}/sessions/{again['code']}/tickets", {"customer": temp()})
    assert t.status_code == 201
    d = (await admin.get(f"{B}/sessions/{again['code']}")).json()
    blocked = await w(admin, "DELETE", f"{B}/sessions/{again['code']}", {"version": d["version"]})
    assert_err(blocked, "E-023")


# ---------------------------------------------------------------------------
# 5. Item info, collect, uncollectible (AC17-AC21)
# ---------------------------------------------------------------------------


async def test_ac17_item_detail_and_actions(admin, staff):
    res, bk = await new_booking(admin, customer=temp("QA Chi Tiết", "0977888999", "ghi chú đặt"))
    it = await item(staff, bk["code"])
    assert it["payment_status"] == "unpaid" and it["version"] >= 1
    assert {"collect"} <= set(it["actions"]), it["actions"]
    assert "0977888999" not in str(it)
    # staff vs admin created-by label (no email / username leak)
    assert "@" not in str(it)
    r = await w(
        staff,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": it["version"]},
    )
    assert r.status_code == 200, r.text
    done = await item(staff, bk["code"])
    assert not set(done["actions"]) & {"collect", "uncollectible"}


async def test_ac18_collect_cash(admin, staff):
    res, bk = await new_booking(admin)
    it = await item(admin, bk["code"])
    r = await w(
        staff,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": it["version"]},
    )
    assert r.status_code == 200, r.text
    done = await item(staff, bk["code"])
    assert done["payment_status"] == "paid"
    assert "Tài khoản tại máy" in str(done), "collected_by shows the role label"
    assert done["amount"] == it["amount"]


async def test_ac18_transfer_not_available_yet(admin):
    res, bk = await new_booking(admin)
    r = await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "transfer", "version": bk["version"]},
    )
    assert_err(r, "E-PAY-0")
    assert (await item(admin, bk["code"]))["payment_status"] == "unpaid"


@pytest.mark.parametrize("extra", [{"amount": 1}, {"method": "bitcoin"}, {"method": None}])
async def test_ac18_collect_rejects_bad_body(admin, extra):
    res, bk = await new_booking(admin)
    body = {"method": "cash", "version": bk["version"], **extra}
    r = await w(admin, "POST", f"{B}/items/{bk['code']}/collect", body)
    assert r.status_code == 422, r.text


async def test_ac19_uncollectible_flow(admin, staff):
    res, bk = await new_booking(admin)
    v = bk["version"]
    for reason in ("", "x" * 201):
        r = await w(
            staff, "POST", f"{B}/items/{bk['code']}/uncollectible", {"reason": reason, "version": v}
        )
        assert r.status_code == 422, (len(reason), r.text)
    ok = await w(
        staff,
        "POST",
        f"{B}/items/{bk['code']}/uncollectible",
        {"reason": "Khách bỏ về", "version": v},
    )
    assert ok.status_code == 200, ok.text
    it = await item(admin, bk["code"])
    assert it["payment_status"] == "uncollectible" and "Khách bỏ về" in str(it)
    # the frame is NOT freed
    assert_err(await book(staff, res["code"]), "E-003")
    # final state: no collect afterwards
    again = await w(
        staff,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": it["version"]},
    )
    assert_err(again, "E-012")


async def test_ac19_future_booking_cannot_be_marked(admin):
    h = now_local().hour
    if h >= 23:
        pytest.skip("no future frame left today")
    res = await new_resource(admin)
    bk = (await book(admin, res["code"], h + 1)).json()
    r = await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/uncollectible",
        {"reason": "sớm", "version": bk["version"]},
    )
    assert r.status_code == 422, r.text
    assert "uncollectible" not in (await item(admin, bk["code"]))["actions"]


async def test_ac19_ticket_can_be_marked_and_seat_not_released(admin, staff):
    res = await new_resource(admin)
    s = (await new_session(admin, [res["code"]], capacity=1)).json()
    t = (await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})).json()
    r = await w(
        staff,
        "POST",
        f"{B}/items/{t['code']}/uncollectible",
        {"reason": "QA", "version": t["version"]},
    )
    assert r.status_code == 200, r.text
    assert (await staff.get(f"{B}/sessions/{s['code']}")).json()["taken"] == 1
    again = await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})
    assert_err(again, "E-024")


async def test_ac20_stale_version_gets_e012(admin, staff):
    res, bk = await new_booking(admin)
    v = bk["version"]
    a = await w(admin, "POST", f"{B}/items/{bk['code']}/collect", {"method": "cash", "version": v})
    assert a.status_code == 200
    b = await w(staff, "POST", f"{B}/items/{bk['code']}/collect", {"method": "cash", "version": v})
    assert_err(b, "E-012")
    c = await w(
        staff, "POST", f"{B}/items/{bk['code']}/uncollectible", {"reason": "QA", "version": v}
    )
    assert_err(c, "E-012")
    assert (await item(admin, bk["code"]))["payment_status"] == "paid"


async def test_sec5_two_parallel_collects_one_paid(admin, staff):
    res, bk = await new_booking(admin)
    rs = await asyncio.gather(
        w(
            admin,
            "POST",
            f"{B}/items/{bk['code']}/collect",
            {"method": "cash", "version": bk["version"]},
        ),
        w(
            staff,
            "POST",
            f"{B}/items/{bk['code']}/collect",
            {"method": "cash", "version": bk["version"]},
        ),
    )
    ok = [r for r in rs if r.status_code == 200]
    assert len(ok) == 1, [r.status_code for r in rs]
    assert_err(next(r for r in rs if r.status_code != 200), "E-012")
    assert (
        len(await audit_rows("action='payment.collect' AND entity_code=:c", {"c": bk["code"]})) == 1
    )


async def test_ac21_replay_same_key_one_write_no_e012(admin):
    res, bk = await new_booking(admin)
    k = key()
    body = {"method": "cash", "version": bk["version"]}
    r1 = await w(admin, "POST", f"{B}/items/{bk['code']}/collect", body, k=k)
    r2 = await w(admin, "POST", f"{B}/items/{bk['code']}/collect", body, k=k)
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert r1.json() == r2.json()
    assert (
        len(await audit_rows("action='payment.collect' AND entity_code=:c", {"c": bk["code"]})) == 1
    )


# ---------------------------------------------------------------------------
# 6. Transaction history (AC22-AC23)
# ---------------------------------------------------------------------------


async def test_ac22_defaults_cards_and_paging(admin):
    for _ in range(3):
        await new_booking(admin)
    r = await admin.get(f"{B}/transactions")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["page"] == 1 and len(d["rows"]) <= 8
    for k in ("paid", "unpaid", "uncollectible"):
        assert {"amount", "count"} <= set(d["cards"][k])
    assert d["cards"]["unpaid"]["count"] >= 3
    total = sum(d["cards"][k]["count"] for k in d["cards"])
    assert d["total"] == total, "cards follow the same filter as rows"
    if d["total"] > 8:
        p2 = (await admin.get(f"{B}/transactions", params={"page": 2})).json()
        assert p2["page"] == 2 and {x["code"] for x in p2["rows"]}.isdisjoint(
            {x["code"] for x in d["rows"]}
        )


async def test_ac22_filters(admin):
    res, bk = await new_booking(admin, customer=temp("QA Lọc Tên", "0966123456"))
    await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": bk["version"]},
    )
    base = {"from": today().isoformat(), "to": today().isoformat()}
    by_code = (
        await admin.get(f"{B}/transactions", params={**base, "q": bk["code"].lower()})
    ).json()
    assert [r["code"] for r in by_code["rows"]] == [bk["code"]]
    by_phone = (await admin.get(f"{B}/transactions", params={**base, "q": "0966 123.456"})).json()
    assert bk["code"] in [r["code"] for r in by_phone["rows"]]
    by_name = (await admin.get(f"{B}/transactions", params={**base, "q": "lọc tên"})).json()
    assert bk["code"] in [r["code"] for r in by_name["rows"]]
    paid = (
        await admin.get(f"{B}/transactions", params={**base, "status": "paid", "q": bk["code"]})
    ).json()
    assert paid["cards"]["paid"]["count"] == 1
    cash = (
        await admin.get(f"{B}/transactions", params={**base, "method": "cash", "q": bk["code"]})
    ).json()
    assert cash["total"] == 1
    unp = (
        await admin.get(f"{B}/transactions", params={**base, "status": "unpaid", "q": bk["code"]})
    ).json()
    assert unp["total"] == 0
    by_res = (await admin.get(f"{B}/transactions", params={**base, "resource": res["code"]})).json()
    assert [r["code"] for r in by_res["rows"]] == [bk["code"]]


async def test_ac22_range_errors(admin):
    t = today()
    r = await admin.get(
        f"{B}/transactions",
        params={"from": t.isoformat(), "to": (t - timedelta(days=1)).isoformat()},
    )
    assert_err(r, "E-016")
    r = await admin.get(
        f"{B}/transactions",
        params={"from": (t - timedelta(days=93)).isoformat(), "to": t.isoformat()},
    )
    assert_err(r, "E-020")
    ok = await admin.get(
        f"{B}/transactions",
        params={"from": (t - timedelta(days=91)).isoformat(), "to": t.isoformat()},
    )
    assert ok.status_code == 200, "92 days inclusive is the maximum"


async def test_ac22_revenue_counts_play_date_and_paid_only(admin):
    before = (
        await admin.get(
            f"{B}/transactions", params={"from": today().isoformat(), "to": today().isoformat()}
        )
    ).json()
    res, bk = await new_booking(admin)
    mid = (
        await admin.get(
            f"{B}/transactions", params={"from": today().isoformat(), "to": today().isoformat()}
        )
    ).json()
    assert mid["cards"]["paid"]["amount"] == before["cards"]["paid"]["amount"]
    assert mid["cards"]["unpaid"]["amount"] == before["cards"]["unpaid"]["amount"] + bk["amount"]
    await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": bk["version"]},
    )
    after = (
        await admin.get(
            f"{B}/transactions", params={"from": today().isoformat(), "to": today().isoformat()}
        )
    ).json()
    assert after["cards"]["paid"]["amount"] == before["cards"]["paid"]["amount"] + bk["amount"]


async def test_ac23_transactions_admin_only(staff, customer, anon):
    assert (await staff.get(f"{B}/transactions")).status_code == 403
    assert (await customer.get(f"{B}/transactions")).status_code == 403
    assert (await anon.get(f"{B}/transactions")).status_code == 401


# ---------------------------------------------------------------------------
# 7. Audit (AC24, SEC9)
# ---------------------------------------------------------------------------


async def test_ac24_exactly_one_audit_row_per_write_and_none_for_blocked(admin, staff):
    res = await new_resource(admin)
    ph = phone()
    c0 = len(await audit_rows("action='booking.counter.create'"))
    m0 = len(await audit_rows("action='member.temp.create'"))
    r = await book(staff, res["code"], customer=temp("QA Audit", ph))
    assert r.status_code == 201
    code = r.json()["code"]
    assert len(await audit_rows("action='booking.counter.create'")) == c0 + 1
    assert len(await audit_rows("action='member.temp.create'")) == m0 + 1
    # blocked (conflict) -> no row
    dup = await book(staff, res["code"])
    assert_err(dup, "E-003")
    assert len(await audit_rows("action='booking.counter.create'")) == c0 + 1
    # collect / uncollectible rows carry method / reason but no phone
    await w(
        staff,
        "POST",
        f"{B}/items/{code}/collect",
        {"method": "cash", "version": r.json()["version"]},
    )
    rows = await audit_rows("action='payment.collect' AND entity_code=:c", {"c": code})
    assert len(rows) == 1 and "cash" in str(rows[0]["detail"]) and ph not in str(dict(rows[0]))
    # session + ticket + delete
    s = (await new_session(admin, [(await new_resource(admin))["code"]])).json()
    assert (
        len(await audit_rows("action='session.create' AND entity_code=:c", {"c": s["code"]})) == 1
    )
    t = (await w(staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp()})).json()
    assert len(await audit_rows("action='ticket.create' AND entity_code=:c", {"c": t["code"]})) == 1
    # actor label is the role label, not an email
    row = (await audit_rows("action='booking.counter.create' AND entity_code=:c", {"c": code}))[0]
    assert row["actor_label"] == "Tài khoản tại máy"


async def test_sec9_audit_log_is_append_only():
    rows = await audit_rows()
    if not rows:
        pytest.skip("no audit rows yet")
    async with SessionLocal() as s:
        with pytest.raises(DBAPIError):
            await s.execute(
                text("UPDATE audit_log SET action='x' WHERE id=:i"), {"i": rows[0]["id"]}
            )
            await s.commit()
    async with SessionLocal() as s:
        with pytest.raises(DBAPIError):
            await s.execute(text("DELETE FROM audit_log WHERE id=:i"), {"i": rows[0]["id"]})
            await s.commit()


# ---------------------------------------------------------------------------
# 8. Security (SEC1-SEC8)
# ---------------------------------------------------------------------------

ADMIN_ONLY, ADMIN_STAFF = "admin", "admin+staff"


def _matrix():
    code = FAKE_CODE
    d = today().isoformat()
    b = {"resource_code": "ZZ999", "date": d, "start_hour": 10, "end_hour": 11, "customer": temp()}
    sess = {
        "resource_codes": ["ZZ999"],
        "date": d,
        "start_hour": 10,
        "end_hour": 11,
        "name": "x",
        "capacity": 1,
        "ticket_price": 0,
    }
    return [
        ("GET", f"{B}/calendar?date={d}", None, ADMIN_STAFF),
        ("GET", f"{B}/search?code={code}", None, ADMIN_STAFF),
        ("GET", f"{MEMBERS}/search?q=HV", None, ADMIN_STAFF),
        ("POST", f"{FD}/bookings", b, ADMIN_STAFF),
        ("POST", f"{B}/sessions", sess, ADMIN_ONLY),
        ("GET", f"{B}/sessions/{code}", None, ADMIN_STAFF),
        ("DELETE", f"{B}/sessions/{code}", {"version": 1}, ADMIN_ONLY),
        ("POST", f"{FD}/sessions/{code}/tickets", {"customer": temp()}, ADMIN_STAFF),
        ("GET", f"{B}/items/{code}", None, ADMIN_STAFF),
        ("POST", f"{B}/items/{code}/collect", {"method": "cash", "version": 1}, ADMIN_STAFF),
        ("POST", f"{B}/items/{code}/uncollectible", {"reason": "x", "version": 1}, ADMIN_STAFF),
        ("GET", f"{B}/transactions", None, ADMIN_ONLY),
    ]


@pytest.mark.parametrize("idx", range(12))
async def test_sec1_permission_matrix(idx, anon, customer, staff, admin):
    method, path, body, allowed = _matrix()[idx]
    expect = {
        "anon": False,
        "customer": False,
        "staff": allowed == ADMIN_STAFF,
        "admin": True,
    }
    for name, client in (
        ("anon", anon),
        ("customer", customer),
        ("staff", staff),
        ("admin", admin),
    ):
        r = await w(client, method, path, body) if method != "GET" else await client.get(path)
        if expect[name]:
            assert r.status_code not in (401, 403), (name, method, path, r.status_code, r.text)
        else:
            want = 401 if name == "anon" else 403
            assert r.status_code == want, (name, method, path, r.status_code, r.text)
            assert code_of(r) == ("E-AUTH-1" if name == "anon" else "E-AUTH-2")


@pytest.mark.parametrize(
    "field",
    ["amount", "price", "code", "payment_status", "customer_name", "created_by", "tenant_id", "id"],
)
async def test_sec2_forbidden_body_fields(staff, admin, field):
    res = await new_resource(admin)
    body = {
        **booking_body(res["code"], usable_hour()),
        field: "BK-20260101-001" if field == "code" else 1,
    }
    r = await w(staff, "POST", f"{FD}/bookings", body)
    assert r.status_code == 422, (field, r.text)
    cal = await calendar(staff)
    assert not [b for b in cal["blocks"] if b.get("resource_code") == res["code"]]


async def test_sec2_forbidden_fields_on_other_writes(admin):
    res, bk = await new_booking(admin)
    r = await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/collect",
        {"method": "cash", "version": bk["version"], "payment_status": "paid", "amount": 1},
    )
    assert r.status_code == 422
    r = await new_session(admin, [(await new_resource(admin))["code"]])
    assert r.status_code == 201
    r = await w(
        admin,
        "POST",
        f"{B}/sessions",
        {
            "resource_codes": ["x"],
            "code": "BK-1",
            "name": "n",
            "date": today().isoformat(),
            "start_hour": 1,
            "end_hour": 2,
            "capacity": 1,
            "ticket_price": 0,
        },
    )
    assert r.status_code == 422


async def test_sec3_evil_origin_blocked_on_all_writes(admin):
    res, bk = await new_booking(admin)
    login = await admin.post(
        f"{API}/auth/login",
        json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    cookies = dict(admin.cookies)
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": EVIL}, cookies=cookies
    ) as evil:
        for method, path, body, _ in _matrix():
            if method == "GET":
                continue
            r = await w(evil, method, path, body)
            assert r.status_code == 403 and code_of(r) == "E-SEC-1", (method, path, r.status_code)
        r = await w(
            evil,
            "POST",
            f"{B}/items/{bk['code']}/collect",
            {"method": "cash", "version": bk["version"]},
        )
        assert r.status_code == 403
    assert (await item(admin, bk["code"]))["payment_status"] == "unpaid"


async def test_sec4_no_full_phone_or_internal_ids_in_responses(admin, staff):
    ph = "0944556677"
    res, bk = await new_booking(admin, customer=temp("QA Riêng Tư", ph))
    s = (await new_session(admin, [(await new_resource(admin))["code"]])).json()
    t = (
        await w(
            staff, "POST", f"{FD}/sessions/{s['code']}/tickets", {"customer": temp("Vé Riêng", ph)}
        )
    ).json()
    day = today().isoformat()
    responses = [
        bk,
        t,
        s,
        (await staff.get(f"{B}/calendar", params={"date": day})).json(),
        (await staff.get(f"{B}/items/{bk['code']}")).json(),
        (await staff.get(f"{B}/items/{t['code']}")).json(),
        (await staff.get(f"{B}/sessions/{s['code']}")).json(),
        (await admin.get(f"{B}/transactions", params={"from": day, "to": day})).json(),
        (await staff.get(f"{MEMBERS}/search", params={"q": "HV"})).json(),
        (await staff.get(f"{B}/search", params={"code": bk["code"]})).json(),
    ]
    phones = await all_phones()
    for data in responses:
        blob = str(data)
        for p in phones:
            assert p not in blob, f"full phone {p} leaked"
        for k, v in walk(data):
            assert k not in (
                "customer_ref",
                "customer_id",
                "created_by_id",
                "marked_by_id",
                "tenant_id",
            ), k
            if k == "id":
                assert not isinstance(v, int), "numeric internal id leaked"
    # masked phone format
    assert re.search(r"0944 xxx 677", str(responses[4]))
    assert "@" not in str(responses[4])


async def test_sec6_idempotency_replay_conflict_missing(staff, admin):
    res = await new_resource(admin)
    h = usable_hour()
    body = booking_body(res["code"], h)
    k = key()
    first = await w(staff, "POST", f"{FD}/bookings", body, k=k)
    replay = await w(staff, "POST", f"{FD}/bookings", body, k=k)
    assert first.status_code == 201 and replay.status_code == 201
    assert replay.json() == first.json()
    changed = await w(
        staff, "POST", f"{FD}/bookings", {**body, "end_hour": h + 1, "customer": temp()}, k=k
    )
    assert changed.status_code == 422, changed.text
    missing = await w(staff, "POST", f"{FD}/bookings", booking_body(res["code"], h), k=None)
    assert missing.status_code == 400, missing.text
    n = len(
        await audit_rows(
            "action='booking.counter.create' AND entity_code=:c", {"c": first.json()["code"]}
        )
    )
    assert n == 1


async def test_sec6_idempotency_on_session_and_ticket(admin, staff):
    res = await new_resource(admin)
    k = key()
    h = usable_hour()
    body = {
        "resource_codes": [res["code"]],
        "date": today().isoformat(),
        "start_hour": h,
        "end_hour": h + 1,
        "name": "QA idem",
        "capacity": 2,
        "ticket_price": 0,
    }
    a = await w(admin, "POST", f"{B}/sessions", body, k=k)
    b = await w(admin, "POST", f"{B}/sessions", body, k=k)
    assert a.status_code == b.status_code == 201 and a.json()["code"] == b.json()["code"]
    kt = key()
    cust = {"customer": temp()}
    t1 = await w(staff, "POST", f"{FD}/sessions/{a.json()['code']}/tickets", cust, k=kt)
    t2 = await w(staff, "POST", f"{FD}/sessions/{a.json()['code']}/tickets", cust, k=kt)
    assert t1.status_code == t2.status_code == 201 and t1.json()["code"] == t2.json()["code"]
    assert (await staff.get(f"{B}/sessions/{a.json()['code']}")).json()["taken"] == 1


async def test_sec7_xss_strings_stored_verbatim(admin, staff):
    res = await new_resource(admin)
    r = await book(staff, res["code"], customer=temp(f"A{XSS}", note=XSS))
    assert r.status_code == 201, r.text
    it = await item(staff, r.json()["code"])
    assert f"A{XSS}" in str(it) and XSS in str(it)
    s = await new_session(admin, [(await new_resource(admin))["code"]], name=XSS)
    assert (
        s.status_code == 201
        and (await staff.get(f"{B}/sessions/{s.json()['code']}")).json()["name"] == XSS
    )
    res2, bk = await new_booking(admin)
    mark = await w(
        admin,
        "POST",
        f"{B}/items/{bk['code']}/uncollectible",
        {"reason": XSS, "version": bk["version"]},
    )
    assert mark.status_code == 200
    assert XSS in str(await item(admin, bk["code"]))
    # responses are JSON, never HTML
    resp = await staff.get(f"{B}/items/{bk['code']}")
    assert resp.headers["content-type"].startswith("application/json")


async def test_sec8_search_rate_limit(staff):
    statuses = [
        (await staff.get(f"{B}/search", params={"code": FAKE_CODE})).status_code for _ in range(61)
    ]
    assert statuses[:60].count(429) == 0, "first 60 must pass"
    assert statuses[60] == 429
    r = await staff.get(f"{B}/search", params={"code": FAKE_CODE})
    assert code_of(r) == "E-SEC-5"


async def test_sec8_members_search_rate_limit(staff):
    statuses = [
        (await staff.get(f"{MEMBERS}/search", params={"q": "HV"})).status_code for _ in range(61)
    ]
    assert statuses[:60].count(429) == 0
    assert statuses[60] == 429


# ---------------------------------------------------------------------------
# 9. DB-level guarantees (BR-010: constraint, not application code)
# ---------------------------------------------------------------------------


async def test_db_exclusion_constraint_is_the_guard():
    async with SessionLocal() as s:
        row = (
            await s.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='booking' AND t.relname='allocation' AND c.contype='x'"
                )
            )
        ).first()
    assert row and "gist" in row[0].lower() and "&&" in row[0] and "active" in row[0].lower()


async def test_payment_state_machine_is_enforced_in_db():
    async with SessionLocal() as s:
        defs = (
            await s.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid=c.conrelid "
                    "JOIN pg_namespace n ON n.oid=t.relnamespace "
                    "WHERE n.nspname='booking' AND t.relname='booking' AND c.contype='c'"
                )
            )
        ).all()
    blob = " ".join(d[0] for d in defs)
    assert "paid" in blob and "uncollectible" in blob and "payment_method" in blob

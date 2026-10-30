"""QA acceptance tests for T-008 (web khach: online checkout, SePay webhook, lookup, finance queue).

Source of truth: board/tasks/T-008-web-khach-dat-online.md (AC1-AC32, SEC1-SEC10) and ADR-001/007.
Written from the spec BEFORE the BE handoff: section 1 holds every assumption about names/shapes
so it can be adjusted in one place. UI-only criteria (AC15-17 countdown/polling rendering, AC28-30,
SEC9 headers on /thanh-toan/*) are verified by hand / on the dev link (see qa/T-008-report.md).

ASSUMED CONTRACT (beyond the spec's API section):
  * settings: SEPAY_BANK_CODE, SEPAY_BANK_NAME, SEPAY_ACCOUNT_NUMBER, SEPAY_ACCOUNT_NAME,
    SEPAY_WEBHOOK_SECRET, SEPAY_TIMESTAMP_TOLERANCE_SECONDS, ONLINE_HOLD_MINUTES,
    ONLINE_HOLD_GRACE_SECONDS, PAYMENTS_SIMULATE
  * webhook: SePay JSON ({id, gateway, transactionDate "YYYY-MM-DD HH:MM:SS" Vietnam time,
    accountNumber, code, content, transferType in|out, transferAmount, referenceCode, ...}),
    headers X-SePay-Signature: sha256=<hex HMAC(secret, f"{ts}.{raw_body}")> and X-SePay-Timestamp
  * webhook answers: 200 {"success": true}; bad signature 401; no secret 503; bad body 400
  * tables: booking.checkout(token_hash, pay_ref, status, expires_at, paid_amount),
    booking.hold(checkout_id, expires_at, status),
    payments.bank_transaction(provider_txn_id, outcome)
  * simulate: POST /payments/dev/simulate {pay_ref, amount} -> same response shape as the
    transaction it created (outcome, refund_amount, ...)
  * the members handler for ``booking.online_paid`` is driven by the outbox publisher; tests call
    ``outbox.publish_pending`` when it exists
Per-IP rate limits (6 checkouts / 10 min, 10 lookups / min) are reset before every test by the
autouse fixture in conftest, and no test except the rate-limit tests sends more than 6 checkouts.
Response-time equality for lookups (SEC2) is checked by hand: wall-clock asserts would be flaky.
Every test uses a fresh court (open 00:00-24:00) and its own phone number, so tests never collide.
"""

import asyncio
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.api import normalize_phone
from tests.conftest import API, ORIGIN, idem
from tests.helpers_web import phone_token

W = f"{API}/web/booking"
PAY = f"{API}/payments"
BK = f"{API}/booking"
FD = f"{API}/front-desk"
SECRET = "qa-webhook-secret-0123456789abcdef"
ACCOUNT = "0123456789"
FAR = 20  # days ahead: never "today", so no wall-clock flakiness


# ---------------------------------------------------------------------------
# 1. Contract helpers
# ---------------------------------------------------------------------------


def _set(name: str, value) -> None:
    object.__setattr__(settings, name, value)


@pytest.fixture
def sepay():
    """Online booking switched on with a fake bank account and a known webhook secret."""
    names = {
        "SEPAY_BANK_CODE": "VCB",
        "SEPAY_BANK_NAME": "Vietcombank",
        "SEPAY_ACCOUNT_NUMBER": ACCOUNT,
        "SEPAY_ACCOUNT_NAME": "SAN CAU LONG QA",
        "SEPAY_WEBHOOK_SECRET": SECRET,
        "SEPAY_TIMESTAMP_TOLERANCE_SECONDS": 0,
        "ONLINE_HOLD_MINUTES": 5,
        "ONLINE_HOLD_GRACE_SECONDS": 60,
        "PAYMENTS_SIMULATE": True,
    }
    saved = {k: getattr(settings, k, None) for k in names}
    for k, v in names.items():
        _set(k, v)
    yield
    for k, v in saved.items():
        _set(k, v)


def day(offset: int = FAR) -> date:
    return date.today() + timedelta(days=offset)


def phone() -> str:
    return "09" + str(uuid.uuid4().int)[:8]


def code_of(resp) -> str | None:
    try:
        detail = resp.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return None
    return detail.get("code") if isinstance(detail, dict) else None


def err(resp, status: int, code: str) -> None:
    assert resp.status_code == status, (status, code, resp.status_code, resp.text)
    assert code_of(resp) == code, (code, resp.text)


async def court(admin, **kw) -> dict:
    body = {
        "name": f"QA web {uuid.uuid4().hex[:6]}",
        "resource_type_code": "thuong",
        "open_time": "00:00",
        "close_time": "24:00",
        "peak_bands": [],
        **kw,
    }
    r = await admin.post(f"{BK}/resources", json=body, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


def slots(code: str, *hours: int) -> list[dict]:
    return [{"resource_code": code, "start_hour": h} for h in hours]


async def with_token(web, body: dict) -> dict:
    """T-013 AC26: đặt online cần ``phone_token`` của đúng SĐT (OTP chế độ thử)."""
    if "phone_token" not in body:
        body["phone_token"] = await phone_token(web, normalize_phone(body["phone"]), required=False)
    return body


async def checkout(web, sl, *, d: date | None = None, name="QA Khách Web", ph=None, note=None, **x):
    body = {
        "date": (d or day()).isoformat(),
        "slots": sl,
        "full_name": name,
        "phone": ph or phone(),
        **x,
    }
    if note is not None:
        body["note"] = note
    return await web.post(f"{W}/checkouts", json=await with_token(web, body), headers=idem())


async def make_checkout(web, sl, **kw) -> dict:
    r = await checkout(web, sl, **kw)
    assert r.status_code == 201, r.text
    return r.json()


async def calendar(web, d: date | None = None):
    return await web.get(f"{W}/calendar", params={"date": (d or day()).isoformat()})


def state_of(cal: dict, code: str, hour: int) -> dict | None:
    for res in cal["resources"]:
        if res["code"] == code:
            return next((s for s in res["slots"] if s["start_hour"] == hour), None)
    return None


def sign(body: bytes, secret: str = SECRET, ts: int | None = None) -> dict[str, str]:
    stamp = str(ts if ts is not None else int(time.time()))
    mac = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return {
        "X-SePay-Signature": f"sha256={mac}",
        "X-SePay-Timestamp": stamp,
        "Content-Type": "application/json",
    }


def now_vn() -> str:
    return datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S")


def payload(pay_ref: str | None, amount: int, *, txn_id: int | None = None, **kw) -> dict:
    return {
        "id": txn_id if txn_id is not None else uuid.uuid4().int % 10**12,
        "gateway": "Vietcombank",
        "transactionDate": now_vn(),
        "accountNumber": ACCOUNT,
        "code": pay_ref,
        "content": f"CK {pay_ref}" if pay_ref else "chuyen tien",
        "transferType": "in",
        "transferAmount": amount,
        "accumulated": 0,
        "referenceCode": "FT" + uuid.uuid4().hex[:10],
        "description": "",
        **kw,
    }


async def webhook(web, body: dict | bytes, *, headers: dict | None = None, **kw):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return await web.post(f"{PAY}/sepay/webhook", content=raw, headers=headers or sign(raw), **kw)


async def pay(web, co: dict, amount: int | None = None, **kw):
    """Send a correctly signed incoming transfer for the checkout."""
    return await webhook(
        web, payload(co["pay_ref"], co["amount"] if amount is None else amount, **kw)
    )


async def get_checkout(web, token: str) -> dict:
    r = await web.get(f"{W}/checkouts/{token}")
    assert r.status_code == 200, r.text
    return r.json()


async def sql(query: str, **params):
    async with SessionLocal() as s:
        res = await s.execute(text(query), params)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


async def run_expiry() -> None:
    from app.modules.booking_engine import api as engine_api

    async with SessionLocal() as s:
        await engine_api.expire_holds(s)
        await s.commit()


async def publish_outbox() -> None:
    from app.modules.booking_engine import api as engine_api

    for _ in range(20):  # each round handles up to 100 events; stop when nothing is left
        if await engine_api.publish_outbox(SessionLocal) == 0:
            return


async def age_checkout(pay_ref: str, seconds: int) -> None:
    """Move the checkout (and its holds) `seconds` into the past, as if time had passed."""
    await sql(
        "UPDATE booking.checkout SET expires_at = expires_at - make_interval(secs => :s) "
        "WHERE pay_ref = :p",
        s=seconds,
        p=pay_ref,
    )
    await sql(
        "UPDATE booking.hold SET expires_at = expires_at - make_interval(secs => :s) "
        "WHERE checkout_id = (SELECT id FROM booking.checkout WHERE pay_ref = :p)",
        s=seconds,
        p=pay_ref,
    )


# ---------------------------------------------------------------------------
# 2. Public calendar (AC1, AC2, AC5, SEC1)
# ---------------------------------------------------------------------------


async def test_ac1_calendar_is_public_and_shaped(anon, admin, sepay):
    c = await court(admin)
    r = await calendar(anon)
    assert r.status_code == 200, r.text
    assert "no-store" in r.headers.get("cache-control", "")
    d = r.json()
    for k in ("date", "server_now", "online_enabled", "hold_minutes", "columns", "resources"):
        assert k in d, k
    assert d["online_enabled"] is True and d["hold_minutes"] == 5
    s = state_of(d, c["code"], 10)
    assert s and s["state"] == "free" and s["price"] > 0 and s["band"] in ("offpeak", "peak")


async def test_ac1_past_date_rejected_and_far_future_allowed(anon, sepay):
    r = await calendar(anon, date.today() - timedelta(days=1))
    err(r, 422, "E-WEB-2")
    assert (await calendar(anon, date.today() + timedelta(days=900))).status_code == 200
    assert (await anon.get(f"{W}/calendar", params={"date": "not-a-date"})).status_code == 422


async def test_ac1_only_active_resources_listed(anon, admin, sepay):
    c = await court(admin)
    listing = (await admin.get(f"{BK}/resources")).json()
    items = (
        listing
        if isinstance(listing, list)
        else next(v for v in listing.values() if isinstance(v, list))
    )
    cur = next(x for x in items if x["code"] == c["code"])
    off = await admin.patch(
        f"{BK}/resources/{c['code']}",
        json={"version": cur["version"], "is_active": False},
        headers=idem(),
    )
    assert off.status_code == 200, off.text
    cal = (await calendar(anon)).json()
    assert c["code"] not in {r["code"] for r in cal["resources"]}


async def test_ac2_slot_states_free_booked_event_closed(anon, admin, sepay):
    c = await court(admin, open_time="06:00", close_time="22:00")
    co = await make_checkout(anon, slots(c["code"], 9))
    cal = (await calendar(anon)).json()
    assert state_of(cal, c["code"], 9)["state"] == "booked", "a held slot looks booked to others"
    assert state_of(cal, c["code"], 5)["state"] == "closed", "before opening -> grey"
    assert state_of(cal, c["code"], 22) is None or state_of(cal, c["code"], 22)["state"] == "closed"
    assert state_of(cal, c["code"], 12)["state"] == "free"
    # an event (admin) shows as event with taken/capacity and is not bookable
    ev = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [c["code"]],
            "date": day().isoformat(),
            "start_hour": 14,
            "end_hour": 15,
            "name": "QA sự kiện web",
            "capacity": 8,
            "ticket_price": 1000,
        },
        headers=idem(),
    )
    assert ev.status_code == 201, ev.text
    s = state_of((await calendar(anon)).json(), c["code"], 14)
    assert s["state"] == "event" and s["capacity"] == 8 and s["taken"] == 0
    blocked = await checkout(anon, slots(c["code"], 14))  # the event holds the slot: refused
    assert blocked.status_code in (409, 422), blocked.text
    assert code_of(blocked) in ("E-WEB-2", "E-WEB-3"), blocked.text
    assert co["status"] == "pending"


async def test_sec1_calendar_never_leaks_other_people(anon, admin, sepay):
    c = await court(admin)
    ph = "0977123456"
    co = await make_checkout(
        anon, slots(c["code"], 9), name="QA Bí Mật Nguyễn", ph=ph, note="ghi chú riêng"
    )
    bk = await admin.post(
        f"{FD}/bookings",
        json={
            "resource_code": c["code"],
            "date": day().isoformat(),
            "start_hour": 11,
            "end_hour": 12,
            "customer": {"temp": {"full_name": "QA Quầy Riêng", "phone": "0966555444"}},
        },
        headers=idem(),
    )
    assert bk.status_code in (201, 422, 403), bk.text  # counter is today-only; failure is fine
    blob = (await calendar(anon)).text
    for needle in (
        "Bí Mật",
        ph,
        "ghi chú riêng",
        co["items"][0]["code"],
        co["pay_ref"],
        "Quầy Riêng",
    ):
        assert needle not in blob, needle


async def test_ac5_online_disabled_when_not_configured(anon, admin, sepay):
    for k in ("SEPAY_ACCOUNT_NUMBER", "SEPAY_WEBHOOK_SECRET"):
        _set(k, "")
    c = await court(admin)
    cal = (await calendar(anon)).json()
    assert cal["online_enabled"] is False
    assert state_of(cal, c["code"], 10)["state"] == "free", "calendar still readable"
    err(await checkout(anon, slots(c["code"], 10)), 503, "E-WEB-5")


# ---------------------------------------------------------------------------
# 3. Checkout creation (AC3, AC7-AC13, SEC4, SEC6, SEC10)
# ---------------------------------------------------------------------------


async def test_ac10_checkout_shape_codes_amount_and_expiry(anon, admin, sepay):
    c = await court(admin)
    cal = (await calendar(anon)).json()
    price = state_of(cal, c["code"], 19)["price"] + state_of(cal, c["code"], 20)["price"]
    co = await make_checkout(anon, slots(c["code"], 19, 20))
    assert len(co["token"]) == 43 and re.fullmatch(r"[A-Za-z0-9_-]{43}", co["token"])
    assert co["status"] == "pending" and co["paid_amount"] == 0 and co["paid_at"] is None
    assert co["amount"] == price, "server total = sum of calendar prices"
    assert re.fullmatch(r"BK\d{11}", co["pay_ref"])
    assert len(co["items"]) == 1, "two adjacent hours of one court form ONE booking"
    it = co["items"][0]
    assert re.fullmatch(r"BK-\d{8}-\d{3}", co["order_code"]), (
        "T-019 AC1: one order code per checkout"
    )
    assert it["code"] == f"{co['order_code']}-01" and it["hours"] == 2, "child code = order-01"
    assert it["start_time"] == "19:00" and it["end_time"] == "21:00" and it["amount"] == price
    assert co["pay_ref"] == co["order_code"].replace("-", ""), "T-019 AC2: pay_ref = order code"
    exp = datetime.fromisoformat(co["expires_at"])
    now = datetime.fromisoformat(co["server_now"])
    assert 4.5 * 60 <= (exp - now).total_seconds() <= 5 * 60 + 5, "hold = 5 minutes"
    assert co["bank"]["account_number"] == ACCOUNT
    qr = co["bank"]["qr_url"]
    assert qr.startswith("https://qr.sepay.vn/img?") and f"amount={price}" in qr
    assert co["pay_ref"] in qr and "token" not in qr and co["token"] not in qr
    assert co["customer"]["phone_masked"].count("x") >= 3 and "full_name" in co["customer"]


async def test_ac10_amount_matches_counter_price_function(anon, admin, sepay):
    c = await court(admin, peak_bands=[["17:00", "21:00"]])
    cal = (await calendar(anon)).json()
    q = await admin.post(
        f"{BK}/quote",
        json={
            "resource_code": c["code"],
            "date": day().isoformat(),
            "start_hour": 17,
            "end_hour": 19,
        },
    )
    assert q.status_code == 200, q.text
    total = q.json().get("total_amount", q.json().get("total"))
    co = await make_checkout(anon, slots(c["code"], 17, 18))
    assert co["amount"] == total
    assert state_of(cal, c["code"], 17)["band"] == "peak"


async def test_ac10_non_adjacent_hours_and_multi_court(anon, admin, sepay):
    a, b = await court(admin), await court(admin)
    co = await make_checkout(anon, slots(a["code"], 8, 9, 12) + slots(b["code"], 8))
    assert len(co["items"]) == 3, "one booking per run of adjacent hours per court"
    codes = [i["code"] for i in co["items"]]
    assert len(set(codes)) == 3 and codes == sorted(codes)
    assert codes == [f"{co['order_code']}-{n:02d}" for n in (1, 2, 3)], "children numbered -01..-03"
    assert co["amount"] == sum(i["amount"] for i in co["items"])
    assert co["pay_ref"] == co["order_code"].replace("-", "")


async def test_ac3_slot_limits(anon, admin, sepay):
    c = await court(admin)
    err(await checkout(anon, slots(c["code"], *range(0, 17))), 422, "E-WEB-1")
    err(await checkout(anon, []), 422, "E-WEB-1")
    ok = await checkout(anon, slots(c["code"], *range(0, 16)))
    assert ok.status_code == 201, ok.text  # exactly 16 is allowed
    assert ok.json()["amount"] > 0


@pytest.mark.parametrize(
    ("patch", "status"),
    [
        ({"full_name": ""}, 422),
        ({"full_name": "   "}, 422),
        ({"full_name": "x" * 101}, 422),
        ({"phone": "123"}, 422),
        ({"phone": "09123456789"}, 422),
        ({"phone": "abcdefghij"}, 422),
        ({"phone": ""}, 422),
        ({"note": "n" * 201}, 422),
        ({"amount": 1}, 422),
        ({"price": 1}, 422),
        ({"total": 1}, 422),
        ({"status": "paid"}, 422),
        ({"pay_ref": "BK00000000001"}, 422),
    ],
)
async def test_ac7_sec4_validation_and_forbidden_fields(anon, admin, sepay, patch, status):
    c = await court(admin)
    body = {
        "date": day().isoformat(),
        "slots": slots(c["code"], 10),
        "full_name": "QA Hợp Lệ",
        "phone": phone(),
        **patch,
    }
    r = await anon.post(f"{W}/checkouts", json=await with_token(anon, body), headers=idem())
    assert r.status_code == status, r.text
    assert (state_of((await calendar(anon)).json(), c["code"], 10) or {}).get("state") == "free"


@pytest.mark.parametrize("style", ["spaces", "dots", "dashes", "plus84"])
async def test_ac7_phone_is_normalised(anon, admin, sepay, style):
    c = await court(admin)
    n = str(uuid.uuid4().int)[:8]  # a fresh number per case: one pending checkout per phone
    canonical = f"09{n}"
    raw = {
        "spaces": f"09{n[:2]} {n[2:5]} {n[5:]}",
        "dots": f"09{n[:2]}.{n[2:5]}.{n[5:]}",
        "dashes": f"09{n[:2]}-{n[2:5]}-{n[5:]}",
        "plus84": f"+849{n}",
    }[style]
    co = await make_checkout(anon, slots(c["code"], 10), ph=raw)
    masked = co["customer"]["phone_masked"]
    assert masked.startswith(canonical[:4]) and masked.endswith(canonical[-3:]), (raw, masked)
    # the canonical form is the same customer -> still only one pending checkout
    err(await checkout(anon, slots(c["code"], 11), ph=canonical), 409, "E-WEB-4")


async def test_ac7_name_whitespace_collapsed(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10), name="  Phạm   Quang \t Minh  ")
    assert co["customer"]["full_name"] == "Phạm Quang Minh"


async def test_sec4_unknown_court_and_bad_slots(anon, admin, sepay):
    c = await court(admin)
    err(await checkout(anon, slots("ZZ999", 10)), 422, "E-WEB-2")
    for bad in (-1, 24, 99):
        r = await checkout(anon, slots(c["code"], bad))
        assert r.status_code == 422, (bad, r.text)
    dup = await checkout(anon, slots(c["code"], 10, 10))
    assert dup.status_code in (201, 422), dup.text  # duplicates must never double-book
    if dup.status_code == 201:
        assert dup.json()["items"][0]["hours"] == 1


async def test_ac10_past_and_closed_slots_rejected(anon, admin, sepay):
    c = await court(admin, open_time="06:00", close_time="22:00")
    err(await checkout(anon, slots(c["code"], 5)), 422, "E-WEB-2")  # before opening
    err(await checkout(anon, slots(c["code"], 22)), 422, "E-WEB-2")  # at closing
    past_body = {
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "slots": slots(c["code"], 10),
        "full_name": "QA Quá Khứ",
        "phone": phone(),
    }
    past = await anon.post(f"{W}/checkouts", json=await with_token(anon, past_body), headers=idem())
    assert past.status_code == 422, past.text
    # today: only hours that start in the future may be booked
    h = datetime.now(settings.tz).hour
    started_body = {
        "date": date.today().isoformat(),
        "slots": slots(c["code"], h),
        "full_name": "QA Đang Chơi",
        "phone": phone(),
    }
    started = await anon.post(
        f"{W}/checkouts", json=await with_token(anon, started_body), headers=idem()
    )
    err(started, 422, "E-WEB-2")


async def test_ac10_all_or_nothing_on_conflict(anon, admin, sepay):
    c = await court(admin)
    first = await make_checkout(anon, slots(c["code"], 10))
    r = await checkout(anon, slots(c["code"], 9, 10, 11))
    err(r, 409, "E-WEB-3")
    conflicts = r.json()["detail"]["conflicts"]
    assert {"resource_code": c["code"], "start_hour": 10} in conflicts
    cal = (await calendar(anon)).json()
    assert state_of(cal, c["code"], 9)["state"] == "free", "nothing was created for hour 9"
    assert state_of(cal, c["code"], 11)["state"] == "free"
    assert first["status"] == "pending"


async def test_sec10_parallel_checkouts_same_slot_one_wins(anon, admin, sepay):
    c = await court(admin)
    rs = await asyncio.gather(*[checkout(anon, slots(c["code"], 15)) for _ in range(5)])
    ok = [r for r in rs if r.status_code == 201]
    assert len(ok) == 1, [r.status_code for r in rs]
    assert all(code_of(r) == "E-WEB-3" for r in rs if r.status_code != 201)
    n = await sql(
        "SELECT count(*) AS n FROM booking.allocation a "
        "JOIN booking.resource r ON r.id=a.resource_id "
        "WHERE r.code=:c AND a.active",
        c=c["code"],
    )
    assert n[0]["n"] == 1


async def test_ac13_one_pending_checkout_per_phone(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    first = await make_checkout(anon, slots(c["code"], 8), ph=ph)
    err(await checkout(anon, slots(c["code"], 9), ph=ph), 409, "E-WEB-4")
    err(await checkout(anon, slots(c["code"], 9), ph=ph.replace("09", "+849", 1)), 409, "E-WEB-4")
    # after payment the phone is free again
    assert (await pay(anon, first)).status_code == 200
    again = await checkout(anon, slots(c["code"], 9), ph=ph)
    assert again.status_code == 201, again.text


async def test_ac13_phone_freed_after_expiry(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 8), ph=ph)
    await age_checkout(co["pay_ref"], 400)
    await run_expiry()
    again = await checkout(anon, slots(c["code"], 8), ph=ph)
    assert again.status_code == 201, again.text


async def test_ac13_sec6_ip_rate_limit_six_per_ten_minutes(anon, admin, sepay):
    c = await court(admin)
    codes = []
    for h in range(7):
        r = await checkout(anon, slots(c["code"], h))
        codes.append(r.status_code)
    assert codes[:6] == [201] * 6, codes
    err(await checkout(anon, slots(c["code"], 7)), 429, "E-SEC-5")


async def test_idempotent_checkout_replay_creates_one(anon, admin, sepay):
    c = await court(admin)
    k = idem()
    body = {
        "date": day().isoformat(),
        "slots": slots(c["code"], 10),
        "full_name": "QA Lặp",
        "phone": phone(),
    }
    await with_token(anon, body)
    a = await anon.post(f"{W}/checkouts", json=body, headers=k)
    b = await anon.post(f"{W}/checkouts", json=body, headers=k)
    assert a.status_code == b.status_code == 201
    assert a.json()["pay_ref"] == b.json()["pay_ref"]
    missing = await anon.post(f"{W}/checkouts", json=body)
    assert missing.status_code == 400, missing.text


async def test_origin_required_for_public_writes(admin, sepay):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    c = await court(admin)
    body = {
        "date": day().isoformat(),
        "slots": slots(c["code"], 10),
        "full_name": "QA Origin",
        "phone": phone(),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": "https://evil.example"},
    ) as evil:
        r = await evil.post(f"{W}/checkouts", json=body, headers=idem())
        assert r.status_code == 403 and code_of(r) == "E-SEC-1"
        r = await evil.post(f"{W}/lookup", json={"code": "BK-20200101-001", "phone": "0900000000"})
        assert r.status_code == 403 and code_of(r) == "E-SEC-1"


async def test_ac12_member_phone_gets_member_snapshot_and_no_temp_profile(anon, admin, sepay):
    member = (
        await sql(
            "SELECT member_code, full_name, phone FROM customer "
            "WHERE kind='member' AND is_active ORDER BY id LIMIT 1"
        )
    )[0]
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10), name="Tên Khác Hẳn", ph=member["phone"])
    r = await anon.post(
        f"{W}/lookup", json={"code": co["items"][0]["code"], "phone": member["phone"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["customer_name"] == member["full_name"], "member profile wins over typed name"
    fresh = await checkout_phone_profiles(phone())
    assert fresh == 0
    # a brand-new phone must NOT create a temp profile while only holding (ADR-007 section 7)
    newp = phone()
    await make_checkout(anon, slots(c["code"], 11), ph=newp)
    assert await checkout_phone_profiles(newp) == 0


async def checkout_phone_profiles(ph: str) -> int:
    return (await sql("SELECT count(*) AS n FROM customer WHERE phone=:p", p=ph))[0]["n"]


# ---------------------------------------------------------------------------
# 4. Expiry (AC14, AC17)
# ---------------------------------------------------------------------------


async def test_ac14_grace_period_then_expiry(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    await age_checkout(co["pay_ref"], 5 * 60 + 20)  # past expires_at but within the 60 s grace
    await run_expiry()
    assert (await get_checkout(anon, co["token"]))["status"] == "pending"
    assert state_of((await calendar(anon)).json(), c["code"], 10)["state"] == "booked"
    await age_checkout(co["pay_ref"], 60)  # now beyond the grace
    await run_expiry()
    got = await get_checkout(anon, co["token"])
    assert got["status"] == "expired" and got["bank"] is None
    assert state_of((await calendar(anon)).json(), c["code"], 10)["state"] == "free"
    again = await checkout(anon, slots(c["code"], 10))
    assert again.status_code == 201, "the slot can be sold again"


# ---------------------------------------------------------------------------
# 5. Checkout status page API (AC15, AC16, AC18, SEC3)
# ---------------------------------------------------------------------------


async def test_ac15_get_checkout_by_token(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    r = await anon.get(f"{W}/checkouts/{co['token']}")
    assert r.status_code == 200 and "no-store" in r.headers.get("cache-control", "")
    d = r.json()
    assert "token" not in d, "the token is only returned once"
    assert d["status"] == "pending" and d["bank"]["qr_url"] == co["bank"]["qr_url"]
    assert d["items"][0]["code"] == co["items"][0]["code"]
    assert datetime.fromisoformat(d["server_now"]).tzinfo is not None


async def test_ac18_unknown_token_is_404(anon, sepay):
    for tok in ("x" * 43, "short", uuid.uuid4().hex, "A" * 90):
        r = await anon.get(f"{W}/checkouts/{tok}")
        err(r, 404, "E-WEB-6")
    assert (await anon.get(f"{W}/checkouts/{'A' * 300}")).status_code in (404, 422)
    # path tricks are normalised by the HTTP client/proxy; they must never succeed either
    r = await anon.get(f"{W}/checkouts/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
    assert r.status_code == 404


async def test_sec3_token_stored_hashed_and_not_logged(anon, admin, sepay, caplog):
    c = await court(admin)
    with caplog.at_level("DEBUG"):
        co = await make_checkout(anon, slots(c["code"], 10))
        await get_checkout(anon, co["token"])
    assert co["token"] not in caplog.text, "token must never reach the logs"
    rows = await sql("SELECT token_hash FROM booking.checkout WHERE pay_ref=:p", p=co["pay_ref"])
    h = bytes(rows[0]["token_hash"])
    assert h == hashlib.sha256(co["token"].encode()).digest() and len(h) == 32
    dump = await sql(
        "SELECT row_to_json(t)::text AS j FROM booking.checkout t WHERE pay_ref=:p", p=co["pay_ref"]
    )
    assert co["token"] not in dump[0]["j"]
    assert len(co["token"]) >= 43  # 256 bits as base64url


async def test_sec3_tokens_are_unique(anon, admin, sepay):
    c = await court(admin)
    tokens = {(await make_checkout(anon, slots(c["code"], h)))["token"] for h in range(5)}
    assert len(tokens) == 5


# ---------------------------------------------------------------------------
# 6. SePay webhook (AC19-AC24, SEC5)
# ---------------------------------------------------------------------------


async def test_ac19_sec5_signature_required(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    body = json.dumps(payload(co["pay_ref"], co["amount"])).encode()
    before = (await sql("SELECT count(*) AS n FROM payments.bank_transaction"))[0]["n"]
    good = sign(body)
    # missing headers
    assert (await anon.post(f"{PAY}/sepay/webhook", content=body)).status_code == 401
    # wrong secret
    assert (await webhook(anon, body, headers=sign(body, "another-secret"))).status_code == 401
    # body modified by one byte after signing
    tampered = body.replace(b'"in"', b'"iN"')
    assert (await webhook(anon, tampered, headers=good)).status_code == 401
    # malformed signature / timestamp
    for h in (
        {**good, "X-SePay-Signature": "sha256=zz"},
        {**good, "X-SePay-Signature": good["X-SePay-Signature"].removeprefix("sha256=")},
        {**good, "X-SePay-Timestamp": "abc"},
    ):
        assert (await webhook(anon, body, headers=h)).status_code == 401
    after = (await sql("SELECT count(*) AS n FROM payments.bank_transaction"))[0]["n"]
    assert after == before, "rejected requests write nothing"
    assert (await get_checkout(anon, co["token"]))["status"] == "pending"


async def test_ac19_no_secret_configured_is_503(anon, sepay):
    _set("SEPAY_WEBHOOK_SECRET", "")
    body = json.dumps(payload("BK20200101001", 1000)).encode()
    r = await webhook(anon, body, headers=sign(body, "anything"))
    assert r.status_code == 503, r.text


async def test_ac19_bad_body_with_valid_signature_is_400(anon, sepay):
    for raw in (b"not json", b"[]", b'{"id": "x"}', b"{}"):
        r = await webhook(anon, raw, headers=sign(raw))
        assert r.status_code == 400, (raw, r.status_code, r.text)


async def test_ac19_duplicate_transaction_id_is_ignored(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    body = payload(co["pay_ref"], co["amount"], txn_id=770000000001 + uuid.uuid4().int % 10**9)
    first = await webhook(anon, body)
    again = await webhook(anon, body)
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() == {"success": True}
    n = await sql(
        "SELECT count(*) AS n FROM payments.bank_transaction WHERE provider_txn_id=:i",
        i=str(body["id"]),
    )
    assert n[0]["n"] == 1
    got = await get_checkout(anon, co["token"])
    assert got["status"] == "paid" and got["paid_amount"] == co["amount"], "money counted once"


async def test_sec5_parallel_duplicate_id_counted_once(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    body = payload(co["pay_ref"], co["amount"], txn_id=880000000000 + uuid.uuid4().int % 10**9)
    rs = await asyncio.gather(*[webhook(anon, body) for _ in range(6)])
    assert all(r.status_code == 200 for r in rs), [r.status_code for r in rs]
    n = await sql(
        "SELECT count(*) AS n FROM payments.bank_transaction WHERE provider_txn_id=:i",
        i=str(body["id"]),
    )
    assert n[0]["n"] == 1
    assert (await get_checkout(anon, co["token"]))["paid_amount"] == co["amount"]


async def _outcome(provider_txn_id) -> dict:
    return (
        await sql(
            "SELECT outcome, refund_amount, booking_codes, code, pay_ref "
            "FROM payments.bank_transaction WHERE provider_txn_id=:i",
            i=str(provider_txn_id),
        )
    )[0]


async def test_ac20_code_from_field_and_from_content(anon, admin, sepay):
    c = await court(admin)
    a = await make_checkout(anon, slots(c["code"], 10))
    b = await make_checkout(anon, slots(c["code"], 11))
    pa = payload(a["pay_ref"], a["amount"])
    assert (await webhook(anon, pa)).status_code == 200
    assert (await _outcome(pa["id"]))["outcome"] == "applied"
    pb = payload(None, b["amount"], content=f"MB CK {b['pay_ref'].lower()} cam on")
    assert (await webhook(anon, pb)).status_code == 200
    assert (await _outcome(pb["id"]))["outcome"] == "applied", "pay_ref found in content, any case"
    assert (await get_checkout(anon, b["token"]))["status"] == "paid"


async def test_ac20_unmatched_ignored_cases(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    cases = {
        "no code": payload(None, co["amount"], content="chuyen khoan tien san"),
        "unknown code": payload("BK99999999999", co["amount"]),
        "two codes": payload(None, co["amount"], content=f"{co['pay_ref']} BK99999999998"),
    }
    for label, body in cases.items():
        assert (await webhook(anon, body)).status_code == 200, label
        assert (await _outcome(body["id"]))["outcome"] == "unmatched", label
    out = payload(co["pay_ref"], co["amount"], transferType="out")
    wrong = payload(co["pay_ref"], co["amount"], accountNumber="9999999999")
    for label, body in (("out", out), ("other account", wrong)):
        assert (await webhook(anon, body)).status_code == 200, label
        assert (await _outcome(body["id"]))["outcome"] == "ignored", label
    assert (await get_checkout(anon, co["token"]))["status"] == "pending", "none of them paid it"


async def test_ac21_exact_payment_creates_online_bookings(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 8, 9) + slots(c["code"], 14))
    p = payload(co["pay_ref"], co["amount"])
    r = await webhook(anon, p)
    assert r.status_code == 200 and r.json() == {"success": True}
    row = await _outcome(p["id"])
    assert row["outcome"] == "applied" and row["refund_amount"] == 0
    assert sorted(row["booking_codes"]) == sorted(i["code"] for i in co["items"])
    got = await get_checkout(anon, co["token"])
    assert got["status"] == "paid" and got["paid_amount"] == co["amount"] and got["bank"] is None
    for it in co["items"]:
        item = (await admin.get(f"{BK}/items/{it['code']}")).json()
        assert item["payment"]["payment_status"] == "paid"
        assert item["payment"]["payment_method"] == "online_transfer"
        assert item["payment"]["collected_by"] == "Khách đặt online"
        assert item["source"] == "online" and item["payment"]["amount"] == it["amount"]
        assert "gateway_ref" not in json.dumps(item) and "sepay:" not in json.dumps(item)
    cal = (await calendar(anon)).json()
    assert state_of(cal, c["code"], 8)["state"] == "booked"


async def test_ac21_overpayment_records_refund(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    p = payload(co["pay_ref"], co["amount"] + 50000)
    assert (await webhook(anon, p)).status_code == 200
    row = await _outcome(p["id"])
    assert row["outcome"] == "applied" and row["refund_amount"] == 50000
    assert (await get_checkout(anon, co["token"]))["status"] == "paid"


async def test_ac21_partial_payments_accumulate(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10, 11))
    half = co["amount"] // 2
    p1 = payload(co["pay_ref"], half)
    assert (await webhook(anon, p1)).status_code == 200
    assert (await _outcome(p1["id"]))["outcome"] == "partial"
    mid = await get_checkout(anon, co["token"])
    assert mid["status"] == "pending" and mid["paid_amount"] == half
    p2 = payload(co["pay_ref"], co["amount"] - half)
    assert (await webhook(anon, p2)).status_code == 200
    assert (await _outcome(p2["id"]))["outcome"] == "applied"
    done = await get_checkout(anon, co["token"])
    assert done["status"] == "paid" and done["paid_amount"] == co["amount"]


async def test_ac21_payment_in_grace_period_is_accepted(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    await age_checkout(co["pay_ref"], 5 * 60 + 20)  # expired by the clock, still inside grace
    p = payload(co["pay_ref"], co["amount"])
    assert (await webhook(anon, p)).status_code == 200
    assert (await _outcome(p["id"]))["outcome"] == "applied"
    assert (await get_checkout(anon, co["token"]))["status"] == "paid"


async def test_ac22_payment_after_grace_needs_refund_and_makes_no_booking(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    await age_checkout(co["pay_ref"], 5 * 60 + 61 + 30)
    await run_expiry()
    p = payload(co["pay_ref"], co["amount"])
    assert (await webhook(anon, p)).status_code == 200
    row = await _outcome(p["id"])
    assert row["outcome"] == "refund_needed" and row["refund_amount"] == co["amount"]
    assert not row["booking_codes"]
    r = await admin.get(f"{BK}/items/{co['items'][0]['code']}")
    assert r.status_code == 404, "no booking was created"
    assert (await get_checkout(anon, co["token"]))["status"] == "expired"


async def test_ac22_already_paid_checkout_second_transfer_is_refund(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    assert (await pay(anon, co)).status_code == 200
    p = payload(co["pay_ref"], co["amount"])
    assert (await webhook(anon, p)).status_code == 200
    row = await _outcome(p["id"])
    assert row["outcome"] == "refund_needed" and row["refund_amount"] == co["amount"]
    got = await get_checkout(anon, co["token"])
    assert got["paid_amount"] == co["amount"], "paid_amount is not inflated"


async def test_ac22_partials_then_expiry_refund_counted_once(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10, 11))
    half = co["amount"] // 2
    p1 = payload(co["pay_ref"], half)
    assert (await webhook(anon, p1)).status_code == 200
    await age_checkout(co["pay_ref"], 5 * 60 + 100)
    await run_expiry()
    p2 = payload(co["pay_ref"], 10000)
    assert (await webhook(anon, p2)).status_code == 200
    r1, r2 = await _outcome(p1["id"]), await _outcome(p2["id"])
    assert r2["outcome"] == "refund_needed"
    assert r1["refund_amount"] + r2["refund_amount"] == half + 10000, "every dong refunded once"


async def test_ac23_two_webhooks_complete_one_checkout_once(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10, 11))
    half = co["amount"] // 2
    ps = [payload(co["pay_ref"], half), payload(co["pay_ref"], co["amount"] - half)]
    rs = await asyncio.gather(*[webhook(anon, p) for p in ps])
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    got = await get_checkout(anon, co["token"])
    assert got["status"] == "paid" and got["paid_amount"] == co["amount"]
    n = await sql(
        "SELECT count(*) AS n FROM booking.booking WHERE code = ANY(:c)",
        c=[i["code"] for i in co["items"]],
    )
    assert n[0]["n"] == len(co["items"]), "bookings created exactly once"
    ev = await sql(
        "SELECT count(*) AS n FROM booking.outbox WHERE event_type='booking.online_paid' "
        "AND payload::text LIKE :p",
        p=f"%{co['items'][0]['code']}%",
    )
    assert ev[0]["n"] == 1, "one outbox event"


async def test_ac24_member_profile_created_from_paid_checkout(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 10), name="QA Hồ Sơ Mới", ph=ph)
    assert await checkout_phone_profiles(ph) == 0
    assert (await pay(anon, co)).status_code == 200
    await publish_outbox()
    rows = await sql("SELECT kind, full_name FROM customer WHERE phone=:p", p=ph)
    assert len(rows) == 1 and rows[0]["kind"] == "temp" and rows[0]["full_name"] == "QA Hồ Sơ Mới"
    # a later booking with the same phone keeps the first name (OQ-21)
    co2 = await make_checkout(anon, slots(c["code"], 12), name="Tên Khác", ph=ph)
    assert (await pay(anon, co2)).status_code == 200
    await publish_outbox()
    rows = await sql("SELECT full_name FROM customer WHERE phone=:p", p=ph)
    assert len(rows) == 1 and rows[0]["full_name"] == "QA Hồ Sơ Mới"


# ---------------------------------------------------------------------------
# 7. Lookup (AC25-AC27, SEC2)
# ---------------------------------------------------------------------------


async def lookup(web, code, ph):
    return await web.post(f"{W}/lookup", json={"code": code, "phone": ph})


async def test_ac25_ac26_lookup_paid_with_code_variants(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 10, 11), ph=ph, name="QA Tra Cứu")
    assert (await pay(anon, co)).status_code == 200
    code = co["items"][0]["code"]
    order = co["order_code"]
    for variant in (
        order,
        order.lower(),
        order.replace("-", ""),
        f"  {order.lower()} ",
        co["pay_ref"].lower(),
        code,  # a child code also finds the whole order (T-019 AC3)
        code.lower(),
        code.replace("-", ""),
    ):
        r = await lookup(anon, variant, ph)
        assert r.status_code == 200, (variant, r.text)
        d = r.json()
        assert d["order_code"] == order and d["status"] == "paid" and d["hours"] == 2
        assert [i["code"] for i in d["items"]] == [code] and d["items"][0]["status"] == "paid"
        assert not {"code", "resource_name", "start_time", "end_time"} & set(d), "order-level only"
        assert d["amount"] == co["amount"] and d["paid_at"]
        assert d["customer_name"] == "QA Tra Cứu"
        assert d["phone_masked"].count("x") >= 3 and ph not in json.dumps(d)
    spaced = f"{ph[:4]} {ph[4:7]}.{ph[7:]}"
    assert (await lookup(anon, order, spaced)).status_code == 200


async def test_ac26_lookup_pending_expired_and_counter_states(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 10), ph=ph)
    code = co["items"][0]["code"]
    d = (await lookup(anon, code, ph)).json()
    assert d["status"] == "pending" and d["pending"]["pay_ref"] == co["pay_ref"]
    assert (
        d["pending"]["amount"] == co["amount"] and d["pending"]["bank"]["account_number"] == ACCOUNT
    )
    await age_checkout(co["pay_ref"], 5 * 60 + 100)
    await run_expiry()
    d = (await lookup(anon, code, ph)).json()
    assert d["status"] == "expired"
    assert d.get("pending") is None


async def test_ac26_lookup_counter_booking_unpaid_and_uncollectible(anon, admin):
    h = datetime.now(settings.tz).hour
    c = await court(admin)
    ph = phone()
    r = await admin.post(
        f"{FD}/bookings",
        json={
            "resource_code": c["code"],
            "date": date.today().isoformat(),
            "start_hour": h,
            "end_hour": h + 1,
            "customer": {"temp": {"full_name": "QA Quầy Tra Cứu", "phone": ph}},
        },
        headers=idem(),
    )
    if r.status_code != 201:
        pytest.skip("cannot book the current hour at the counter right now")
    order = r.json()
    assert len(order["bookings"]) == 1
    bk = order["bookings"][0]
    d = (await lookup(anon, order["order_code"], ph)).json()
    assert d["status"] == "unpaid" and d["amount"] == bk["payment"]["amount"]
    assert d["order_code"] == order["order_code"] and [i["code"] for i in d["items"]] == [
        bk["code"]
    ]
    mark = await admin.post(
        f"{BK}/items/{bk['code']}/uncollectible",
        json={"reason": "QA", "version": bk["version"]},
        headers=idem(),
    )
    assert mark.status_code == 200, mark.text
    assert (await lookup(anon, order["order_code"], ph)).json()["status"] == "uncollectible"
    assert (await lookup(anon, bk["code"], ph)).json()["order_code"] == order["order_code"]


async def test_ac27_sec2_wrong_code_and_wrong_phone_look_identical(anon, admin, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 10), ph=ph)
    code = co["items"][0]["code"]
    wrong_phone = await lookup(anon, code, phone())
    wrong_code = await lookup(anon, "BK-20200101-999", ph)
    for r in (wrong_phone, wrong_code):
        err(r, 404, "E-WEB-7")
    assert wrong_phone.json() == wrong_code.json(), "identical body: no enumeration oracle"
    assert code not in wrong_phone.text and ph not in wrong_phone.text
    # ticket / event codes are not supported yet
    ev = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [c["code"]],
            "date": day().isoformat(),
            "start_hour": 16,
            "end_hour": 17,
            "name": "QA ev",
            "capacity": 2,
            "ticket_price": 0,
        },
        headers=idem(),
    )
    err(await lookup(anon, ev.json()["code"], ph), 404, "E-WEB-7")


async def test_sec2_lookup_rate_limit_ten_per_minute(anon, sepay):
    codes = [(await lookup(anon, "BK-20200101-999", "0900000000")).status_code for _ in range(10)]
    assert codes == [404] * 10, codes
    err(await lookup(anon, "BK-20200101-999", "0900000000"), 429, "E-SEC-5")


async def test_ac27_lookup_validates_input(anon, sepay):
    for body in (
        {"code": "", "phone": "0900000000"},
        {"code": "BK", "phone": ""},
        {"code": "x" * 100, "phone": "1"},
        {},
    ):
        r = await anon.post(f"{W}/lookup", json=body)
        assert r.status_code in (404, 422), (body, r.status_code)
    r = await anon.post(
        f"{W}/lookup", json={"code": "BK-20200101-001", "phone": "0900000000", "x": 1}
    )
    assert r.status_code == 422, "extra fields are forbidden"


# ---------------------------------------------------------------------------
# 8. Admin side (AC31, AC32, SEC7, SEC8)
# ---------------------------------------------------------------------------


async def test_ac31_online_booking_visible_to_counter_and_history(anon, admin, staff, sepay):
    c = await court(admin)
    ph = phone()
    co = await make_checkout(anon, slots(c["code"], 10), ph=ph, name="QA Online Quầy")
    cal = (await staff.get(f"{BK}/calendar", params={"date": day().isoformat()})).json()
    held = [
        b for b in cal["blocks"] if b["type"] == "hold" and c["code"] in b.get("resource_codes", [])
    ]
    assert held and held[0].get("expires_at"), "pending hold shows with a countdown"
    assert (await pay(anon, co)).status_code == 200
    cal = (await staff.get(f"{BK}/calendar", params={"date": day().isoformat()})).json()
    blk = [b for b in cal["blocks"] if b.get("code") == co["items"][0]["code"]]
    assert blk and blk[0]["payment_status"] == "paid" and blk[0].get("source") == "online"
    item = (await staff.get(f"{BK}/items/{co['items'][0]['code']}")).json()
    assert item["customer"]["name"] == "QA Online Quầy"
    assert item["customer"]["phone"] == ph, "quầy thấy SĐT đầy đủ (bỏ che số ở màn quản trị)"
    assert item["actions"] == [], "paid online booking has no collect/uncollectible actions"
    tx = (
        await admin.get(
            f"{BK}/transactions",
            params={
                "from": day().isoformat(),
                "to": day().isoformat(),
                "q": co["items"][0]["code"],
            },
        )
    ).json()
    assert tx["total"] == 1 and tx["rows"][0]["code"] == co["items"][0]["code"]
    only_transfer = (
        await admin.get(
            f"{BK}/transactions",
            params={
                "from": day().isoformat(),
                "to": day().isoformat(),
                "method": "transfer",
                "q": co["items"][0]["code"],
            },
        )
    ).json()
    assert only_transfer["total"] == 1, "'Chuyển khoản' filter includes online transfers"


async def test_ac32_bank_transactions_queue_and_resolve(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    over = payload(co["pay_ref"], co["amount"] + 7000)
    lost = payload(None, 12345, content=f"khong ma {uuid.uuid4().hex[:8]}")
    ok_only = payload("BK00000000000", 1)
    for p in (over, lost, ok_only):
        assert (await webhook(anon, p)).status_code == 200
    r = await admin.get(f"{PAY}/bank-transactions", params={"needs_action": "true", "limit": 500})
    assert r.status_code == 200, r.text
    rows = {x["provider_txn_id"]: x for x in r.json()}
    assert str(over["id"]) in rows and rows[str(over["id"])]["refund_amount"] == 7000
    assert str(lost["id"]) in rows and rows[str(lost["id"])]["outcome"] == "unmatched"
    row = rows[str(over["id"])]
    for k in (
        "id",
        "provider",
        "received_at",
        "transaction_at",
        "amount",
        "content",
        "outcome",
        "booking_codes",
    ):
        assert k in row, k
    rid = row["id"]
    for bad in ("", "x" * 501):
        err_r = await admin.post(
            f"{PAY}/bank-transactions/{rid}/resolve", json={"note": bad}, headers=idem()
        )
        assert err_r.status_code == 422, (len(bad), err_r.text)
    ok = await admin.post(
        f"{PAY}/bank-transactions/{rid}/resolve",
        json={"note": "Đã hoàn 7.000 <b>x</b>"},
        headers=idem(),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["resolved_at"] and ok.json()["resolved_by_label"] == "Admin"
    again = await admin.post(
        f"{PAY}/bank-transactions/{rid}/resolve", json={"note": "lần hai"}, headers=idem()
    )
    err(again, 409, "E-PAY-2")
    after = (
        await admin.get(f"{PAY}/bank-transactions", params={"needs_action": "true", "limit": 500})
    ).json()
    assert str(over["id"]) not in {x["provider_txn_id"] for x in after}


async def test_sec8_bank_transactions_admin_only(anon, customer, staff, admin):
    cases = [
        ("GET", f"{PAY}/bank-transactions?needs_action=true"),
        ("POST", f"{PAY}/bank-transactions/1/resolve"),
    ]
    for method, path in cases:
        for name, client, want in (
            ("anon", anon, 401),
            ("customer", customer, 403),
            ("staff", staff, 403),
        ):
            r = await client.request(method, path, json={"note": "x"}, headers=idem())
            assert r.status_code == want, (name, method, path, r.status_code, r.text)
    assert (await admin.get(f"{PAY}/bank-transactions")).status_code == 200


async def test_sec7_simulate_off_is_404_for_everyone(anon, customer, staff, admin, sepay):
    _set("PAYMENTS_SIMULATE", False)
    body = {"pay_ref": "BK00000000000", "amount": 1000}
    for client in (anon, customer, staff, admin):
        r = await client.post(f"{PAY}/dev/simulate", json=body, headers=idem())
        assert r.status_code == 404, r.status_code


async def test_sec7_simulate_on_admin_only_and_uses_webhook_path(
    anon, customer, staff, admin, sepay
):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    body = {"pay_ref": co["pay_ref"], "amount": co["amount"]}
    assert (await anon.post(f"{PAY}/dev/simulate", json=body, headers=idem())).status_code in (
        401,
        403,
    )
    assert (
        await customer.post(f"{PAY}/dev/simulate", json=body, headers=idem())
    ).status_code == 403
    assert (await staff.post(f"{PAY}/dev/simulate", json=body, headers=idem())).status_code == 403
    assert (await get_checkout(anon, co["token"]))["status"] == "pending"
    ok = await admin.post(f"{PAY}/dev/simulate", json=body, headers=idem())
    assert ok.status_code == 200, ok.text
    assert (await get_checkout(anon, co["token"]))["status"] == "paid"
    rows = await sql(
        "SELECT provider_txn_id FROM payments.bank_transaction WHERE pay_ref=:p", p=co["pay_ref"]
    )
    assert rows and rows[0]["provider_txn_id"].startswith("sim-")


def test_sec7_production_refuses_simulate_flag():
    cls = type(settings)
    # since T-012 staging/production also require a valid Fernet key (32 bytes, urlsafe base64)
    base = {"_env_file": None, "SECRET_KEY": "x" * 40, "PAYMENTS_ENCRYPTION_KEY": "0" * 43 + "="}
    cls(**base, ENV="staging", PAYMENTS_SIMULATE=True)  # allowed outside production
    with pytest.raises(ValueError, match="(?i)PAYMENTS_SIMULATE"):  # pydantic ValidationError
        cls(**base, ENV="production", PAYMENTS_SIMULATE=True)


# ---------------------------------------------------------------------------
# 9. Shared guarantees
# ---------------------------------------------------------------------------


async def test_sec6_cannot_hold_more_than_16_slots_via_many_requests_on_one_phone(
    anon, admin, sepay
):
    c = await court(admin)
    ph = phone()
    first = await make_checkout(anon, slots(c["code"], *range(0, 16)), ph=ph)
    assert len(first["items"]) == 1
    err(await checkout(anon, slots(c["code"], 20), ph=ph), 409, "E-WEB-4")


async def test_db_hold_to_booking_keeps_exclusion_constraint(anon, admin, sepay):
    c = await court(admin)
    co = await make_checkout(anon, slots(c["code"], 10))
    assert (await pay(anon, co)).status_code == 200
    n = await sql(
        "SELECT count(*) AS n FROM booking.allocation a "
        "JOIN booking.resource r ON r.id=a.resource_id "
        "WHERE r.code=:c AND a.active",
        c=c["code"],
    )
    assert n[0]["n"] == 1, "the hold's allocation moved to the booking (no second row)"
    err(await checkout(anon, slots(c["code"], 10)), 409, "E-WEB-3")


async def test_legacy_flow_still_gone(anon):
    for path in ("courts", "venue/config", "bookings"):
        assert (await anon.get(f"{API}/{path}")).status_code == 404


async def test_ac1_unlimited_days_ahead_can_be_booked(anon, admin, sepay):
    """AC1/AC10: online booking has no upper limit on the date (only the past is refused)."""
    c = await court(admin)
    far = day(400)
    cal = (await calendar(anon, far)).json()
    assert state_of(cal, c["code"], 10)["state"] == "free"
    co = await make_checkout(anon, slots(c["code"], 10), d=far)
    assert co["items"][0]["code"].startswith("BK-" + far.strftime("%Y%m%d"))

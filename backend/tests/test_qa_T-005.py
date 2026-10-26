"""QA acceptance tests for T-005 (security foundation + booking_engine skeleton + config & pricing).

Source of truth: board/tasks/T-005-nen-tang-booking-engine.md and
board/decisions/ADR-004-bao-mat-nen-tang.md.
Tests talk to the public HTTP contract only (no engine internals), so they stay valid
whatever BACKEND names its modules.

Names follow the spec: test_d1..d8 (configuration rules), test_sec1/3/4/5/6/7/8 (security criteria),
test_b* (shared infrastructure), test_c5 (architecture).

ASSUMED CONTRACT (shapes the spec leaves open; adjust section 1 helpers at BE handoff):
  * resource create/patch bodies: name, resource_type_code, open_time, close_time,
    peak_bands, version, is_active
  * GET /booking/prices -> {"version": int, "prices": [{resource_type_code, day_type,
    band, price_per_hour}]}
  * POST /booking/special-days body: date_from, date_to, name -> {"id": ...}
  * quote response exposes the amount as total_amount (or total)
  * config validation failures answer 409 or 422 with detail.code = E-CFG-n
"""

import asyncio
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.main import app
from app.modules.booking_engine.testing import make_allocation, release_allocation
from tests.conftest import API

B = f"{API}/booking"
EVIL = "https://evil.example"
INVALID_STATUSES = (400, 409, 422)


# ---------------------------------------------------------------------------
# 1. Contract helpers (the only place that knows request/response shapes)
# ---------------------------------------------------------------------------


def _allowed_origin() -> str:
    raw = getattr(settings, "ALLOWED_ORIGINS", None)
    if isinstance(raw, str):
        raw = [o.strip() for o in raw.split(",") if o.strip()]
    return (list(raw) if raw else ["http://localhost:3000"])[0]


def _http(origin: str | None = None) -> AsyncClient:
    headers = {"Origin": origin or _allowed_origin()}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver", headers=headers
    )


def _key() -> str:
    return str(uuid.uuid4())


def _items(data):
    if isinstance(data, list):
        return data
    return next(v for v in data.values() if isinstance(v, list))


def _code(resp) -> str | None:
    try:
        detail = resp.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return None
    return detail.get("code") if isinstance(detail, dict) else None


def _total(resp) -> int:
    data = resp.json()
    return data["total_amount"] if "total_amount" in data else data["total"]


def _resource_payload(
    name, *, type_code="thuong", open_time="05:00", close_time="22:00", peaks=None
):
    peaks = peaks if peaks is not None else [["05:00", "07:00"], ["17:00", "21:00"]]
    return {
        "name": name,
        "resource_type_code": type_code,
        "open_time": open_time,
        "close_time": close_time,
        "peak_bands": peaks,
    }


async def write(client, method, path, *, json_body=None, key="auto", **kw):
    headers = dict(kw.pop("headers", {}))
    if key == "auto":
        headers["Idempotency-Key"] = _key()
    elif key is not None:
        headers["Idempotency-Key"] = key
    return await client.request(method, path, json=json_body, headers=headers, **kw)


async def quote(client, code, day, start_hour, end_hour):
    return await client.post(
        f"{B}/quote",
        json={
            "resource_code": code,
            "date": day.isoformat(),
            "start_hour": start_hour,
            "end_hour": end_hour,
        },
    )


async def new_resource(adm, **kw):
    name = f"QA {uuid.uuid4().hex[:8]}"
    r = await write(adm, "POST", f"{B}/resources", json_body=_resource_payload(name, **kw))
    assert r.status_code == 201, r.text
    return r.json()


def next_weekday(weekday: int, min_days: int = 2) -> date:
    d = date.today() + timedelta(days=min_days)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


async def add_holiday(adm, day: date, name: str | None = None, to: date | None = None):
    return await write(
        adm,
        "POST",
        f"{B}/special-days",
        json_body={
            "date_from": day.isoformat(),
            "date_to": (to or day).isoformat(),
            "name": name if name is not None else f"QA lễ {uuid.uuid4().hex[:6]}",
        },
    )


async def free_holiday(adm, picker):
    """Create a one-day holiday on the first free date (within 20 days) accepted by `picker`."""
    for offset in range(2, 22):
        day = date.today() + timedelta(days=offset)
        if not picker(day):
            continue
        r = await add_holiday(adm, day)
        if r.status_code == 201:
            return day, r.json()["id"]
        assert _code(r) == "E-CFG-8", r.text
    pytest.fail("no free date found for a test holiday")


async def drop_holiday(adm, special_id):
    r = await write(adm, "DELETE", f"{B}/special-days/{special_id}")
    assert r.status_code in (200, 204), r.text


# ---------------------------------------------------------------------------
# 2. Fixtures (clients always send an allowed Origin, so only the tested header varies)
# ---------------------------------------------------------------------------


@pytest.fixture
async def adm():
    async with _http() as c:
        r = await c.post(
            f"{API}/auth/login",
            json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
        )
        assert r.status_code == 200, r.text
        yield c


@asynccontextmanager
async def _registered(role_by_admin: tuple | None = None):
    n = uuid.uuid4().hex[:8]
    creds = {
        "email": f"qa{n}@test.vn",
        "password": "password123",
        "full_name": f"QA {n}",
        "phone": "0912345678",
    }
    async with _http() as c:
        if role_by_admin is None:
            r = await c.post(f"{API}/auth/register", json=creds)
            assert r.status_code == 201, r.text
        else:
            admin_client, role = role_by_admin
            r = await admin_client.post(f"{API}/admin/users", json={**creds, "role": role})
            assert r.status_code == 201, r.text
            r = await c.post(
                f"{API}/auth/login", json={"email": creds["email"], "password": creds["password"]}
            )
            assert r.status_code == 200, r.text
        yield c


@pytest.fixture
async def customer_c():
    async with _registered() as c:
        yield c


@pytest.fixture
async def staff_c(adm):
    async with _registered((adm, "staff")) as c:
        yield c


@pytest.fixture
async def anon_c():
    async with _http() as c:
        yield c


@pytest.fixture
def clean_rate_limit(monkeypatch):
    """Turn the limiter on for the test; conftest's autouse fixture resets the counters (Q4)."""
    if "RATE_LIMIT_ENABLED" in type(settings).model_fields:
        monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)


# ---------------------------------------------------------------------------
# 3. D1–D8: configuration & pricing rules
# ---------------------------------------------------------------------------

SEED_PRICES = [
    # code, weekday-index, start_hour, expected VND (S01 thuong, S05 vip) – seed table in the spec
    ("S01", 2, 7, 150_000),  # Wed off-peak
    ("S01", 2, 6, 180_000),  # Wed 06–07 is peak (05–07)
    ("S01", 2, 16, 150_000),  # just before 17h peak
    ("S01", 2, 17, 180_000),  # first peak hour
    ("S01", 2, 20, 180_000),  # last peak hour (17–21)
    ("S01", 2, 21, 150_000),  # right after peak, still open (until 22)
    ("S01", 5, 18, 240_000),  # Sat peak
    ("S01", 6, 9, 210_000),  # Sun off-peak
    ("S05", 2, 8, 250_000),  # VIP weekday off-peak (S05 opens 06:00)
    ("S05", 2, 18, 300_000),  # VIP weekday peak
    ("S05", 5, 18, 400_000),  # VIP weekend peak
]


@pytest.mark.parametrize(("code", "wd", "hour", "expected"), SEED_PRICES)
async def test_d2_seed_price_per_hour_frame(adm, code, wd, hour, expected):
    day = next_weekday(wd)
    r = await quote(adm, code, day, hour, hour + 1)
    if _special_day_covers(await _special_days(adm), day):
        pytest.skip("test date falls on a seeded holiday")
    assert r.status_code == 200, r.text
    assert _total(r) == expected


async def test_d2_multi_frame_quote_is_sum_of_frames(adm):
    day = next_weekday(2)
    if _special_day_covers(await _special_days(adm), day):
        pytest.skip("test date falls on a seeded holiday")
    r = await quote(adm, "S01", day, 16, 18)  # 16–17 off-peak + 17–18 peak
    assert r.status_code == 200, r.text
    assert _total(r) == 150_000 + 180_000


async def _special_days(adm):
    r = await adm.get(f"{B}/special-days")
    assert r.status_code == 200, r.text
    return _items(r.json())


def _special_day_covers(days, d: date) -> bool:
    return any(
        date.fromisoformat(s["date_from"]) <= d <= date.fromisoformat(s["date_to"]) for s in days
    )


async def test_d2_and_d4_partial_peak_frame_priced_by_half_hours_from_tomorrow(adm):
    res = await new_resource(adm)  # peaks 05–07, 17–21
    tomorrow = date.today() + timedelta(days=1)
    if _special_day_covers(await _special_days(adm), tomorrow):
        pytest.skip("tomorrow is a holiday")
    r = await write(
        adm,
        "PATCH",
        f"{B}/resources/{res['code']}",
        json_body={
            "version": res["version"],
            "peak_bands": [["05:00", "06:30"], ["17:00", "21:00"]],
        },
    )
    assert r.status_code == 200, r.text
    # D4: new schedule is effective from tomorrow and listed as pending
    listing = await adm.get(f"{B}/resources")
    entry = next(x for x in _items(listing.json()) if x["code"] == res["code"])
    assert tomorrow.isoformat() in json.dumps(entry), (
        "pending schedule must show effective_from=tomorrow"
    )
    # D2: frame 06–07 = half peak + half off-peak
    q = await quote(adm, res["code"], tomorrow, 6, 7)
    assert q.status_code == 200, q.text
    expected = 225_000 if tomorrow.weekday() >= 5 else 165_000
    assert _total(q) == expected
    assert "Một phần cao điểm" in q.text
    # a frame fully inside the peak / fully off-peak keeps its label
    peak = await quote(adm, res["code"], tomorrow, 17, 18)
    assert "Cao điểm" in peak.text
    off = await quote(adm, res["code"], tomorrow, 8, 9)
    assert "Thấp điểm" in off.text


@pytest.mark.parametrize(
    ("code", "hour"),
    [
        ("S05", 5),  # S05 opens at 06:00
        ("S01", 22),  # closes at 22:00
        ("S01", 4),  # before opening
        ("S06", 10),  # inactive resource
    ],
)
async def test_d3_frame_outside_hours_or_inactive_is_not_sellable(adm, code, hour):
    r = await quote(adm, code, next_weekday(2), hour, hour + 1)
    assert r.status_code in INVALID_STATUSES, r.text


async def test_d3_last_frame_before_closing_is_sellable(adm):
    r = await quote(adm, "S01", next_weekday(2), 21, 22)
    assert r.status_code == 200, r.text


async def test_d1_day_types_weekday_weekend_holiday(adm):
    wed, sat, sun = next_weekday(2), next_weekday(5), next_weekday(6)
    days = await _special_days(adm)
    if any(_special_day_covers(days, d) for d in (wed, sat, sun)):
        pytest.skip("test dates overlap a seeded holiday")
    assert _total(await quote(adm, "S01", wed, 10, 11)) == 150_000
    assert _total(await quote(adm, "S01", sat, 10, 11)) == 210_000
    assert _total(await quote(adm, "S01", sun, 10, 11)) == 210_000
    # holiday on a weekday -> holiday price; holiday on a Saturday -> holiday beats weekend
    day, sid = await free_holiday(adm, lambda d: d.weekday() < 5)
    try:
        assert _total(await quote(adm, "S01", day, 10, 11)) == 225_000
        assert _total(await quote(adm, "S05", day, 18, 19)) == 420_000
    finally:
        await drop_holiday(adm, sid)
    day, sid = await free_holiday(adm, lambda d: d.weekday() == 5)
    try:
        assert _total(await quote(adm, "S01", day, 10, 11)) == 225_000
    finally:
        await drop_holiday(adm, sid)
    assert (
        _total(await quote(adm, "S01", day, 10, 11)) == 210_000
    )  # holiday removed -> weekend again


def closing_at(hour: int) -> dict:
    """Body fragment closing earlier while keeping the peak bands inside opening hours."""
    return {
        "close_time": f"{hour:02d}:00",
        "peak_bands": [["05:00", "07:00"], ["17:00", f"{hour:02d}:00"]],
    }


async def _occupy(code: str, day: date, start_h: int, end_h: int) -> int:
    """Insert an active occupancy through BACKEND's test-only helper (T-005 Q5)."""
    start = datetime.combine(day, time(start_h), settings.tz)
    end = datetime.combine(day, time(0), settings.tz) + timedelta(hours=end_h)
    async with SessionLocal() as session:
        alloc_id = await make_allocation(session, code, start, end, owner_code="BK-QA-T005")
        await session.commit()
    return alloc_id


async def _free(alloc_ids) -> None:
    async with SessionLocal() as session:
        for alloc_id in alloc_ids:
            await release_allocation(session, alloc_id)
        await session.commit()


async def test_d4_hours_change_blocked_only_by_occupancy_from_tomorrow(adm):
    res = await new_resource(adm)  # open 05:00–22:00
    today, tomorrow = date.today(), date.today() + timedelta(days=1)
    path = f"{B}/resources/{res['code']}"
    version = res["version"]
    ids = [await _occupy(res["code"], today, 21, 22)]  # today is not affected by a change
    try:
        r = await write(adm, "PATCH", path, json_body={"version": version, **closing_at(20)})
        assert r.status_code == 200, r.text  # only today's slot lies outside the new hours
        version = r.json()["version"]
        ids.append(await _occupy(res["code"], tomorrow + timedelta(days=1), 20, 21))
        r = await write(adm, "PATCH", path, json_body={"version": version, **closing_at(19)})
        assert r.status_code == 409 and _code(r) == "E-CFG-3", r.text
        detail = r.json()["detail"]
        assert len(detail["items"]) == 1 and detail["more"] == 0
        assert detail["items"][0]["date"] == (tomorrow + timedelta(days=1)).isoformat()
    finally:
        await _free(ids)
    r = await write(adm, "PATCH", path, json_body={"version": version, **closing_at(19)})
    assert r.status_code == 200, r.text  # allowed once the occupancy is gone


async def test_d4_conflict_list_is_capped_at_six_with_remainder(adm):
    res = await new_resource(adm)
    first = date.today() + timedelta(days=2)
    ids = [await _occupy(res["code"], first + timedelta(days=i), 20, 21) for i in range(8)]
    try:
        r = await write(
            adm,
            "PATCH",
            f"{B}/resources/{res['code']}",
            json_body={"version": res["version"], **closing_at(19)},
        )
        assert r.status_code == 409 and _code(r) == "E-CFG-3", r.text
        detail = r.json()["detail"]
        assert len(detail["items"]) == 6 and detail["more"] == 2
    finally:
        await _free(ids)


async def test_d5_deactivate_blocked_when_occupied_from_today(adm):
    res = await new_resource(adm)
    path = f"{B}/resources/{res['code']}"
    alloc = await _occupy(res["code"], date.today() + timedelta(days=1), 10, 11)
    try:
        r = await write(
            adm, "PATCH", path, json_body={"version": res["version"], "is_active": False}
        )
        assert r.status_code == 409 and _code(r) == "E-CFG-4", r.text
        assert r.json()["detail"]["items"], "conflicts must be listed"
    finally:
        await _free([alloc])
    r = await write(adm, "PATCH", path, json_body={"version": res["version"], "is_active": False})
    assert r.status_code == 200, r.text


async def test_d5_deactivate_free_resource_makes_it_unsellable(adm):
    res = await new_resource(adm)
    r = await write(
        adm,
        "PATCH",
        f"{B}/resources/{res['code']}",
        json_body={"version": res["version"], "is_active": False},
    )
    assert r.status_code == 200, r.text
    q = await quote(adm, res["code"], next_weekday(2), 10, 11)
    assert q.status_code in INVALID_STATUSES, q.text


async def test_d6_name_rules(adm):
    base = await new_resource(adm)
    name = (await adm.get(f"{B}/resources")).json()
    existing = next(x for x in _items(name) if x["code"] == base["code"])["name"]
    # duplicate, case-insensitive -> E-CFG-1
    r = await write(adm, "POST", f"{B}/resources", json_body=_resource_payload(existing.upper()))
    assert r.status_code in INVALID_STATUSES and _code(r) == "E-CFG-1", r.text
    # length 1..50
    for bad in ("", "x" * 51):
        r = await write(adm, "POST", f"{B}/resources", json_body=_resource_payload(bad))
        assert r.status_code in INVALID_STATUSES, f"len={len(bad)}: {r.text}"
    fifty = ("Q" * 18 + uuid.uuid4().hex)[:50]
    ok = await write(adm, "POST", f"{B}/resources", json_body=_resource_payload(fifty))
    assert ok.status_code == 201, ok.text  # 50 characters is the allowed maximum


async def test_d6_hours_and_peak_rules(adm):
    cases = {
        "E-CFG-2": [
            dict(open_time="08:00", close_time="08:30"),  # less than 60 minutes open
            dict(open_time="10:00", close_time="09:00"),
        ],
        "E-CFG-5": [
            dict(peaks=[["05:30", "05:30"]]),  # shorter than 30 minutes
            dict(peaks=[["04:00", "06:00"]]),  # starts before opening
            dict(peaks=[["20:00", "23:00"]]),  # ends after closing
            dict(peaks=[["05:00", "08:00"], ["07:00", "09:00"]]),  # overlap
        ],
    }
    for expected, variants in cases.items():
        for kw in variants:
            payload = _resource_payload(f"QA {uuid.uuid4().hex[:8]}", **kw)
            r = await write(adm, "POST", f"{B}/resources", json_body=payload)
            assert r.status_code in INVALID_STATUSES, f"{kw}: {r.text}"
            assert _code(r) == expected, f"{kw}: {r.text}"


async def _get_prices(adm):
    r = await adm.get(f"{B}/prices")
    assert r.status_code == 200, r.text
    return r.json()


def _bump(prices, delta, type_code="thuong", day_type="weekday", band="offpeak"):
    out = json.loads(json.dumps(prices))
    for p in out:
        if (p["resource_type_code"], p["day_type"], p["band"]) == (type_code, day_type, band):
            p["price_per_hour"] += delta
    return out


async def test_d7_price_table_optimistic_lock_and_validation(adm):
    cur = await _get_prices(adm)
    ver, table = cur["version"], cur["prices"]
    try:
        # stale/other version -> E-CFG-7
        r = await write(adm, "PUT", f"{B}/prices", json_body={"version": ver + 99, "prices": table})
        assert r.status_code == 409 and _code(r) == "E-CFG-7", r.text
        assert "Tải lại" in r.text
        # every cell must be an integer > 0 -> E-CFG-6
        for bad in (0, -1):
            broken = json.loads(json.dumps(table))
            broken[0]["price_per_hour"] = bad
            r = await write(adm, "PUT", f"{B}/prices", json_body={"version": ver, "prices": broken})
            assert r.status_code == 422 and _code(r) == "E-CFG-6", f"{bad!r}: {r.text}"
        for bad in (150000.5, "abc"):  # not an integer: generic 422 validation (BE handoff)
            broken = json.loads(json.dumps(table))
            broken[0]["price_per_hour"] = bad
            r = await write(adm, "PUT", f"{B}/prices", json_body={"version": ver, "prices": broken})
            assert r.status_code == 422, f"{bad!r}: {r.text}"
        incomplete = table[:-1]  # every one of the 12 cells is required
        r = await write(adm, "PUT", f"{B}/prices", json_body={"version": ver, "prices": incomplete})
        assert r.status_code == 422 and _code(r) == "E-CFG-6", r.text
        # valid save: version moves on, a second save with the old version is rejected
        r = await write(
            adm, "PUT", f"{B}/prices", json_body={"version": ver, "prices": _bump(table, 10_000)}
        )
        assert r.status_code == 200, r.text
        new = await _get_prices(adm)
        assert new["version"] != ver
        again = await write(adm, "PUT", f"{B}/prices", json_body={"version": ver, "prices": table})
        assert again.status_code == 409 and _code(again) == "E-CFG-7", again.text
        # new price applies to a frame that is not booked yet
        wed = next_weekday(2)
        if not _special_day_covers(await _special_days(adm), wed):
            assert _total(await quote(adm, "S01", wed, 10, 11)) == 160_000
    finally:
        latest = await _get_prices(adm)
        await write(
            adm, "PUT", f"{B}/prices", json_body={"version": latest["version"], "prices": table}
        )


async def test_d8_special_day_overlap_year_and_delete(adm):
    base = date.today() + timedelta(days=3)
    if base.year != (base + timedelta(days=4)).year:
        pytest.skip("range crosses a year boundary")
    day, sid = await free_holiday(adm, lambda d: d.year == (d + timedelta(days=4)).year)
    try:
        r = await add_holiday(adm, day, "QA trùng")
        assert r.status_code == 409 and _code(r) == "E-CFG-8", r.text
        assert "đã nằm trong" in r.text and day.strftime("%d/%m") in r.text
        # range overlapping the first day is also rejected
        r = await add_holiday(adm, day - timedelta(days=1), "QA trùng khoảng", to=day)
        assert r.status_code == 409 and _code(r) == "E-CFG-8", r.text
    finally:
        await drop_holiday(adm, sid)
    r = await add_holiday(adm, day, "QA sau khi xóa")  # deletable, so the date is free again
    assert r.status_code == 201, r.text
    await drop_holiday(adm, r.json()["id"])
    # validation: from > to, different years, name length
    r = await add_holiday(adm, day + timedelta(days=2), to=day)
    assert r.status_code in INVALID_STATUSES, r.text
    r = await add_holiday(
        adm, date(date.today().year, 12, 30), to=date(date.today().year + 1, 1, 2)
    )
    assert r.status_code in INVALID_STATUSES, r.text
    for bad in ("", "x" * 101):
        r = await add_holiday(adm, day, bad)
        assert r.status_code in INVALID_STATUSES, f"len={len(bad)}: {r.text}"


# ---------------------------------------------------------------------------
# 4. Security criteria (ADR-004)
# ---------------------------------------------------------------------------


async def test_sec1_global_rate_limit_returns_429_with_retry_after(clean_rate_limit):
    async with _http() as c:
        statuses, retry = [], None
        for _ in range(135):
            r = await c.get(f"{API}/venue/config")
            statuses.append(r.status_code)
            if r.status_code == 429:
                retry = r.headers.get("Retry-After")
                break
    assert 429 in statuses, "no 429 after 135 requests (limit is 120/min/IP)"
    assert statuses.index(429) <= 121
    assert statuses.count(200) >= 100, "limiter kicked in far too early"
    assert retry is not None and int(retry) >= 1


WRITE_CALLS = [
    ("POST", f"{B}/resources", lambda: _resource_payload(f"QA {uuid.uuid4().hex[:8]}")),
    ("PATCH", f"{B}/resources/S01", lambda: {"version": 1, "name": "hacked"}),
    ("PUT", f"{B}/prices", lambda: {"version": 1, "prices": []}),
    (
        "POST",
        f"{B}/special-days",
        lambda: {"date_from": "2026-12-01", "date_to": "2026-12-01", "name": "x"},
    ),
    ("DELETE", f"{B}/special-days/1", lambda: None),
]


@pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS)
async def test_sec3_foreign_origin_with_cookie_is_forbidden(adm, method, path, body):
    r = await write(adm, method, path, json_body=body(), headers={"Origin": EVIL})
    assert r.status_code == 403, r.text
    assert _code(r) == "E-SEC-1", r.text


async def test_sec3_foreign_referer_and_legacy_routes_also_blocked(adm, customer_c):
    r = await write(
        adm,
        "POST",
        f"{B}/special-days",
        json_body={"date_from": "2026-12-01", "date_to": "2026-12-01", "name": "x"},
        headers={"Origin": "", "Referer": f"{EVIL}/page"},
    )
    assert r.status_code == 403, r.text
    r = await customer_c.post(f"{API}/bookings", json={"slots": []}, headers={"Origin": EVIL})
    assert r.status_code == 403, r.text


async def test_sec3_safe_methods_and_allowed_origin_pass(adm):
    assert (await adm.get(f"{B}/resources", headers={"Origin": EVIL})).status_code == 200
    ok = await write(adm, "PUT", f"{B}/prices", json_body={"version": 0, "prices": []})
    assert ok.status_code != 403, "allowed Origin must not be blocked by CSRF check"


def _sweep_routes(prefixes, skip):
    """Yield (method, concrete path) for every documented route under the given prefixes."""
    for path, item in app.openapi()["paths"].items():
        if not any(path.startswith(p) for p in prefixes):
            continue
        for method in sorted(item):
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            if (method.upper(), path) in skip:
                continue
            yield method.upper(), re.sub(r"\{[^}]+\}", "1", path)


QUOTE = ("POST", f"{B}/quote")  # Q2: admin + staff only (customers get 403 until T-008)
CONFIG_PUBLIC_FOR_STAFF = {("GET", f"{B}/resources")}


async def test_sec4_all_admin_routes_require_login_and_role(anon_c, customer_c):
    routes = list(_sweep_routes((f"{API}/admin/", f"{B}/"), set()))
    assert len(routes) >= 8, "route sweep found too few admin/booking routes"
    for method, path in routes:
        a = await write(anon_c, method, path, json_body={})
        assert a.status_code == 401, f"anon {method} {path} -> {a.status_code}"
        c = await write(customer_c, method, path, json_body={})
        assert c.status_code == 403, f"customer {method} {path} -> {c.status_code}"


async def test_sec4_counter_account_cannot_use_config_api(staff_c):
    routes = list(_sweep_routes((f"{B}/",), {QUOTE} | CONFIG_PUBLIC_FOR_STAFF))
    assert len(routes) >= 5
    for method, path in routes:
        r = await write(staff_c, method, path, json_body={})
        assert r.status_code == 403, f"staff {method} {path} -> {r.status_code}"
    assert (
        await staff_c.get(f"{B}/resources")
    ).status_code == 200  # counter may read the catalogue


async def test_q2_quote_allowed_for_admin_and_staff_only(adm, staff_c, customer_c, anon_c):
    body = {
        "resource_code": "S01",
        "date": next_weekday(2).isoformat(),
        "start_hour": 10,
        "end_hour": 11,
    }
    assert (await adm.post(f"{B}/quote", json=body)).status_code == 200
    assert (await staff_c.post(f"{B}/quote", json=body)).status_code == 200
    assert (await customer_c.post(f"{B}/quote", json=body)).status_code == 403
    assert (await anon_c.post(f"{B}/quote", json=body)).status_code == 401


async def test_q2_quote_rate_limit_60_per_minute_per_user(adm, clean_rate_limit):
    body = {
        "resource_code": "S01",
        "date": next_weekday(2).isoformat(),
        "start_hour": 10,
        "end_hour": 11,
    }
    statuses = []
    for _ in range(65):
        r = await adm.post(f"{B}/quote", json=body)
        statuses.append(r.status_code)
        if r.status_code == 429:
            assert int(r.headers["Retry-After"]) >= 1
            break
    assert 429 in statuses, "no 429 after 65 quotes (limit is 60/min/user)"
    assert statuses.index(429) <= 61


async def test_q3_cookie_write_without_origin_and_referer_is_forbidden(adm):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.post(
            f"{API}/auth/login",
            json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
        )
        assert r.status_code == 200, "login has no cookie yet, so it must not need an Origin"
        w = await write(
            c,
            "POST",
            f"{B}/special-days",
            json_body={"date_from": "2026-12-01", "date_to": "2026-12-01", "name": "x"},
        )
        assert w.status_code == 403 and _code(w) == "E-SEC-1", w.text
        ok = await c.get(f"{B}/resources")  # safe methods are not subject to the check
        assert ok.status_code == 200, ok.text


async def test_sec5_forbidden_body_fields_rejected_with_422(adm):
    extras = {"price": 1, "amount": 1, "code": "S99", "created_by": "hacker"}
    bodies = [
        ("POST", f"{B}/resources", _resource_payload(f"QA {uuid.uuid4().hex[:8]}")),
        (
            "POST",
            f"{B}/special-days",
            {"date_from": "2026-12-05", "date_to": "2026-12-05", "name": "x"},
        ),
        ("PATCH", f"{B}/resources/S01", {"version": 1, "name": "Sân 1"}),
    ]
    prices = await _get_prices(adm)
    bodies.append(
        ("PUT", f"{B}/prices", {"version": prices["version"], "prices": prices["prices"]})
    )
    for method, path, base in bodies:
        for field, value in extras.items():
            r = await write(adm, method, path, json_body={**base, field: value})
            assert r.status_code == 422, (
                f"{method} {path} +{field} -> {r.status_code}: {r.text[:200]}"
            )
    q = await adm.post(
        f"{B}/quote",
        json={
            "resource_code": "S01",
            "date": next_weekday(2).isoformat(),
            "start_hour": 10,
            "end_hour": 11,
            "price": 1,
        },
    )
    assert q.status_code == 422, q.text


async def test_sec6_idempotency_replay_same_key_one_record(adm):
    day = date.today() + timedelta(days=5)
    body = {
        "date_from": day.isoformat(),
        "date_to": day.isoformat(),
        "name": f"QA idem {uuid.uuid4().hex[:6]}",
    }
    pre = await _special_days(adm)
    if _special_day_covers(pre, day):
        pytest.skip("date already a holiday")
    key = _key()
    first = await write(adm, "POST", f"{B}/special-days", json_body=body, key=key)
    second = await write(adm, "POST", f"{B}/special-days", json_body=body, key=key)
    try:
        assert first.status_code == 201, first.text
        assert second.status_code == first.status_code
        assert second.json() == first.json()
        mine = [s for s in await _special_days(adm) if s["name"] == body["name"]]
        assert len(mine) == 1
        # same key, different body -> 422 E-SEC-4
        other = await write(
            adm,
            "POST",
            f"{B}/special-days",
            json_body={**body, "name": body["name"] + "!"},
            key=key,
        )
        assert other.status_code == 422 and _code(other) == "E-SEC-4", other.text
    finally:
        await drop_holiday(adm, first.json()["id"])


@pytest.mark.parametrize(("method", "path", "body"), WRITE_CALLS[:4])
async def test_sec6_missing_or_malformed_key_rejected_with_400(adm, method, path, body):
    r = await write(adm, method, path, json_body=body(), key=None)
    assert r.status_code == 400 and _code(r) == "E-SEC-2", r.text
    r = await write(adm, method, path, json_body=body(), key="not-a-uuid")
    assert r.status_code == 400 and _code(r) == "E-SEC-2", r.text


async def test_sec6_concurrent_same_key_creates_single_record(adm):
    day = date.today() + timedelta(days=6)
    if _special_day_covers(await _special_days(adm), day):
        pytest.skip("date already a holiday")
    body = {
        "date_from": day.isoformat(),
        "date_to": day.isoformat(),
        "name": f"QA conc {uuid.uuid4().hex[:6]}",
    }
    key = _key()
    results = await asyncio.gather(
        *(write(adm, "POST", f"{B}/special-days", json_body=body, key=key) for _ in range(5))
    )
    created = [r for r in results if r.status_code == 201]
    try:
        assert created, [r.status_code for r in results]
        assert all(
            r.status_code == 201 or (r.status_code == 409 and _code(r) == "E-SEC-3")
            for r in results
        )
        assert len({r.json()["id"] for r in created}) == 1
        assert len([s for s in await _special_days(adm) if s["name"] == body["name"]]) == 1
    finally:
        await drop_holiday(adm, created[0].json()["id"])


async def _audit_rows(where="TRUE", params=None):
    async with engine.connect() as conn:
        res = await conn.execute(
            text(f"SELECT * FROM audit_log WHERE {where} ORDER BY id DESC"), params or {}
        )
        return [dict(r._mapping) for r in res]


async def test_sec7_audit_row_written_for_config_write_and_not_for_failure(adm):
    day = date.today() + timedelta(days=7)
    if _special_day_covers(await _special_days(adm), day):
        pytest.skip("date already a holiday")
    name = f"QA audit {uuid.uuid4().hex[:6]}"
    r = await add_holiday(adm, day, name)
    assert r.status_code == 201, r.text
    try:
        rows = await _audit_rows(
            "action = 'config.special_day.create' AND detail::text LIKE :n", {"n": f"%{name}%"}
        )
        assert len(rows) == 1, "exactly one audit row expected in the same transaction as the write"
        row = rows[0]
        assert row["actor_type"] == "admin" and row["request_id"] and row["ip"] is not None
        before = len(await _audit_rows("action = 'config.special_day.create'"))
        dup = await add_holiday(adm, day, "QA trùng audit")
        assert dup.status_code == 409
        assert len(await _audit_rows("action = 'config.special_day.create'")) == before, (
            "failed write must not audit"
        )
    finally:
        await drop_holiday(adm, r.json()["id"])


async def test_sec7_audit_log_is_append_only_at_database_level(adm):
    _, sid = await free_holiday(adm, lambda d: True)
    await drop_holiday(adm, sid)
    rows = await _audit_rows()
    assert rows, "audit_log is empty after a config write"
    target = rows[0]["id"]
    async with engine.connect() as conn:
        triggers = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE tgrelid = 'audit_log'::regclass AND NOT tgisinternal"
                )
            )
        ).scalar_one()
    assert triggers >= 1, (
        "no trigger on audit_log in the test DB "
        "(create_all skips migrations: install via a DDL event or run alembic)"
    )
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE audit_log SET action = 'tampered' WHERE id = :i"), {"i": target}
            )
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM audit_log WHERE id = :i"), {"i": target})
    # rows older than 12 months may be purged (retention job)
    async with engine.begin() as conn:
        old_id = (
            await conn.execute(
                text(
                    "INSERT INTO audit_log "
                    "(at, actor_type, actor_label, action, entity_type, entity_code, detail) "
                    "VALUES (now() - interval '13 months', 'system', 'qa', 'qa.retention', "
                    "'qa', 'QA-OLD', '{}'::jsonb) "
                    "RETURNING id"
                )
            )
        ).scalar_one()
        deleted = await conn.execute(text("DELETE FROM audit_log WHERE id = :i"), {"i": old_id})
        assert deleted.rowcount == 1
    assert await _audit_rows("id = :i", {"i": target}), "recent audit row must still exist"


FORBIDDEN_FIELDS = ("hashed_password", "password", "access_token", "refresh_token", "secret")


async def test_sec8_no_secrets_in_responses(adm, customer_c):
    paths = [
        f"{API}/admin/users",
        f"{B}/resources",
        f"{B}/prices",
        f"{B}/special-days",
        f"{API}/auth/me",
    ]
    for client in (adm, customer_c):
        for path in paths:
            r = await client.get(path)
            if r.status_code != 200:
                continue
            body = r.text.lower()
            for word in FORBIDDEN_FIELDS:
                assert word not in body, f"{path} leaks '{word}'"
    async with _http() as c:  # login response body must not contain tokens either (cookies only)
        r = await c.post(
            f"{API}/auth/login",
            json={"email": settings.FIRST_ADMIN_EMAIL, "password": settings.FIRST_ADMIN_PASSWORD},
        )
        assert "access_token" not in r.text and "refresh_token" not in r.text


async def test_sec8_phone_numbers_masked_in_lists(adm, customer_c):
    """Q1: the users list returns `phone_masked` instead of `phone` (S12 / BR-021)."""
    users = await adm.get(f"{API}/admin/users")
    assert users.status_code == 200
    assert "0912345678" not in users.text, "full phone number visible in the users list"
    rows = users.json()
    assert rows and all("phone" not in row for row in rows), "`phone` must be replaced"
    masked = [row["phone_masked"] for row in rows if row.get("phone_masked")]
    assert masked, "no `phone_masked` values returned"
    assert all(re.search(r"[xX*•]", m) for m in masked), masked


# ---------------------------------------------------------------------------
# 5. Shared infrastructure (B3, B7, B8) and architecture (C5)
# ---------------------------------------------------------------------------


async def test_b3_body_over_64kb_is_413(adm):
    big = {"name": "x" * 70_000}
    r = await write(adm, "POST", f"{B}/resources", json_body=big)
    assert r.status_code == 413, r.status_code


async def test_b7_request_id_generated_and_echoed(anon_c):
    r = await anon_c.get(f"{API}/venue/config")
    assert r.headers.get("X-Request-ID")
    rid = _key()
    r = await anon_c.get(f"{API}/venue/config", headers={"X-Request-ID": rid})
    assert r.headers.get("X-Request-ID") == rid


async def test_b8_business_error_shape_is_code_and_message(adm):
    table = (await _get_prices(adm))["prices"]
    r = await write(adm, "PUT", f"{B}/prices", json_body={"version": 10**6, "prices": table})
    detail = r.json()["detail"]
    assert isinstance(detail, dict) and set(detail) >= {"code", "message"}, r.text


ENGINE_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "booking_engine"
MODULES_DIR = ENGINE_DIR.parent


def test_c5_engine_does_not_import_other_modules():
    assert ENGINE_DIR.is_dir(), "app/modules/booking_engine is missing"
    pat = re.compile(r"^\s*(?:from|import)\s+app\.modules\.(\w+)", re.M)
    bad = []
    for f in ENGINE_DIR.rglob("*.py"):
        for mod in pat.findall(f.read_text(encoding="utf-8")):
            if mod != "booking_engine":
                bad.append(f"{f.relative_to(MODULES_DIR)} imports app.modules.{mod}")
    assert not bad, bad


def test_c5_other_modules_only_use_engine_facade():
    pat = re.compile(r"^\s*(?:from|import)\s+app\.modules\.booking_engine(?:\.(\w+))?", re.M)
    bad = []
    for f in MODULES_DIR.rglob("*.py"):
        if ENGINE_DIR in f.parents:
            continue
        for sub in pat.findall(f.read_text(encoding="utf-8")):
            if sub not in ("api", "dto", ""):
                bad.append(f"{f.relative_to(MODULES_DIR)} imports booking_engine.{sub}")
    assert not bad, bad


def test_c5_booking_schema_tables_have_no_foreign_key_outside_schema():
    from app.core.db import Base

    tables = [t for t in Base.metadata.tables.values() if t.schema == "booking"]
    assert tables, "no ORM tables in schema 'booking'"
    bad = [
        f"{t.fullname} -> {fk.target_fullname}"
        for t in tables
        for fk in t.foreign_keys
        if not fk.target_fullname.startswith("booking.")
    ]
    assert not bad, bad
    missing = [t.fullname for t in tables if t.name != "tenant" and "tenant_id" not in t.columns]
    assert not missing, f"tables without tenant_id: {missing}"

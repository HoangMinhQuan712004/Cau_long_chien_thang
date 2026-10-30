"""T-005 mục D: cấu hình sân, giờ hoạt động, bảng giá, ngày Lễ/Tết, báo giá."""

import uuid
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine.testing import make_allocation, release_allocation
from tests.conftest import API, idem

BK = f"{API}/booking"
PEAKS = [["05:00", "07:00"], ["17:00", "21:00"]]


def today() -> date:
    return datetime.now(settings.tz).date()


def next_weekday(start: date, weekday: int) -> date:
    """Ngày gần nhất ≥ ``start`` có thứ ``weekday`` (0 = Thứ 2), tránh Lễ/Tết seed năm 2026."""
    d = start + timedelta(days=(weekday - start.weekday()) % 7)
    while d.year == 2026 and d.month in (1, 2, 4, 5, 9):
        d += timedelta(days=7)
    return d


def unique_name(prefix: str = "Sân") -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]}"


async def create_resource(client, **overrides) -> dict:
    body = {
        "name": unique_name(),
        "resource_type_code": "thuong",
        "open_time": "05:00",
        "close_time": "22:00",
        "peak_bands": PEAKS,
        **overrides,
    }
    r = await client.post(f"{BK}/resources", json=body, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


async def get_resource(client, code: str) -> dict:
    r = await client.get(f"{BK}/resources")
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["code"] == code)


async def allocate(code: str, day: date, start_h: int, end_h: int, owner: str) -> int:
    start = datetime.combine(day, time(start_h), settings.tz)
    end = datetime.combine(day, time(0), settings.tz) + timedelta(hours=end_h)
    async with SessionLocal() as s:
        alloc_id = await make_allocation(s, code, start, end, owner_code=owner)
        await s.commit()
    return alloc_id


async def release(alloc_id: int) -> None:
    async with SessionLocal() as s:
        await release_allocation(s, alloc_id)
        await s.commit()


# ------------------------------------------------------------------ danh sách + seed


async def test_list_resources_seeded_from_prototype(admin, staff):
    r = await staff.get(f"{BK}/resources")  # quầy xem được danh mục sân
    assert r.status_code == 200, r.text
    data = r.json()
    by_code = {i["code"]: i for i in data["items"]}
    assert {"S01", "S02", "S03", "S04", "S05", "S06"} <= set(by_code)
    assert by_code["S05"]["resource_type_code"] == "vip"
    assert by_code["S05"]["schedule"]["open_time"] == "06:00"
    assert by_code["S01"]["schedule"]["peak_bands"] == PEAKS
    assert by_code["S06"]["is_active"] is False
    assert [t["code"] for t in data["resource_types"]] == ["thuong", "vip"]
    assert "id" not in by_code["S01"]


# ------------------------------------------------------------------ thêm / sửa sân (D6)


async def test_create_resource_assigns_code_and_audits(admin):
    name = unique_name()
    r = await admin.post(
        f"{BK}/resources",
        json={
            "name": f"  {name}  ",
            "resource_type_code": "vip",
            "open_time": "06:00",
            "close_time": "24:00",
            "peak_bands": [["17:00", "21:00"], ["06:00", "07:00"]],
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["code"].startswith("S") and body["code"][1:].isdigit()
    assert body["name"] == name
    assert body["version"] == 1 and body["is_active"] is True
    assert body["schedule"]["effective_from"] == today().isoformat()
    assert body["schedule"]["close_time"] == "24:00"
    # cao điểm được sắp xếp
    assert body["schedule"]["peak_bands"] == [["06:00", "07:00"], ["17:00", "21:00"]]
    assert body["pending_schedule"] is None

    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "config.resource.create", AuditLog.entity_code == body["code"]
            )
        )
    assert row is not None
    assert row.actor_type == "admin" and row.actor_label == "Admin"
    assert row.request_id == r.headers["x-request-id"]


@pytest.mark.parametrize(
    ("override", "status", "code"),
    [
        ({"name": "   "}, 422, "E-CFG-1"),
        ({"name": "x" * 51}, 422, "E-CFG-1"),
        ({"close_time": "05:30"}, 422, "E-CFG-2"),
        ({"open_time": "10:00", "close_time": "10:30"}, 422, "E-CFG-2"),
        ({"peak_bands": [["05:00", "05:00"]]}, 422, "E-CFG-5"),
        ({"peak_bands": [["04:00", "07:00"]]}, 422, "E-CFG-5"),
        ({"peak_bands": [["17:00", "21:00"], ["20:00", "22:00"]]}, 422, "E-CFG-5"),
        ({"resource_type_code": "khong-co"}, 422, "E-CFG-9"),
    ],
)
async def test_create_resource_validation(admin, override, status, code):
    body = {
        "name": unique_name(),
        "resource_type_code": "thuong",
        "open_time": "05:00",
        "close_time": "22:00",
        "peak_bands": PEAKS,
        **override,
    }
    r = await admin.post(f"{BK}/resources", json=body, headers=idem())
    assert r.status_code == status, r.text
    assert r.json()["detail"]["code"] == code
    assert r.json()["detail"]["message"]


async def test_duplicate_name_case_insensitive(admin):
    first = await create_resource(admin)
    r = await admin.post(
        f"{BK}/resources",
        json={
            "name": first["name"].upper(),
            "resource_type_code": "thuong",
            "open_time": "05:00",
            "close_time": "22:00",
        },
        headers=idem(),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "E-CFG-1"

    other = await create_resource(admin)
    r = await admin.patch(
        f"{BK}/resources/{other['code']}",
        json={"version": other["version"], "name": first["name"].lower()},
        headers=idem(),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "E-CFG-1"


async def test_bad_time_format_rejected(admin):
    body = {"name": unique_name(), "resource_type_code": "thuong"}
    for bad in ("5:00", "05:15", "25:00", "24:30"):
        r = await admin.post(
            f"{BK}/resources",
            json={**body, "open_time": "05:00", "close_time": bad},
            headers=idem(),
        )
        assert r.status_code == 422, bad


async def test_update_basic_fields_and_version(admin):
    res = await create_resource(admin)
    new_name = unique_name("Sân VIP")
    r = await admin.patch(
        f"{BK}/resources/{res['code']}",
        json={"version": 1, "name": new_name, "resource_type_code": "vip"},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == new_name and body["resource_type_code"] == "vip"
    assert body["version"] == 2
    assert body["pending_schedule"] is None  # không đổi giờ

    # Bản cũ (version 1) -> máy khác vừa sửa
    r = await admin.patch(
        f"{BK}/resources/{res['code']}", json={"version": 1, "name": "abc"}, headers=idem()
    )
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-CFG-7",
        "message": "Dữ liệu vừa được thay đổi ở máy khác. Tải lại để xem bản mới nhất.",
    }

    r = await admin.patch(f"{BK}/resources/S99X", json={"version": 1}, headers=idem())
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "E-NOT-FOUND"


# ------------------------------------------------------------------ giờ hiệu lực từ mai (D4)


async def test_hours_change_applies_from_tomorrow(admin):
    res = await create_resource(admin)
    code = res["code"]
    tomorrow = today() + timedelta(days=1)
    r = await admin.patch(
        f"{BK}/resources/{code}",
        json={"version": 1, "open_time": "06:00", "peak_bands": [["17:00", "20:00"]]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schedule"]["open_time"] == "05:00"  # hôm nay giữ nguyên
    assert body["pending_schedule"] == {
        "effective_from": tomorrow.isoformat(),
        "open_time": "06:00",
        "close_time": "22:00",
        "peak_bands": [["17:00", "20:00"]],
    }

    # Sửa lần nữa trong ngày: ghi đè bản chờ của ngày mai (base = bản chờ)
    r = await admin.patch(
        f"{BK}/resources/{code}",
        json={"version": 2, "close_time": "23:00"},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    pending = r.json()["pending_schedule"]
    assert (pending["open_time"], pending["close_time"]) == ("06:00", "23:00")
    assert pending["effective_from"] == tomorrow.isoformat()

    # Báo giá: hôm nay mở 05:00, ngày mai mở 06:00
    q = {"resource_code": code, "start_hour": 5, "end_hour": 6}
    r = await admin.post(f"{BK}/quote", json={**q, "date": today().isoformat()})
    assert r.status_code == 200, r.text
    r = await admin.post(f"{BK}/quote", json={**q, "date": tomorrow.isoformat()})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-10"

    # Quay về đúng lịch hiện tại -> bỏ bản chờ
    r = await admin.patch(
        f"{BK}/resources/{code}",
        json={"version": 3, "open_time": "05:00", "close_time": "22:00", "peak_bands": PEAKS},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert r.json()["pending_schedule"] is None


async def test_hours_change_blocked_by_bookings_outside_new_hours(admin):
    res = await create_resource(admin)
    code = res["code"]
    day = today() + timedelta(days=3)
    ids = [
        await allocate(code, day, 5, 6, "BK-TEST-001"),
        await allocate(code, day, 20, 22, "BK-TEST-002"),
        await allocate(code, day, 9, 10, "BK-TEST-003"),  # trong giờ mới -> không vướng
    ]
    try:
        r = await admin.patch(
            f"{BK}/resources/{code}",
            json={"version": 1, "open_time": "06:00", "close_time": "21:00", "peak_bands": []},
            headers=idem(),
        )
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "E-CFG-3"
        assert "2 khung" in detail["message"]
        assert [i["code"] for i in detail["items"]] == ["BK-TEST-001", "BK-TEST-002"]
        assert detail["items"][1] == {
            "code": "BK-TEST-002",
            "date": day.isoformat(),
            "start_time": "20:00",
            "end_time": "22:00",
        }
        assert detail["more"] == 0
        assert (await get_resource(admin, code))["pending_schedule"] is None
    finally:
        for i in ids:
            await release(i)

    r = await admin.patch(
        f"{BK}/resources/{code}",
        json={"version": 1, "open_time": "06:00", "close_time": "21:00", "peak_bands": []},
        headers=idem(),
    )
    assert r.status_code == 200, r.text


async def test_hours_conflict_list_truncated_to_six(admin):
    res = await create_resource(admin)
    code = res["code"]
    ids = [
        await allocate(code, today() + timedelta(days=d), 5, 6, f"BK-T-{d:03d}")
        for d in range(1, 9)
    ]
    try:
        r = await admin.patch(
            f"{BK}/resources/{code}",
            json={"version": 1, "open_time": "06:00", "peak_bands": []},
            headers=idem(),
        )
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert len(detail["items"]) == 6 and detail["more"] == 2
    finally:
        for i in ids:
            await release(i)


# ------------------------------------------------------------------ ngừng sân (D5)


async def test_deactivate_blocked_while_bookings_remain(admin):
    res = await create_resource(admin)
    code = res["code"]
    alloc = await allocate(code, today(), 21, 22, "BK-TEST-101")
    try:
        r = await admin.patch(
            f"{BK}/resources/{code}", json={"version": 1, "is_active": False}, headers=idem()
        )
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "E-CFG-4"
        assert detail["items"][0]["code"] == "BK-TEST-101"
    finally:
        await release(alloc)

    r = await admin.patch(
        f"{BK}/resources/{code}", json={"version": 1, "is_active": False}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    # Sân ngừng: không bán
    r = await admin.post(
        f"{BK}/quote",
        json={"resource_code": code, "date": today().isoformat(), "start_hour": 8, "end_hour": 9},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-10"


# ------------------------------------------------------------------ bảng giá (D7)


async def test_price_table_get_and_update(admin):
    r = await admin.get(f"{BK}/prices")
    assert r.status_code == 200, r.text
    table = r.json()
    assert len(table["prices"]) == 12
    cell = {
        (p["resource_type_code"], p["day_type"], p["band"]): p["price_per_hour"]
        for p in table["prices"]
    }
    assert cell[("thuong", "weekday", "offpeak")] == 150_000
    assert cell[("vip", "holiday", "peak")] == 420_000

    new_prices = [{**p, "price_per_hour": p["price_per_hour"] + 2_000} for p in table["prices"]]
    r = await admin.put(
        f"{BK}/prices", json={"version": table["version"], "prices": new_prices}, headers=idem()
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == table["version"] + 1
    assert saved["updated_by"] == "Admin" and saved["updated_at"]

    # Bản cũ -> 409 E-CFG-7
    r = await admin.put(
        f"{BK}/prices",
        json={"version": table["version"], "prices": table["prices"]},
        headers=idem(),
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-CFG-7"

    # Trả lại giá gốc cho các test khác
    r = await admin.put(
        f"{BK}/prices",
        json={"version": saved["version"], "prices": table["prices"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text

    async with SessionLocal() as s:
        audit_row = await s.scalar(
            select(AuditLog)
            .where(AuditLog.action == "config.price.update")
            .order_by(AuditLog.id.desc())
        )
    # Lịch sử thao tác: 1 lần lưu = 1 dòng, mỗi ô đổi "Tên ô: trước → sau" (giá đã định dạng)
    change = audit_row.detail["changes"][0]

    def money(v: str) -> int:
        return int(v.removesuffix(" ₫").replace(".", ""))

    assert money(change["after"]) == money(change["before"]) - 2_000
    assert " · " in change["field"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda prices: [{**prices[0], "price_per_hour": 0}, *prices[1:]],
        lambda prices: [{**prices[0], "price_per_hour": -1000}, *prices[1:]],
        lambda prices: prices[1:],  # thiếu ô
        lambda prices: [*prices, prices[0]],  # trùng ô
    ],
)
async def test_price_table_invalid_cells(admin, mutate):
    table = (await admin.get(f"{BK}/prices")).json()
    r = await admin.put(
        f"{BK}/prices",
        json={"version": table["version"], "prices": mutate(table["prices"])},
        headers=idem(),
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "E-CFG-6"


async def test_price_must_be_integer(admin):
    table = (await admin.get(f"{BK}/prices")).json()
    for bad in (150000.5, "150000"):
        prices = [{**table["prices"][0], "price_per_hour": bad}, *table["prices"][1:]]
        r = await admin.put(
            f"{BK}/prices", json={"version": table["version"], "prices": prices}, headers=idem()
        )
        assert r.status_code == 422, bad


# ------------------------------------------------------------------ Lễ / Tết (D8)


async def test_special_days_crud_and_overlap(admin):
    r = await admin.get(f"{BK}/special-days", params={"year": 2026})
    assert r.status_code == 200
    names = [d["name"] for d in r.json()]
    assert "Tết Nguyên đán" in names and "Quốc khánh" in names

    r = await admin.post(
        f"{BK}/special-days",
        json={"date_from": "2031-04-30", "date_to": "2031-05-01", "name": "Lễ 30/4 – 1/5"},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["day_type"] == "holiday"

    r = await admin.post(
        f"{BK}/special-days",
        json={"date_from": "2031-05-01", "name": "Trùng"},
        headers=idem(),
    )
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-CFG-8",
        "message": "Ngày 01/05 đã nằm trong Lễ 30/4 – 1/5.",
    }

    for body in (
        {"date_from": "2031-05-03", "date_to": "2031-05-02", "name": "Ngược"},
        {"date_from": "2031-12-31", "date_to": "2032-01-01", "name": "Qua năm"},
        {"date_from": "2031-06-01", "name": ""},
        {"date_from": "2031-06-01", "name": "x" * 101},
    ):
        r = await admin.post(f"{BK}/special-days", json=body, headers=idem())
        assert r.status_code == 422, body

    r = await admin.delete(f"{BK}/special-days/{created['id']}", headers=idem())
    assert r.status_code == 204
    r = await admin.delete(f"{BK}/special-days/{created['id']}", headers=idem())
    assert r.status_code == 404
    r = await admin.get(f"{BK}/special-days", params={"year": 2031})
    assert r.json() == []


# ------------------------------------------------------------------ báo giá (D1–D3)


async def test_quote_prices_by_band_and_day_type(admin, staff):
    weekday = next_weekday(today() + timedelta(days=1), 1)  # Thứ 3
    r = await staff.post(
        f"{BK}/quote",
        json={
            "resource_code": "S01",
            "date": weekday.isoformat(),
            "start_hour": 16,
            "end_hour": 18,
        },
    )
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["day_type"] == "weekday"
    assert [(i["start_time"], i["label"], i["price"]) for i in q["items"]] == [
        ("16:00", "Thấp điểm", 150_000),
        ("17:00", "Cao điểm", 180_000),
    ]
    assert q["total_amount"] == 330_000

    sunday = next_weekday(today() + timedelta(days=1), 6)
    r = await staff.post(
        f"{BK}/quote",
        json={"resource_code": "S05", "date": sunday.isoformat(), "start_hour": 6, "end_hour": 8},
    )
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["day_type"] == "weekend"
    assert [i["price"] for i in q["items"]] == [400_000, 350_000]  # VIP cuối tuần


async def test_quote_partial_peak_and_holiday(admin):
    res = await create_resource(admin, peak_bands=[["17:30", "21:00"]])
    weekday = next_weekday(today() + timedelta(days=1), 2)
    r = await admin.post(
        f"{BK}/quote",
        json={
            "resource_code": res["code"],
            "date": weekday.isoformat(),
            "start_hour": 17,
            "end_hour": 18,
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert (item["band"], item["label"], item["price"]) == ("partial", "Một phần cao điểm", 165_000)

    # Ngày Lễ thắng cuối tuần
    holiday = date(2031, 9, 2)
    r = await admin.post(
        f"{BK}/special-days",
        json={"date_from": holiday.isoformat(), "name": "Quốc khánh 2031"},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    holiday_id = r.json()["id"]
    try:
        r = await admin.post(
            f"{BK}/quote",
            json={
                "resource_code": "S01",
                "date": holiday.isoformat(),
                "start_hour": 8,
                "end_hour": 9,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["day_type"] == "holiday"
        assert r.json()["total_amount"] == 225_000
    finally:
        r = await admin.delete(f"{BK}/special-days/{holiday_id}", headers=idem())
        assert r.status_code == 204


async def test_quote_not_sold(admin):
    day = (today() + timedelta(days=2)).isoformat()
    cases = [
        {"resource_code": "S05", "date": day, "start_hour": 5, "end_hour": 6},  # S05 mở 06:00
        {"resource_code": "S01", "date": day, "start_hour": 21, "end_hour": 23},  # đóng 22:00
        {"resource_code": "S06", "date": day, "start_hour": 8, "end_hour": 9},  # sân ngừng
        {"resource_code": "S01", "date": day, "start_hour": 9, "end_hour": 9},
    ]
    for body in cases:
        r = await admin.post(f"{BK}/quote", json=body)
        assert r.status_code == 422, body
        assert r.json()["detail"]["code"] == "E-CFG-10"
    r = await admin.post(
        f"{BK}/quote", json={"resource_code": "S77", "date": day, "start_hour": 8, "end_hour": 9}
    )
    assert r.status_code == 404

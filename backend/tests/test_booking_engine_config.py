"""T-005 mục D: cấu hình sân, giờ hoạt động, bảng giá, ngày Lễ/Tết, báo giá."""

import asyncio
import uuid
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.core.permissions import DEFAULT_ROLE_PERMS, Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.config_service import lock_live_resources
from app.modules.booking_engine.models import Allocation, Booking, BookingOrder, Hold, Resource
from app.modules.booking_engine.testing import make_allocation, release_allocation
from tests.conftest import API, idem
from tests.helpers_booking import FD, book, safe_hour, set_legacy_schedule, temp
from tests.helpers_web import WEB, checkout

BK = f"{API}/booking"
PEAKS = [["05:00", "07:00"], ["17:00", "21:00"]]


@pytest.fixture(autouse=True)
async def cleanup_fake_bookings():
    """Dọn booking / đơn / chỗ chiếm giả ``BK-TEST-…`` (``make_allocation``) sau mỗi test, để test
    khác quét bảng booking không gặp dòng giả (gợi ý của QA, T-019)."""
    yield
    async with SessionLocal() as s:
        await s.execute(
            delete(Allocation).where(
                Allocation.booking_id.in_(select(Booking.id).where(Booking.code.like("BK-TEST-%")))
            )
        )
        order_ids = select(Booking.order_id).where(Booking.code.like("BK-TEST-%"))
        ids = list(await s.scalars(order_ids))
        await s.execute(delete(Booking).where(Booking.code.like("BK-TEST-%")))
        if ids:
            await s.execute(delete(BookingOrder).where(BookingOrder.id.in_(ids)))
        await s.commit()


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
        ({"close_time": "05:00"}, 422, "E-CFG-2"),
        ({"open_time": "10:00", "close_time": "09:00"}, 422, "E-CFG-2"),
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


# Người dùng chốt 2026-11-06: giờ mới chỉ tròn giờ; lịch cũ có :30 vẫn sửa được phần khác
@pytest.mark.parametrize(
    "hours",
    [
        {"open_time": "05:30"},
        {"close_time": "21:30"},
        {"peak_bands": [["17:30", "21:00"]]},
        {"peak_bands": [["17:00", "20:30"]]},
    ],
)
async def test_new_hours_must_be_whole(admin, hours):
    body = {
        "name": unique_name(),
        "resource_type_code": "thuong",
        "open_time": "05:00",
        "close_time": "22:00",
        "peak_bands": PEAKS,
        **hours,
    }
    r = await admin.post(f"{BK}/resources", json=body, headers=idem())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-12", r.text
    assert "tròn giờ" in r.json()["detail"]["message"]

    res = await create_resource(admin)
    r = await admin.patch(
        f"{BK}/resources/{res['code']}", json={"version": res["version"], **hours}, headers=idem()
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-12", r.text


async def test_legacy_half_hour_schedule_can_still_edit_other_fields(admin):
    res = await create_resource(admin)
    code = res["code"]
    legacy = [["05:30", "07:00"], ["17:30", "21:00"]]
    await set_legacy_schedule(code, open_minute=5 * 60 + 30, peak_bands=legacy)

    async def patch(**body):
        current = await get_resource(admin, code)
        return await admin.patch(
            f"{BK}/resources/{code}", json={"version": current["version"], **body}, headers=idem()
        )

    # Sửa tên: không đụng giờ
    r = await patch(name=unique_name())
    assert r.status_code == 200, r.text
    assert r.json()["schedule"]["open_time"] == "05:30"
    # Form gửi lại nguyên giá trị cũ kèm đổi giờ đóng cửa: giá trị cũ không bị bắt lỗi
    r = await patch(open_time="05:30", close_time="21:00", peak_bands=legacy)
    assert r.status_code == 200, r.text
    assert r.json()["pending_schedule"]["close_time"] == "21:00"
    assert r.json()["pending_schedule"]["open_time"] == "05:30", "giữ giá trị cũ"
    # Đổi sang một giá trị :30 khác: chặn
    r = await patch(open_time="06:30")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-12", r.text
    r = await patch(peak_bands=[["17:30", "20:30"]])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-CFG-12", r.text
    # Đổi về tròn giờ: được
    r = await patch(open_time="06:00", peak_bands=PEAKS[1:])
    assert r.status_code == 200, r.text


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
    res = await create_resource(admin)
    # Lịch cũ có :30 vẫn tính "một phần cao điểm" (API mới chỉ nhận tròn giờ)
    await set_legacy_schedule(res["code"], peak_bands=[["17:30", "21:00"]])
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
        f"{BK}/quote", json={"resource_code": "SX9999", "date": day, "start_hour": 8, "end_hour": 9}
    )
    assert r.status_code == 404


# ------------------------------------------------------------------ xóa sân

DELETE_PERM = Perm.BOOKING_RESOURCES_DELETE


async def delete_court(client, code: str):
    return await client.delete(f"{BK}/resources/{code}", headers=idem())


def event_body(code: str, day: date, start_hour: int, end_hour: int, name: str) -> dict:
    return {
        "resource_codes": [code],
        "date": day.isoformat(),
        "start_hour": start_hour,
        "end_hour": end_hour,
        "name": name,
        "capacity": 8,
        "ticket_price": 50_000,
    }


async def court_id(code: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(Resource.id).where(Resource.code == code))


async def test_delete_resource_permission_admin_staff_default_and_granted(admin, staff, anon):
    assert DELETE_PERM not in DEFAULT_ROLE_PERMS["staff"], "NV mặc định tắt"
    res = await create_resource(admin)
    assert (await delete_court(anon, res["code"])).status_code == 401
    r = await delete_court(staff, res["code"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2"
    # Hiện ở tab Phân quyền, Admin bật được cho NV
    roles = (await admin.get(f"{API}/admin/roles")).json()
    keys = [p["key"] for g in roles["groups"] for p in g["perms"]]
    assert DELETE_PERM.value in keys and DELETE_PERM.value not in roles["defaults"]["staff"]
    async with SessionLocal() as s:
        s.add(RolePermission(role="staff", perm=DELETE_PERM.value))
        await s.commit()
    try:
        assert (await delete_court(staff, res["code"])).status_code == 204
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(RolePermission).where(RolePermission.perm == DELETE_PERM.value))
            await s.commit()
    other = await create_resource(admin)
    assert (await delete_court(admin, other["code"])).status_code == 204
    evil = await admin.delete(
        f"{BK}/resources/S01", headers={**idem(), "Origin": "https://evil.example"}
    )
    assert evil.status_code == 403


async def test_delete_resource_blocked_while_schedule_unfinished(admin, anon):
    res = await create_resource(admin)
    code = res["code"]
    day = today() + timedelta(days=20)
    # Đã kết thúc: không chặn
    past = await allocate(code, today() - timedelta(days=1), 8, 9, "BK-TEST-DEL-0")
    booked = await allocate(code, day, 8, 9, "BK-TEST-DEL-1")
    r = await delete_court(admin, code)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "E-CFG-11" and detail["count"] == 1
    assert detail["message"] == "Sân còn 1 lịch sắp tới, hãy xử lý trước khi xóa."
    await release(booked)
    await release(past)

    # Sự kiện
    r = await admin.post(
        f"{BK}/sessions",
        json=event_body(code, day, 10, 12, "Sự kiện chặn xóa"),
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    assert (await delete_court(admin, code)).status_code == 409
    gone = await admin.request(
        "DELETE",
        f"{BK}/sessions/{r.json()['code']}",
        json={"version": r.json()["version"]},
        headers=idem(),
    )
    assert gone.status_code == 200, gone.text

    # Giữ chỗ online còn hạn chặn; hết hạn thì không
    held = await checkout(anon, [(code, 9)], day=day)
    assert held.status_code == 201, held.text
    r = await delete_court(admin, code)
    assert r.status_code == 409 and r.json()["detail"]["count"] == 1
    rid = await court_id(code)
    async with SessionLocal() as s:
        hold_ids = select(Allocation.hold_id).where(Allocation.resource_id == rid)
        await s.execute(
            update(Hold)
            .where(Hold.id.in_(hold_ids))
            .values(expires_at=datetime.now(settings.tz) - timedelta(days=1))
        )
        await s.commit()
    assert (await delete_court(admin, code)).status_code == 204


async def test_deleted_resource_gone_everywhere_but_history_keeps_name(admin, staff, anon):
    res = await create_resource(admin, open_time="00:00", close_time="24:00", peak_bands=[])
    code, name = res["code"], res["name"]
    day = today() + timedelta(days=21)
    # Đơn đã có: coi như đã xong (tắt chỗ chiếm), vẫn phải tra được sau khi xóa
    hour = await safe_hour()  # đặt quầy chỉ cho hôm nay
    done = await book(admin, code, hour, customer=temp("Khách Cũ"))
    assert done.status_code == 201, done.text
    async with SessionLocal() as s:
        await s.execute(
            update(Allocation)
            .where(Allocation.owner_code == done.json()["code"])
            .values(active=False)
        )
        await s.commit()
    assert (await delete_court(admin, code)).status_code == 204

    # Danh sách, lịch quản trị + khách, chi tiết, thống kê
    assert code not in [i["code"] for i in (await admin.get(f"{BK}/resources")).json()["items"]]
    for shown_day in (today(), day):  # hôm nay có đơn cũ: không còn khối mồ côi
        cal = (await admin.get(f"{BK}/calendar", params={"date": shown_day.isoformat()})).json()
        assert code not in [r["code"] for r in cal["resources"]]
        assert all(code not in b["resource_codes"] for b in cal["blocks"])
    public = await anon.get(f"{WEB}/calendar", params={"date": day.isoformat()})
    assert public.status_code == 200 and code not in public.text
    assert (await admin.get(f"{BK}/resources/{code}/detail")).status_code == 404

    # Không tạo được gì mới
    body = {"resource_code": code, "date": day.isoformat(), "start_hour": 9, "end_hour": 10}
    assert (await admin.post(f"{BK}/quote", json=body)).status_code == 404
    assert (await book(admin, code, hour, customer=temp())).status_code == 404
    r = await admin.post(
        f"{FD}/recurring",
        json={
            "resource_code": code,
            "weekdays": [day.isoweekday()],
            "start_hour": 9,
            "end_hour": 10,
            "date_from": day.isoformat(),
            "date_to": day.isoformat(),
            "customer": temp(),
        },
        headers=idem(),
    )
    assert r.status_code == 404, r.text
    r = await admin.post(
        f"{BK}/sessions",
        json=event_body(code, day, 9, 10, "Không được"),
        headers=idem(),
    )
    assert r.status_code == 404, r.text
    online = await checkout(anon, [(code, 9)], day=day)
    assert online.status_code >= 400 and online.status_code != 500, online.text
    r = await admin.patch(
        f"{BK}/resources/{code}", json={"version": 2, "name": "X"}, headers=idem()
    )
    assert r.status_code == 404
    assert (await delete_court(admin, code)).status_code == 404, "xóa lần 2"
    assert (await delete_court(admin, "S999")).status_code == 404, "mã không có"

    # Lịch sử: đơn cũ + tên sân vẫn đúng
    item = await staff.get(f"{BK}/items/{done.json()['code']}")
    assert item.status_code == 200 and code in item.json()["schedule"]["resource_codes"]
    async with SessionLocal() as s:
        assert (await engine.resource_names(s))[code] == name
    # Mã không dùng lại; tên được dùng lại
    fresh = await create_resource(admin, name=name)
    assert int(fresh["code"][1:]) > int(code[1:])

    # Lịch sử thao tác
    rows = await admin.get(f"{API}/admin/audit-log", params={"action": "config.resource.delete"})
    row = next(i for i in rows.json()["items"] if i["target"]["code"] == code)
    assert row["action_label"] == "Xóa sân" and row["actor"] == "admin"
    assert row["target"]["name"] == name
    assert row["changes"][0]["after"] == "Đã xóa"


async def test_delete_resource_waits_for_booking_in_flight(admin):
    """Booking đang tạo (giữ khóa dòng sân) xong trước -> lệnh xóa phải thấy lịch đó, 409."""
    res = await create_resource(admin)
    code = res["code"]
    rid = await court_id(code)
    start = datetime.combine(today() + timedelta(days=22), time(8), settings.tz)
    async with SessionLocal() as booking_tx:
        await lock_live_resources(booking_tx, {rid})
        deleting = asyncio.create_task(delete_court(admin, code))
        await asyncio.sleep(0.3)
        assert not deleting.done(), "lệnh xóa phải chờ khóa của booking"
        await make_allocation(
            booking_tx, code, start, start + timedelta(hours=1), owner_code="BK-TEST-DEL-2"
        )
        await booking_tx.commit()
    r = await deleting
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-CFG-11", r.text


async def test_booking_waits_for_delete_in_flight_then_404(admin):
    """Lệnh xóa đang chạy (giữ FOR UPDATE) xong trước -> booking phải thấy sân đã xóa, 404."""
    res = await create_resource(admin)
    rid = await court_id(res["code"])
    async with SessionLocal() as delete_tx, SessionLocal() as booking_tx:
        row = await delete_tx.scalar(select(Resource).where(Resource.id == rid).with_for_update())
        locking = asyncio.create_task(lock_live_resources(booking_tx, {rid}))
        await asyncio.sleep(0.3)
        assert not locking.done(), "booking phải chờ khóa của lệnh xóa"
        row.deleted_at = datetime.now(settings.tz)
        row.is_active = False
        await delete_tx.commit()
        with pytest.raises(AppError) as err:
            await locking
        assert err.value.status_code == 404

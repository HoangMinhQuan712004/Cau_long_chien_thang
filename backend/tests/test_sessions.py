"""T-006 phần 2: sự kiện (Đặt sự kiện, popup Sự kiện, xóa buổi) và đăng ký vé tại quầy."""

import asyncio
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.testing import make_hold
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, calendar, member, new_court, safe_hour, temp, today

FD = f"{API}/front-desk"


async def create_session(admin, codes, day=None, start=9, end=11, **overrides):
    body = {
        "resource_codes": codes,
        "date": (day or today() + timedelta(days=1)).isoformat(),
        "start_hour": start,
        "end_hour": end,
        "name": "Giao lưu tối thứ Sáu",
        "capacity": 8,
        "ticket_price": 60_000,
        **overrides,
    }
    return await admin.post(f"{BK}/sessions", json=body, headers=idem())


async def register(client, code, customer=None, headers=None):
    return await client.post(
        f"{FD}/sessions/{code}/tickets",
        json={"customer": customer or member()},
        headers=headers or idem(),
    )


async def today_session(admin, capacity=8, **overrides) -> dict:
    """Sự kiện đang diễn ra hôm nay (đăng ký vé tại quầy được) trên một sân mới."""
    court = await new_court(admin)
    hour = await safe_hour()
    r = await create_session(
        admin,
        [court["code"]],
        day=today(),
        start=hour,
        end=hour + 1,
        capacity=capacity,
        **overrides,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ tạo sự kiện (BR-017)


async def test_create_session_spans_adjacent_courts(admin, staff):
    a, b = await new_court(admin), await new_court(admin)
    tomorrow = today() + timedelta(days=1)
    r = await create_session(admin, [b["code"], a["code"]], day=tomorrow, name=" <b>Giải</b>  mở ")
    assert r.status_code == 201, r.text
    ev = r.json()
    assert re.fullmatch(rf"BK-{tomorrow:%Y%m%d}-\d{{3}}", ev["code"])
    assert ev["name"] == "<b>Giải</b> mở"  # lưu nguyên văn (FE hiển thị dạng chữ)
    assert [x["code"] for x in ev["resources"]] == [a["code"], b["code"]]
    assert (ev["start_time"], ev["end_time"]) == ("09:00", "11:00")
    assert (ev["taken"], ev["capacity"], ev["is_full"]) == (0, 8, False)
    assert ev["tickets"] == [] and ev["active_holds"] == []
    assert ev["can"] == {"register": False, "delete": True}  # ngày mai: chưa đăng ký tại quầy
    assert ev["created_by"] == "Admin" and ev["status"] == "active"

    cal = await calendar(staff, tomorrow)
    block = next(x for x in cal["blocks"] if x["code"] == ev["code"])
    assert block["type"] == "session" and block["resource_codes"] == [a["code"], b["code"]]
    assert (block["taken"], block["capacity"], block["is_full"]) == (0, 8, False)

    # Khung đã thuộc sự kiện -> đặt sự kiện khác chồng lên bị chặn E-010
    r = await create_session(admin, [a["code"]], day=tomorrow, start=10, end=12)
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-010",
        "message": f"Khung 10:00–11:00 ở {a['name']} đã có người đặt. Vui lòng chọn vùng khác.",
    }


async def test_create_session_staff_forbidden(admin, staff):
    # NV mặc định được tạo sự kiện (người dùng chốt 2026-11-05) – tên test giữ nguyên
    court = await new_court(admin)
    r = await create_session(staff, [court["code"]], day=today() + timedelta(days=1))
    assert r.status_code == 201, r.text


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"name": "   "}, "E-001"),
        ({"name": "x" * 101}, "E-001"),
        ({"capacity": None}, "E-001"),
        ({"capacity": 0}, "E-009"),
        ({"capacity": 100}, "E-009"),
        ({"capacity": 2.5}, "E-009"),
        ({"ticket_price": None}, "E-001"),
        ({"ticket_price": -1}, "E-013"),
        ({"ticket_price": 1000.5}, "E-013"),
    ],
)
async def test_create_session_field_validation(admin, overrides, code):
    court = await new_court(admin)
    r = await create_session(admin, [court["code"]], **overrides)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == code


async def test_create_session_rules(admin):
    a, b, c = await new_court(admin), await new_court(admin), await new_court(admin)
    # Sân không liền nhau
    r = await create_session(admin, [a["code"], c["code"]])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-BOOK-2"
    # Ngày đã qua -> E-004; ngày rất xa -> được (bỏ giới hạn "hết tháng sau", T-008 AC31b)
    r = await create_session(admin, [a["code"]], day=today() - timedelta(days=1))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004"
    r = await create_session(admin, [a["code"]], day=today() + timedelta(days=200))
    assert r.status_code == 201, r.text
    # Vướng booking tại quầy
    hour = await safe_hour()
    assert (await book(admin, b["code"], hour)).status_code == 201
    r = await create_session(admin, [a["code"], b["code"]], day=today(), start=hour, end=hour + 1)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-010"
    assert b["name"] in r.json()["detail"]["message"]
    # Gửi trường do server quyết -> 422
    r = await create_session(admin, [c["code"]], code="BK-X", amount=1)
    assert r.status_code == 422


# ------------------------------------------------------------------ đăng ký vé (BR-024)


async def test_register_ticket_and_session_detail(admin, staff):
    ev = await today_session(admin, ticket_price=50_000)
    before = (await calendar(staff))["unpaid_count"]
    assert ev["can"]["register"] is True

    r = await register(staff, ev["code"], temp("Khách lẻ <script>alert(1)</script>"))
    assert r.status_code == 201, r.text
    t1 = r.json()
    assert t1["kind"] == "ticket" and t1["code"] == f"{ev['code']}-V01"
    assert t1["payment"] == {
        "amount": 50_000,
        "payment_status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "collected_by": None,
        "uncollectible_reason": None,
        "marked_by": None,
        "marked_at": None,
    }
    assert t1["schedule"]["session"] == {"code": ev["code"], "name": ev["name"]}
    assert t1["customer"]["name"] == "Khách lẻ <script>alert(1)</script>"
    t2 = (await register(staff, ev["code"], member("HV0045"))).json()
    assert t2["code"] == f"{ev['code']}-V02"

    detail = (await staff.get(f"{BK}/sessions/{ev['code'].lower()}")).json()
    assert set(detail) >= {
        "code", "name", "play_date", "start_time", "end_time", "resources", "ticket_price",
        "capacity", "taken", "is_full", "created_by", "created_at", "version", "tickets",
        "active_holds", "can",
    }  # fmt: skip
    assert detail["taken"] == 2
    assert [t["code"] for t in detail["tickets"]] == [t2["code"], t1["code"]]  # mới nhất trước
    assert detail["tickets"][0]["phone"] == "0978220145"  # màn quản trị: SĐT đầy đủ
    assert detail["can"] == {"register": True, "delete": False}  # quầy không xóa buổi
    assert (await calendar(staff))["unpaid_count"] == before + 2

    item = await staff.get(f"{BK}/items/{t1['code']}")
    assert item.status_code == 200 and item.json()["kind"] == "ticket"
    found = await staff.get(f"{BK}/search", params={"code": t1["code"].lower()})
    assert found.json() == {
        "kind": "ticket",
        "code": t1["code"],
        "play_date": today().isoformat(),
        "order_code": None,
        "codes": [],
    }
    found = await staff.get(f"{BK}/search", params={"code": ev["code"]})
    assert found.json()["kind"] == "session"

    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                select(AuditLog.action).where(AuditLog.entity_code.in_([t1["code"], t2["code"]]))
            )
        )
    assert rows == ["ticket.create", "ticket.create"]


async def test_register_ticket_only_today_and_not_ended(admin, staff):
    court = await new_court(admin)
    r = await create_session(admin, [court["code"]], day=today() + timedelta(days=1))
    code = r.json()["code"]
    r = await register(staff, code)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004"
    r = await register(staff, "BK-20000101-001")
    assert r.status_code == 404


async def test_register_last_seat_race_one_wins(admin, staff):
    ev = await today_session(admin, capacity=1)
    results = await asyncio.gather(*(register(staff, ev["code"]) for _ in range(20)))
    statuses = sorted(r.status_code for r in results)
    assert statuses.count(201) == 1, statuses
    assert statuses.count(409) == 19
    assert {r.json()["detail"]["code"] for r in results if r.status_code == 409} == {"E-024"}
    detail = (await staff.get(f"{BK}/sessions/{ev['code']}")).json()
    assert (detail["taken"], detail["is_full"]) == (1, True)
    assert detail["can"]["register"] is False
    r = await register(staff, ev["code"])
    assert r.status_code == 409 and r.json()["detail"] == {
        "code": "E-024",
        "message": "Sự kiện đã đủ chỗ.",
    }


async def test_seat_holds_count_toward_capacity(admin, staff):
    ev = await today_session(admin, capacity=2)
    async with SessionLocal() as s:
        await make_hold(s, session_code=ev["code"], seats=2, minutes=7)
        await s.commit()
    detail = (await staff.get(f"{BK}/sessions/{ev['code']}")).json()
    assert detail["taken"] == 2 and len(detail["active_holds"]) == 1
    assert detail["active_holds"][0]["seats"] == 2
    r = await register(staff, ev["code"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-024"
    r = await admin.request(
        "DELETE", f"{BK}/sessions/{ev['code']}", json={"version": 1}, headers=idem()
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-023"


# ------------------------------------------------------------------ xóa buổi (BR-025)


async def test_delete_session(admin, staff):
    court = await new_court(admin)
    tomorrow = today() + timedelta(days=1)
    ev = (await create_session(admin, [court["code"]], day=tomorrow)).json()
    path = f"{BK}/sessions/{ev['code']}"

    # NV mặc định được xóa sự kiện (người dùng chốt 2026-11-05): qua kiểm quyền, tới kiểm phiên bản
    r = await staff.request("DELETE", path, json={"version": 99}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-012"
    r = await admin.request("DELETE", path, json={"version": 99}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-012"

    headers = idem()
    r = await admin.request("DELETE", path, json={"version": 1}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deleted" and r.json()["name"] == ev["name"]
    replay = await admin.request("DELETE", path, json={"version": 1}, headers=headers)
    assert replay.status_code == 200 and replay.headers.get("idempotent-replayed") == "true"

    assert (await staff.get(path)).status_code == 404
    assert (await staff.get(f"{BK}/search", params={"code": ev["code"]})).status_code == 404
    cal = await calendar(admin, tomorrow)
    assert not [b for b in cal["blocks"] if court["code"] in b["resource_codes"]]
    # Khung trống lại; mã không dùng lại
    again = await create_session(admin, [court["code"]], day=tomorrow)
    assert again.status_code == 201 and again.json()["code"] != ev["code"]


async def test_delete_session_with_ticket_blocked(admin, staff):
    ev = await today_session(admin)
    assert (await register(staff, ev["code"])).status_code == 201
    r = await admin.request(
        "DELETE", f"{BK}/sessions/{ev['code']}", json={"version": ev["version"]}, headers=idem()
    )
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-023",
        "message": "Sự kiện đã có người đăng ký, không xóa được.",
    }

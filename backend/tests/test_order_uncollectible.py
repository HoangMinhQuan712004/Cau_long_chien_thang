"""T-064: "Không thu được" cả đơn – chỉ buổi Chưa thanh toán đã tới giờ, buổi sau giữ nguyên; đơn
online / chưa buổi nào tới giờ -> E-PAY-1; không còn khối chưa thu -> E-BOOK-4; đồng thời, gửi lại.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Allocation, Booking
from tests.conftest import idem
from tests.helpers_booking import BK, new_court, random_phone
from tests.helpers_web import checkout, simulate
from tests.test_recurring_list import create

FAR = (datetime.now(settings.tz) + timedelta(days=240)).date()


@pytest.fixture
def clock(monkeypatch):
    """``clock(ngày, giờ, phút)`` đặt giờ engine (buổi "đã tới giờ" theo đồng hồ này)."""
    state = {"now": datetime(FAR.year, FAR.month, FAR.day, 8, tzinfo=settings.tz)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int, minute: int = 0) -> None:
        state["now"] = datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz)

    return set_time


async def recurring(admin, start) -> dict:
    """Đơn định kỳ 4 buổi 18–20h: ``start``, ``start + 1``, ``start + 7``, ``start + 8``."""
    court = await new_court(admin)
    weekdays = (start.isoweekday(), (start + timedelta(days=1)).isoweekday())
    return await create(admin, court, "Khách Bỏ", random_phone(), start, weekdays)


async def mark(client, code: str, reason: str = "", headers: dict | None = None):
    return await client.post(
        f"{BK}/orders/{code}/uncollectible", json={"reason": reason}, headers=headers or idem()
    )


async def blocks(order: dict) -> dict[str, Booking]:
    codes = [b["code"] for b in order["bookings"]]
    async with SessionLocal() as s:
        rows = await s.scalars(select(Booking).where(Booking.code.in_(codes)))
        return {b.code: b for b in rows}


async def audits(codes: list[str]) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "payment.uncollectible", AuditLog.entity_code.in_(codes)
                )
            )
        )


async def test_marks_only_started_blocks_and_keeps_later_ones(admin, clock):
    """AC2, AC3, AC5: 2 buổi đã qua -> Không thu được, 2 buổi sau giữ Chưa thanh toán, khung giữ."""
    start = FAR + timedelta(days=3)
    clock(FAR, 8)
    order = await recurring(admin, start)
    codes = sorted(b["code"] for b in order["bookings"])
    assert len(codes) == 4
    clock(start + timedelta(days=1), 18, 30)  # buổi 2 đang chơi = đã tới giờ

    r = await mark(admin, order["order_code"], reason="  Khách không đến  ")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["order_code"] == order["order_code"]
    assert (out["marked"], out["remaining_unpaid"]) == (codes[:2], codes[2:])
    assert {b["code"]: b["payment"]["payment_status"] for b in out["bookings"]} == {
        **dict.fromkeys(codes[:2], "uncollectible"),
        **dict.fromkeys(codes[2:], "unpaid"),
    }
    rows = await blocks(order)
    assert {rows[c].uncollectible_reason for c in codes[:2]} == {"Khách không đến"}
    async with SessionLocal() as s:
        live = await s.scalars(
            select(Allocation.active).where(
                Allocation.booking_id.in_([rows[c].id for c in codes[:2]])
            )
        )
        assert set(live) == {True}  # khung không trống lại
    logs = await audits(codes)
    assert sorted(a.entity_code for a in logs) == codes[:2]  # mỗi buổi một dòng
    assert all(
        {"field": "Lý do", "before": None, "after": "Khách không đến"} in a.detail["changes"]
        for a in logs
    )

    # Lần sau: chưa buổi nào tới giờ -> E-PAY-1; hết giờ cả -> đánh dấu nốt, rồi E-BOOK-4
    r = await mark(admin, order["order_code"])
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "E-PAY-1",
        "message": "Chưa có buổi nào tới giờ chơi, chưa thể đánh dấu Không thu được.",
    }
    clock(start + timedelta(days=9), 8)
    r = await mark(admin, order["order_code"])  # lý do để trống
    assert r.status_code == 200, r.text
    assert (r.json()["marked"], r.json()["remaining_unpaid"]) == (codes[2:], [])
    logs = await audits(codes[2:])
    assert [c["field"] for a in logs for c in a.detail["changes"]] == ["Thanh toán", "Thanh toán"]
    r = await mark(admin, order["order_code"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-4"


async def test_online_order_and_missing_order(anon, admin):
    one = await new_court(admin)
    r = await checkout(anon, [(one["code"], 19)])
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    r = await mark(admin, co["order_code"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1"
    assert "online" in r.json()["detail"]["message"]
    r = await mark(admin, "BK-20000101-999")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-BOOK-3"
    r = await mark(admin, co["order_code"], reason="x" * 201)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001"


async def test_permission_concurrency_and_replay(admin, staff, customer, clock):
    """AC7: không quyền -> 403; hai máy cùng lúc -> một lần; gửi lại cùng key -> không áp lại."""
    start = FAR + timedelta(days=30)
    clock(FAR, 8)
    first = await recurring(admin, start)
    second = await recurring(admin, start)
    clock(start + timedelta(days=1), 21)
    assert (await mark(customer, first["order_code"])).status_code == 403

    a, b = await asyncio.gather(mark(admin, first["order_code"]), mark(staff, first["order_code"]))
    assert sorted((a.status_code, b.status_code)) == [200, 422], (a.text, b.text)
    loser = a if a.status_code == 422 else b
    assert loser.json()["detail"]["code"] == "E-PAY-1"  # buổi đã tới giờ đã bị bên kia đánh dấu
    assert len(await audits([x["code"] for x in first["bookings"]])) == 2

    headers = idem()
    r1 = await mark(admin, second["order_code"], headers=headers)
    r2 = await mark(admin, second["order_code"], headers=headers)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert len(await audits([x["code"] for x in second["bookings"]])) == 2

"""T-035: Admin đặt sân định kỳ – xem trước, all-or-nothing, giá theo ngày, phân bổ giảm."""

import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.models import Booking, BookingOrder
from app.modules.booking_engine.recurring import _allocate
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import BK, member, new_court, temp, today
from tests.helpers_web import checkout

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

FD = f"{API}/front-desk"


def body(court: dict, start, end, weekdays=(1, 2, 3, 4, 5, 6, 7), hours=(18, 20), pct=0, **extra):
    return {
        "resource_code": court["code"],
        "weekdays": list(weekdays),
        "start_hour": hours[0],
        "end_hour": hours[1],
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "discount_pct": pct,
        **extra,
    }


async def preview(client, data: dict) -> dict:
    r = await client.post(f"{FD}/recurring/preview", json=data)
    assert r.status_code == 200, r.text
    return r.json()


async def quote(client, court: dict, day, hours=(18, 20)) -> int:
    r = await client.post(
        f"{BK}/quote",
        json={
            "resource_code": court["code"],
            "date": day.isoformat(),
            "start_hour": hours[0],
            "end_hour": hours[1],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["total_amount"]


def error(r) -> str:
    return r.json()["detail"]["code"]


# ------------------------------------------------------------------ phân bổ giảm (AC4)


def test_discount_allocation_matches_to_the_dong():
    prices = [100_001, 200_003, 99_999, 150_000]
    original, discount, shares = _allocate(prices, 33)
    assert original == 550_003
    assert discount == (550_003 * 33 + 50) // 100  # half-up = 181 501
    assert sum(shares) == discount and all(s >= 0 for s in shares)
    assert shares[:-1] == [p * discount // original for p in prices[:-1]]  # floor theo tỉ lệ
    assert sum(p - s for p, s in zip(prices, shares, strict=True)) == original - discount
    assert _allocate([120_000, 80_000], 100) == (200_000, 200_000, [120_000, 80_000])
    assert _allocate([120_000, 80_000], 0) == (200_000, 0, [0, 0])
    assert _allocate([1, 1, 1], 50)[1] == 2  # 1.5 -> 2 (half-up)


# ------------------------------------------------------------------ xem trước (AC1, AC4, AC6)


async def test_preview_prices_per_day_including_holiday_and_writes_nothing(admin):
    court = await new_court(admin)
    start = today() + timedelta(days=60)
    end = start + timedelta(days=13)
    holiday = start + timedelta(days=3)
    r = await admin.post(
        f"{BK}/special-days",
        json={"date_from": holiday.isoformat(), "name": "Lễ thử T-035"},
        headers=idem(),
    )
    assert r.status_code == 201, r.text  # ngày Lễ thật để kiểm giá theo ngày
    special_id = r.json()["id"]
    try:
        async with SessionLocal() as s:
            before = await s.scalar(select(func.count()).select_from(Booking))
        d = await preview(admin, body(court, start, end, pct=15))
        assert d["count"] == 14 and d["conflicts_count"] == 0
        assert all(x["ok"] and x["reason"] is None for x in d["sessions"])
        assert all(
            x["weekday"] == date.fromisoformat(x["date"]).isoweekday() for x in d["sessions"]
        )
        by_date = {x["date"]: x for x in d["sessions"]}
        for day in (start, holiday, start + timedelta(days=(5 - start.weekday()) % 7)):
            assert by_date[day.isoformat()]["price"] == await quote(admin, court, day)
        assert d["original_amount"] == sum(x["price"] for x in d["sessions"])
        assert d["discount_amount"] == (d["original_amount"] * 15 + 50) // 100
        assert d["total"] == d["original_amount"] - d["discount_amount"]
        assert sum(x["price_after_discount"] for x in d["sessions"]) == d["total"]
        assert d["sessions"][0]["start_time"] == "18:00" and d["sessions"][0]["end_time"] == "20:00"
        async with SessionLocal() as s:
            assert await s.scalar(select(func.count()).select_from(Booking)) == before
    finally:
        await admin.delete(f"{BK}/special-days/{special_id}", headers=idem())


async def test_limits_and_permissions(admin, staff):
    court = await new_court(admin)
    start = today() + timedelta(days=2)
    bad = [
        body(court, start, start + timedelta(days=6), weekdays=()),
        body(court, start, start + timedelta(days=6), weekdays=(0,)),
        body(court, start, start + timedelta(days=6), hours=(20, 18)),
        body(court, today() - timedelta(days=1), start),
        body(court, start + timedelta(days=3), start),
        body(court, start, start + timedelta(days=92)),  # 93 ngày
        body(court, start, start + timedelta(days=69)),  # 70 buổi > 60
        body(court, start, start + timedelta(days=6), pct=101),
    ]
    for data in bad:
        r = await admin.post(f"{FD}/recurring/preview", json=data)
        assert r.status_code == 422, (data, r.text)
    ok = body(court, start, start + timedelta(days=6))
    assert (await admin.post(f"{FD}/recurring/preview", json=ok)).status_code == 200
    r = await staff.post(f"{FD}/recurring/preview", json=ok)
    assert r.status_code == 403  # AC7: NV không có quyền
    r = await staff.post(
        f"{FD}/recurring", json={**ok, "customer": temp("Khách Định Kỳ")}, headers=idem()
    )
    assert r.status_code == 403


# ------------------------------------------------------------------ tạo (AC2, AC5, AC8, AC9)


async def test_create_order_with_discount_rooms_audit_and_collect(admin, people):
    host = await people("Khách Đặt Tháng")
    court = await new_court(admin)
    start = today() + timedelta(days=5)
    end = start + timedelta(days=20)
    data = body(court, start, end, weekdays=(2, 4), pct=10)
    p = await preview(admin, data)
    key = idem()
    r = await admin.post(
        f"{FD}/recurring", json={**data, "customer": member(host.code)}, headers=key
    )
    assert r.status_code == 201, r.text
    out = r.json()
    first = min(x["date"] for x in p["sessions"])
    assert out["order_code"].startswith(f"BK-{first.replace('-', '')}-")
    assert (out["original_amount"], out["discount_amount"], out["total"]) == (
        p["original_amount"],
        p["discount_amount"],
        p["total"],
    )
    codes = [b["code"] for b in out["bookings"]]
    assert codes == [f"{out['order_code']}-{i:02d}" for i in range(1, p["count"] + 1)]
    # Gửi lại cùng key -> kết quả cũ
    again = await admin.post(
        f"{FD}/recurring", json={**data, "customer": member(host.code)}, headers=key
    )
    assert again.status_code == 201 and again.json() == out

    async with SessionLocal() as s:
        order = await s.scalar(select(BookingOrder).where(BookingOrder.code == out["order_code"]))
        assert (order.kind, order.discount_pct, order.discount_amount) == (
            "recurring",
            10,
            p["discount_amount"],
        )
        rows = list(
            await s.scalars(
                select(Booking).where(Booking.order_id == order.id).order_by(Booking.seq)
            )
        )
        assert [b.start_at for b in rows] == sorted(b.start_at for b in rows)
        assert [(b.list_amount, b.amount) for b in rows] == [
            (x["price"], x["price_after_discount"]) for x in p["sessions"]
        ]
        assert all(
            b.payment_status == "unpaid" and b.customer_ref == str(host.customer_id) for b in rows
        )
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "booking.recurring.create",
                AuditLog.entity_code == out["order_code"],
            )
        )
    assert row.detail["discount_pct"] == 10 and row.detail["sessions"] == p["count"]
    assert row.detail["total"] == p["total"] and host.phone not in str(row.detail)

    # AC8: mỗi buổi có phòng (worker từ outbox)
    while await engine.publish_outbox(SessionLocal):
        pass
    async with SessionLocal() as s:
        rooms = await s.scalar(
            select(func.count()).select_from(PlayRoom).where(PlayRoom.booking_code.in_(codes))
        )
    assert rooms == len(codes)

    # AC5: Thu cả đơn = đúng tổng sau giảm, mọi buổi Đã thanh toán
    r = await admin.post(
        f"{BK}/orders/{out['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        paid = list(await s.scalars(select(Booking).where(Booking.order_id == order.id)))
    assert all(b.payment_status == "paid" for b in paid)
    assert sum(b.amount for b in paid) == p["total"]


async def test_full_discount_collects_zero(admin):
    court = await new_court(admin)
    start = today() + timedelta(days=4)
    data = body(court, start, start + timedelta(days=6), weekdays=(start.isoweekday(),), pct=100)
    r = await admin.post(
        f"{FD}/recurring", json={**data, "customer": temp("Khách Miễn Phí")}, headers=idem()
    )
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 0 and all(b["payment"]["amount"] == 0 for b in r.json()["bookings"])
    r = await admin.post(
        f"{BK}/orders/{r.json()['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ all-or-nothing (AC3, AC6)


async def test_conflicts_event_hold_closed_block_everything(anon, admin):
    court = await new_court(admin, open_time="06:00", close_time="22:00")
    start = today() + timedelta(days=10)
    end = start + timedelta(days=6)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": (start + timedelta(days=1)).isoformat(),
            "start_hour": 19,
            "end_hour": 21,
            "name": "Sự kiện chặn",
            "capacity": 8,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    held = await checkout(anon, [(court["code"], 18)], day=start + timedelta(days=2))
    assert held.status_code == 201, held.text

    d = await preview(admin, body(court, start, end))
    reasons = {x["date"]: x["reason"] for x in d["sessions"] if not x["ok"]}
    assert reasons == {
        (start + timedelta(days=1)).isoformat(): "event",
        (start + timedelta(days=2)).isoformat(): "hold",
    }
    assert d["conflicts_count"] == 2
    async with SessionLocal() as s:
        before = await s.scalar(select(func.count()).select_from(BookingOrder))
    r = await admin.post(
        f"{FD}/recurring",
        json={**body(court, start, end), "customer": temp("Khách Trùng")},
        headers=idem(),
    )
    assert r.status_code == 409 and error(r) == "E-BOOK-5"
    assert r.json()["detail"]["message"] == "Có 2 buổi không đặt được."
    assert {c["reason"] for c in r.json()["detail"]["conflicts"]} == {"event", "hold"}
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(BookingOrder)) == before

    # Ngoài giờ mở cửa (sân 06–22)
    d = await preview(admin, body(court, start, end, hours=(21, 23)))
    assert {x["reason"] for x in d["sessions"]} == {"closed"}


async def test_concurrent_overlapping_orders_one_wins(admin):
    court = await new_court(admin)
    start = today() + timedelta(days=30)
    data = body(court, start, start + timedelta(days=13), weekdays=(1, 3, 5))
    results = await asyncio.gather(
        *(
            admin.post(
                f"{FD}/recurring", json={**data, "customer": temp(f"Khách {i}")}, headers=idem()
            )
            for i in range(2)
        )
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    lost = next(r for r in results if r.status_code == 409)
    assert error(lost) == "E-BOOK-5" and lost.json()["detail"]["conflicts"]
    assert {c["reason"] for c in lost.json()["detail"]["conflicts"]} == {"booked"}

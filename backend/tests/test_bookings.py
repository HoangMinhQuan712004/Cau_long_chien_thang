import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import SessionLocal
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import Booking
from tests.client import API
from tests.conftest import new_customer, slot


async def test_quote_uses_price_rules(anon):
    s = slot(1, 18)  # 18h-19h: giờ vàng ngày thường hoặc cuối tuần
    r = await anon.post(f"{API}/bookings/quote", json=[s])
    assert r.status_code == 200, r.text
    weekday = datetime.fromisoformat(s["start"]).weekday()
    assert r.json()["total_amount"] == (110_000 if weekday >= 5 else 100_000)


async def test_booking_requires_login(anon):
    r = await anon.post(f"{API}/bookings", json={"slots": [slot(1, 6)]})
    assert r.status_code == 401


async def test_overlap_rejected_adjacent_allowed(customer):
    r = await customer.post(f"{API}/bookings", json={"slots": [slot(1, 18)]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["expires_at"] is not None

    async with new_customer() as other:
        r = await other.post(f"{API}/bookings", json={"slots": [slot(1, 18, 30)]})
        assert r.status_code == 409
        # Sân khác cùng giờ: OK
        r = await other.post(f"{API}/bookings", json={"slots": [slot(2, 18)]})
        assert r.status_code == 201
        # Liền kề (19h-20h) không tính là trùng vì range là [start, end)
        r = await other.post(f"{API}/bookings", json={"slots": [slot(1, 19)]})
        assert r.status_code == 201


async def test_concurrent_requests_only_one_wins():
    async with AsyncExitStack() as stack:
        clients = [await stack.enter_async_context(new_customer()) for _ in range(5)]
        results = await asyncio.gather(
            *(c.post(f"{API}/bookings", json={"slots": [slot(3, 20)]}) for c in clients)
        )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409]


async def test_validation(customer):
    cases = [
        slot(1, 8, 15),  # lệch bước 30 phút
        slot(1, 8, minutes=30),  # dưới tối thiểu 60 phút
        slot(1, 4),  # trước giờ mở cửa
        slot(1, 22, minutes=90),  # quá giờ đóng cửa
        slot(1, 8, days=-1),  # quá khứ
        slot(1, 8, days=60),  # quá xa
        slot(999, 8),  # sân không tồn tại
    ]
    for s in cases:
        r = await customer.post(f"{API}/bookings", json={"slots": [s]})
        assert r.status_code == 400, (s, r.text)


async def test_cancel_frees_slot(customer):
    r = await customer.post(f"{API}/bookings", json={"slots": [slot(4, 9)]})
    booking_id = r.json()["id"]
    r = await customer.post(f"{API}/bookings/{booking_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    async with new_customer() as other:
        r = await other.post(f"{API}/bookings", json={"slots": [slot(4, 9)]})
        assert r.status_code == 201
        # Không xem / hủy được đơn người khác
        r = await other.get(f"{API}/bookings/{booking_id}")
        assert r.status_code == 404


async def test_expire_pending_frees_slot(customer):
    r = await customer.post(f"{API}/bookings", json={"slots": [slot(4, 11)]})
    booking_id = r.json()["id"]
    async with SessionLocal() as session:
        await session.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
        assert await bookings_service.expire_pending(session) >= 1

    r = await customer.get(f"{API}/bookings/{booking_id}")
    assert r.json()["status"] == "expired"
    r = await customer.post(f"{API}/bookings", json={"slots": [slot(4, 11)]})
    assert r.status_code == 201


async def test_staff_counter_booking_and_payment(admin, customer):
    # Khách (JWT cổng khách) không có phiên quản trị ⇒ không vào được API admin
    r = await customer.get(f"{API}/admin/bookings")
    assert r.status_code == 401

    r = await admin.post(
        f"{API}/admin/bookings",
        json={"slots": [slot(2, 7)], "customer_name": "Anh Nam", "confirm": False},
    )
    assert r.status_code == 201, r.text
    booking = r.json()
    assert booking["status"] == "pending" and booking["source"] == "counter"
    assert booking["expires_at"] is None  # giữ chỗ tại quầy không tự hết hạn

    r = await admin.post(f"{API}/admin/bookings/{booking['id']}/payments", json={"method": "cash"})
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == booking["total_amount"]

    r = await admin.get(f"{API}/admin/bookings", params={"status": "confirmed"})
    assert booking["id"] in [b["id"] for b in r.json()]


async def test_availability_lists_busy_ranges(anon, customer):
    s = slot(3, 15)
    await customer.post(f"{API}/bookings", json={"slots": [s]})
    day = datetime.fromisoformat(s["start"]).date().isoformat()
    r = await anon.get(f"{API}/bookings/availability", params={"date": day})
    assert r.status_code == 200
    court3 = next(c for c in r.json()["courts"] if c["court_id"] == 3)
    starts = [datetime.fromisoformat(b["start"]) for b in court3["busy"]]
    assert datetime.fromisoformat(s["start"]) in starts

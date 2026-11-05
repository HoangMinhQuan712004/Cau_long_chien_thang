"""T-039: màn "Đơn định kỳ" – danh sách, trạng thái tính từ các buổi, lọc, tìm, che SĐT."""

import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking, BookingOrder
from tests.conftest import idem
from tests.helpers_booking import BK, new_court, random_phone, temp, today
from tests.test_recurring import FD, body

LIST = f"{FD}/recurring"


async def create(admin, court, name: str, phone: str, start, weekdays, pct=0) -> dict:
    data = body(court, start, start + timedelta(days=13), weekdays=weekdays, pct=pct)
    r = await admin.post(LIST, json={**data, "customer": temp(name, phone)}, headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


async def listing(client, **params) -> dict:
    r = await client.get(LIST, params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_list_statuses_counts_filters_and_masked_phone(admin, staff):
    tag = f"ĐK{uuid.uuid4().hex[:6]}"
    court = await new_court(admin)
    start = today() + timedelta(days=20)
    phones = [random_phone() for _ in range(3)]
    a = await create(admin, court, f"{tag} An", phones[0], start, (2, 4), pct=10)
    b = await create(admin, court, f"{tag} Bình", phones[1], start, (1,))
    c = await create(admin, court, f"{tag} Cường", phones[2], start, (6, 7))

    # b: Thu cả đơn -> Đã thanh toán
    r = await admin.post(
        f"{BK}/orders/{b['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    # c: một buổi Không thu được, còn lại đã thu -> Không thu được
    async with SessionLocal() as s:
        order_id = await s.scalar(
            select(BookingOrder.id).where(BookingOrder.code == c["order_code"])
        )
        first = await s.scalar(
            select(Booking.id).where(Booking.order_id == order_id).order_by(Booking.seq).limit(1)
        )
        await s.execute(
            update(Booking)
            .where(Booking.id == first)
            .values(payment_status="uncollectible", uncollectible_reason="Khách không đến")
        )
        await s.commit()
    r = await admin.post(
        f"{BK}/orders/{c['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text

    d = await listing(admin, q=tag)
    assert d["counts"] == {"all": 3, "unpaid": 1, "paid": 1, "uncollectible": 1}
    assert d["total"] == 3 and (d["page"], d["size"]) == (1, 20)
    assert [i["order_code"] for i in d["items"]] == [
        c["order_code"],
        b["order_code"],
        a["order_code"],
    ]
    status = {i["order_code"]: i["status"] for i in d["items"]}
    assert status == {
        a["order_code"]: "unpaid",
        b["order_code"]: "paid",
        c["order_code"]: "uncollectible",
    }

    row = next(i for i in d["items"] if i["order_code"] == a["order_code"])
    assert row["customer_name"] == f"{tag} An" and row["resource_code"] == court["code"]
    assert row["resource_name"] == court["name"]
    assert row["weekdays"] == [2, 4] and (row["start_hour"], row["end_hour"]) == (18, 20)
    assert row["sessions"] == len(a["bookings"])
    dates = sorted(x["schedule"]["play_date"] for x in a["bookings"])
    assert (row["date_from"], row["date_to"]) == (dates[0], dates[-1])  # buổi đầu – buổi cuối
    assert (row["original_amount"], row["discount_pct"], row["discount_amount"], row["total"]) == (
        a["original_amount"],
        10,
        a["discount_amount"],
        a["total"],
    )
    assert row["created_by"] and row["created_at"]
    # SĐT che, không có SĐT đầy đủ ở đâu
    assert row["phone_masked"] == f"{phones[0][:4]} xxx {phones[0][-3:]}"
    text = str(d)
    assert all(p not in text for p in phones)

    # Lọc trạng thái + tìm theo mã đơn / tên / SĐT
    only = await listing(admin, q=tag, status="unpaid")
    assert [i["order_code"] for i in only["items"]] == [a["order_code"]] and only["total"] == 1
    assert only["counts"]["all"] == 3  # đếm bỏ qua status
    assert [i["order_code"] for i in (await listing(admin, q=b["order_code"]))["items"]] == [
        b["order_code"]
    ]
    assert [i["order_code"] for i in (await listing(admin, q=phones[2][-6:]))["items"]] == [
        c["order_code"]
    ]
    assert [i["order_code"] for i in (await listing(admin, q=f"{tag} cường"))["items"]] == [
        c["order_code"]
    ]
    page2 = await listing(admin, q=tag, size=2, page=2)
    assert [i["order_code"] for i in page2["items"]] == [a["order_code"]]

    # Chỉ Admin; đơn quầy thường không vào danh sách
    assert (await staff.get(LIST)).status_code == 403
    assert (await admin.get(LIST, params={"status": "khac"})).status_code == 422

"""T-041: màn "Đơn đặt sân" – đơn ngày (quầy / online) + định kỳ, lọc loại × trạng thái + ngày."""

import uuid
from datetime import timedelta

from tests.conftest import API, idem
from tests.helpers_booking import BK, book, new_court, random_phone, safe_hour, temp, today
from tests.helpers_web import checkout, simulate, tomorrow
from tests.test_recurring import body

ORDERS = f"{API}/front-desk/orders"


async def orders(client, **params) -> dict:
    r = await client.get(ORDERS, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def codes(d: dict) -> list[str]:
    return [i["order_code"] for i in d["items"]]


async def test_orders_kinds_statuses_dates_search_and_privacy(anon, admin, staff):
    tag = f"ĐS{uuid.uuid4().hex[:6]}"
    court = await new_court(admin)
    phones = [random_phone() for _ in range(4)]

    # Đơn ngày tại quầy (hôm nay, chưa thu)
    hour = await safe_hour()
    counter = await book(staff, court["code"], hour, hour + 1, temp(f"{tag} Quầy", phones[0]))
    assert counter.status_code == 201, counter.raw.text
    counter_order, counter_child = counter.json()["order_code"], counter.json()["code"]
    # Đơn ngày online (ngày mai, đã trả)
    co = await checkout(anon, [(court["code"], 9)], phone=phones[1], name=f"{tag} Online")
    assert co.status_code == 201, co.text
    assert await simulate(admin, co.json()["pay_ref"], co.json()["amount"]) == "applied"
    online_order = co.json()["order_code"]
    # Lượt giữ chỗ chưa trả -> chưa thành đơn, không hiện
    pending = await checkout(anon, [(court["code"], 10)], phone=phones[2], name=f"{tag} Chờ")
    assert pending.status_code == 201
    # Đơn định kỳ (từ +20 ngày, chưa thu)
    start = today() + timedelta(days=20)
    data = body(court, start, start + timedelta(days=6), weekdays=(start.isoweekday(),), pct=5)
    r = await admin.post(
        f"{API}/front-desk/recurring",
        json={**data, "customer": temp(f"{tag} Định Kỳ", phones[3])},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    recurring_order = r.json()["order_code"]

    d = await orders(admin, q=tag)
    assert d["counts"]["all"] == {
        "all": 3,
        "unpaid": 2,
        "paid": 1,
        "uncollectible": 0,
        "cancelled": 0,
    }
    assert d["counts"]["single"] == {
        "all": 2,
        "unpaid": 1,
        "paid": 1,
        "uncollectible": 0,
        "cancelled": 0,
    }
    assert d["counts"]["recurring"] == {
        "all": 1,
        "unpaid": 1,
        "paid": 0,
        "uncollectible": 0,
        "cancelled": 0,
    }
    assert codes(d) == [recurring_order, online_order, counter_order]  # mới nhất trước
    by_code = {i["order_code"]: i for i in d["items"]}
    assert (by_code[counter_order]["kind"], by_code[counter_order]["source"]) == (
        "single",
        "counter",
    )
    assert (by_code[online_order]["kind"], by_code[online_order]["source"]) == ("single", "online")
    assert (by_code[online_order]["status"], by_code[counter_order]["status"]) == ("paid", "unpaid")
    rec = by_code[recurring_order]
    assert (rec["kind"], rec["discount_pct"], rec["blocks"]) == ("recurring", 5, 1)
    assert by_code[counter_order]["play_date"] == today().isoformat()
    assert by_code[counter_order]["resource_names"] == [court["name"]]
    # SĐT đầy đủ ở màn Đơn đặt sân (người dùng chốt 2026-11-09; trước đây che)
    assert by_code[counter_order]["phone"] == phones[0]
    assert "phone_masked" not in by_code[counter_order]

    # Lọc loại × trạng thái
    assert codes(await orders(admin, q=tag, kind="single")) == [online_order, counter_order]
    one = await orders(admin, q=tag, kind="single", status="unpaid")
    assert codes(one) == [counter_order] and one["total"] == 1
    assert codes(await orders(admin, q=tag, kind="recurring")) == [recurring_order]
    # Khoảng ngày chơi: hôm nay -> chỉ đơn quầy; từ +10 ngày -> chỉ định kỳ
    d = await orders(admin, q=tag, date_from=today().isoformat(), date_to=today().isoformat())
    assert codes(d) == [counter_order] and d["counts"]["all"]["all"] == 1
    d = await orders(admin, q=tag, date_from=(today() + timedelta(days=10)).isoformat())
    assert codes(d) == [recurring_order]
    d = await orders(admin, q=tag, date_to=tomorrow().isoformat())
    assert set(codes(d)) == {counter_order, online_order}
    # Tìm theo mã con / mã đơn / SĐT
    assert codes(await orders(admin, q=counter_child)) == [counter_order]
    assert codes(await orders(admin, q=online_order.lower())) == [online_order]
    assert codes(await orders(admin, q=phones[3][-6:])) == [recurring_order]

    # Thu cả đơn -> Đã thanh toán
    r = await admin.post(
        f"{BK}/orders/{counter_order}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (await orders(admin, q=counter_order))["items"][0]["status"] == "paid"

    # Quyền + dữ liệu sai
    assert (await staff.get(ORDERS)).status_code == 403
    r = await admin.get(
        ORDERS, params={"date_from": tomorrow().isoformat(), "date_to": today().isoformat()}
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-016"
    assert (await admin.get(ORDERS, params={"kind": "ticket"})).status_code == 422

    # Endpoint cũ T-039 vẫn chạy (chỉ định kỳ)
    old = (await admin.get(f"{API}/front-desk/recurring", params={"q": tag})).json()
    assert [i["order_code"] for i in old["items"]] == [recurring_order]
    assert old["counts"]["all"] == 1


async def test_unpaid_amount_matches_what_collect_order_takes(admin):
    """T-066: ``unpaid_amount`` / ``unpaid_blocks`` = khối Chưa thanh toán (đã giảm %), bỏ khối
    đã thu, đã hủy, Không thu được; trùng số tiền QR cả đơn và số "Thu cả đơn" thu được."""
    from sqlalchemy import update

    from app.core.db import SessionLocal
    from app.modules.booking_engine.models import Booking
    from tests.test_counter_qr import FD, qr, recurring

    order = await recurring(admin, days_ahead=120, pct=10)  # 4 buổi, giảm 10%
    code = order["order_code"]
    items = sorted(order["bookings"], key=lambda b: b["code"])
    amounts = [b["payment"]["amount"] for b in items]

    async def row() -> dict:
        d = await orders(admin, q=code)
        [found] = [r for r in d["items"] if r["order_code"] == code]
        return found

    fresh = await row()
    assert (fresh["unpaid_amount"], fresh["unpaid_blocks"]) == (order["total"], 4)
    assert fresh["total"] == order["total"] < order["original_amount"]

    # Buổi 1 thu tiền mặt, buổi 2 hủy, buổi 3 Không thu được -> còn buổi 4
    r = await admin.post(
        f"{BK}/items/{items[0]['code']}/collect",
        json={"method": "cash", "version": items[0]["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={"reason": "Đổi lịch", "codes": [items[1]["code"]]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:  # buổi tương lai: API đòi đã tới giờ, đặt thẳng trạng thái
        await s.execute(
            update(Booking)
            .where(Booking.code == items[2]["code"])
            .values(payment_status="uncollectible", uncollectible_reason="Khách không đến")
        )
        await s.commit()

    partial = await row()
    assert (partial["unpaid_amount"], partial["unpaid_blocks"]) == (amounts[3], 1)
    assert partial["total"] == amounts[0] + amounts[2] + amounts[3]  # tổng đơn bỏ khối đã hủy
    assert (await qr(admin, code)).json()["amount"] == partial["unpaid_amount"]

    r = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == partial["unpaid_amount"]
    done = await row()
    assert (done["unpaid_amount"], done["unpaid_blocks"]) == (0, 0)

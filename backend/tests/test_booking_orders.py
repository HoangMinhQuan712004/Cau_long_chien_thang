"""T-019 (ADR-010): mã chung cho một lượt đặt – đơn ``BK-YYYYMMDD-NNN``, khối ``{mã đơn}-NN``."""

import re

from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking, BookingOrder, OutboxEvent
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, book_order, new_court, random_phone, safe_hour, today
from tests.helpers_web import WEB, checkout, simulate, tomorrow

ORDERS = f"{BK}/orders"


async def lookup(client, code: str, phone: str):
    return await client.post(f"{WEB}/lookup", json={"code": code, "phone": phone})


async def outbox_payloads(event_type: str, order_code: str) -> list[dict]:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.event_type == event_type,
                OutboxEvent.payload["order_code"].astext == order_code,
            )
        )
        return list(rows)


# ------------------------------------------------------------------ online (AC1, AC2, AC8)


async def test_online_two_courts_two_ranges_is_one_order(anon, admin):
    """Ví dụ của spec: Sân A + Sân B lúc 11–13 và 15–17 -> 1 mã đơn, 4 khối -01…-04."""
    a, b = await new_court(admin), await new_court(admin)
    phone = random_phone()
    slots = [(c["code"], h) for c in (b, a) for h in (16, 11, 15, 12)]
    r = await checkout(anon, slots, phone=phone)
    assert r.status_code == 201, r.text
    co = r.json()
    order = co["order_code"]
    assert re.fullmatch(rf"BK-{tomorrow():%Y%m%d}-\d{{3}}", order)
    assert co["pay_ref"] == order.replace("-", "")
    items = co["items"]
    # Theo sân (thứ tự sân) rồi giờ bắt đầu
    first, second = sorted([a, b], key=lambda c: c["code"])
    assert [(i["code"], i["resource_code"], i["start_time"], i["end_time"]) for i in items] == [
        (f"{order}-01", first["code"], "11:00", "13:00"),
        (f"{order}-02", first["code"], "15:00", "17:00"),
        (f"{order}-03", second["code"], "11:00", "13:00"),
        (f"{order}-04", second["code"], "15:00", "17:00"),
    ]
    assert f"des={co['pay_ref']}" in co["bank"]["qr_url"]  # nội dung CK = mã đơn bỏ gạch

    # Tiền về áp cho cả đơn
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    async with SessionLocal() as s:
        o = await s.scalar(select(BookingOrder).where(BookingOrder.code == order))
        assert o.channel == "online" and o.checkout_id is not None
        blocks = list(
            await s.scalars(select(Booking).where(Booking.order_id == o.id).order_by(Booking.seq))
        )
    assert [b.code for b in blocks] == [i["code"] for i in items]
    assert [b.seq for b in blocks] == [1, 2, 3, 4]
    assert {b.payment_status for b in blocks} == {"paid"}

    paid = await outbox_payloads("booking.online_paid", order)
    assert len(paid) == 1 and paid[0]["codes"] == [i["code"] for i in items]
    created = await outbox_payloads("booking.created", order)
    assert sorted(e["code"] for e in created) == [i["code"] for i in items]
    assert all("phone" not in str(e) for e in created)


async def test_partial_payment_does_not_split_order(anon, admin):
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 9), (court["code"], 14)])
    co = r.json()
    assert len(co["items"]) == 2
    assert await simulate(admin, co["pay_ref"], co["amount"] - 1_000) == "partial"
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).where(BookingOrder.code == co["order_code"]))
    assert n == 0  # đơn chỉ tạo khi đủ tiền
    assert await simulate(admin, co["pay_ref"], 1_000) == "applied"


# ------------------------------------------------------------------ tra cứu (AC3)


async def test_lookup_by_order_or_child_code(anon, admin):
    court = await new_court(admin)
    phone = random_phone()
    r = await checkout(anon, [(court["code"], 9), (court["code"], 14)], phone=phone)
    co = r.json()
    order = co["order_code"]

    # Đang chờ thanh toán: mã đơn hoặc mã con đều ra cả lượt
    for code in (order, f"{order}-02", f"{order}-02".replace("-", "").lower()):
        res = await lookup(anon, code, phone)
        assert res.status_code == 200, (code, res.text)
        body = res.json()
        assert body["order_code"] == order and body["status"] == "pending"
        assert len(body["items"]) == 2 and body["hours"] == 2
        assert body["pending"]["pay_ref"] == co["pay_ref"]

    await simulate(admin, co["pay_ref"], co["amount"])
    res = await lookup(anon, f"{order}-01", phone)
    body = res.json()
    assert body["status"] == "paid" and body["payment_method_label"] == "Chuyển khoản"
    assert [i["status"] for i in body["items"]] == ["paid", "paid"]
    assert body["amount"] == co["amount"] and body["pending"] is None
    assert "matched" not in body["items"][0]

    for code, ph in ((order, random_phone()), (f"{order}-09", phone), ("BK-20000101-001", phone)):
        res = await lookup(anon, code, ph)
        assert res.status_code == 404 and res.json()["detail"]["code"] == "E-WEB-7"


# ------------------------------------------------------------------ quầy (AC4, phương án A)


async def test_counter_multi_block_order(staff, admin):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    blocks = [(b["code"], hour, hour + 1), (a["code"], hour, hour + 1)]
    if hour <= 21:  # cùng sân, giờ liền nhau -> gộp thành một khối
        blocks += [(a["code"], hour + 1, hour + 2)]
    r = await book_order(staff, blocks, customer={"member_code": "HV0087"})
    assert r.status_code == 201, r.text
    body = r.json()
    order = body["order_code"]
    assert re.fullmatch(rf"BK-{today():%Y%m%d}-\d{{3}}", order)
    first, second = sorted([a, b], key=lambda c: c["code"])
    got = [(x["code"], x["schedule"]["resource_codes"][0]) for x in body["bookings"]]
    assert got == [(f"{order}-01", first["code"]), (f"{order}-02", second["code"])]
    merged = next(x for x in body["bookings"] if x["schedule"]["resource_codes"] == [a["code"]])
    assert merged["schedule"]["end_time"] == (
        f"{hour + 2:02d}:00" if hour <= 21 else f"{hour + 1:02d}:00"
    )
    assert all(x["order_code"] == order for x in body["bookings"])
    assert {x["payment"]["payment_status"] for x in body["bookings"]} == {"unpaid"}

    # Lịch: mã đơn trên khối, mã con để mở chi tiết
    cal = (await staff.get(f"{BK}/calendar", params={"date": today().isoformat()})).json()
    ours = [blk for blk in cal["blocks"] if blk.get("order_code") == order]
    assert sorted(blk["code"] for blk in ours) == [f"{order}-01", f"{order}-02"]

    # Tìm mã đơn -> danh sách khối
    found = (await staff.get(f"{BK}/search", params={"code": order})).json()
    assert found["kind"] == "order" and found["codes"] == [f"{order}-01", f"{order}-02"]

    async with SessionLocal() as s:
        audits = list(
            await s.scalars(
                select(AuditLog.detail).where(
                    AuditLog.action == "booking.counter.create",
                    AuditLog.entity_code.like(f"{order}-%"),
                )
            )
        )
    assert len(audits) == 2 and all(d["order_code"] == order for d in audits)


async def test_counter_order_is_all_or_nothing(staff, admin):
    hour = await safe_hour()
    a, b = await new_court(admin), await new_court(admin)
    assert (await book(staff, b["code"], hour)).status_code == 201
    r = await book_order(staff, [(a["code"], hour, hour + 1), (b["code"], hour, hour + 1)])
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "E-003"
    assert detail["conflicts"] == [{"resource_code": b["code"], "start_hour": hour}]
    # Sân A không bị giữ: đặt lại được ngay
    assert (await book(staff, a["code"], hour)).status_code == 201


async def test_counter_order_validation(staff, admin):
    hour = await safe_hour()
    a = await new_court(admin)
    r = await book_order(staff, [(a["code"], hour, hour + 1), (a["code"], hour, hour + 1)])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001"
    r = await book_order(staff, [])
    assert r.status_code == 422
    r = await staff.post(
        f"{API}/front-desk/bookings",
        json={
            "date": today().isoformat(),
            "resource_code": a["code"],
            "start_hour": hour,
            "end_hour": hour + 1,
            "blocks": [{"resource_code": a["code"], "start_hour": hour, "end_hour": hour + 1}],
            "customer": {"member_code": "HV0087"},
        },
        headers=idem(),
    )
    assert r.status_code == 422  # không gửi cả hai dạng


async def test_single_block_shape_still_works(staff, admin):
    court = await new_court(admin)
    r = await book(staff, court["code"], await safe_hour())
    raw = r.raw.json()
    assert set(raw) == {"order_code", "bookings"} and len(raw["bookings"]) == 1
    assert raw["bookings"][0]["code"] == f"{raw['order_code']}-01"
    # Chi tiết theo mã đơn một khối -> khối đó
    item = await staff.get(f"{BK}/items/{raw['order_code']}")
    assert item.status_code == 200 and item.json()["code"] == raw["bookings"][0]["code"]


# ------------------------------------------------------------------ thu cả đơn


async def test_collect_whole_order(staff, admin):
    hour = await safe_hour()
    courts = [await new_court(admin) for _ in range(3)]
    r = await book_order(staff, [(c["code"], hour, hour + 1) for c in courts])
    body = r.json()
    order = body["order_code"]
    first = body["bookings"][0]
    # Thu riêng khối 1 trước
    r = await staff.post(
        f"{BK}/items/{first['code']}/collect",
        json={"method": "cash", "version": first["version"]},
        headers=idem(),
    )
    assert r.status_code == 200

    headers = idem()
    path = f"{ORDERS}/{order.lower()}/collect"  # mã không phân biệt hoa thường
    r = await staff.post(path, json={"method": "cash"}, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["order_code"] == order
    assert out["collected"] == [f"{order}-02", f"{order}-03"]
    assert out["amount"] == sum(b["payment"]["amount"] for b in body["bookings"][1:])
    assert {b["payment"]["payment_status"] for b in out["bookings"]} == {"paid"}
    assert all(b["actions"] == ["move"] for b in out["bookings"])  # chỉ còn Đổi sân
    # Bấm lại cùng Idempotency-Key -> kết quả cũ; key mới -> không còn khối chưa thu
    again = await staff.post(path, json={"method": "cash"}, headers=headers)
    assert again.status_code == 200 and again.json() == out
    r = await staff.post(f"{ORDERS}/{order}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-4"

    r = await staff.post(
        f"{ORDERS}/BK-20000101-999/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 404 and r.json()["detail"] == {
        "code": "E-BOOK-3",
        "message": "Không tìm thấy mã đặt.",
    }
    r = await staff.post(f"{ORDERS}/{order}/collect", json={"method": "transfer"}, headers=idem())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-0"

    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "payment.collect_order", AuditLog.entity_code == order
            )
        )
    assert row.detail["codes"] == [f"{order}-02", f"{order}-03"]


async def test_collect_order_needs_permission(customer, anon):
    for client in (anon, customer):
        r = await client.post(
            f"{ORDERS}/BK-20000101-001/collect", json={"method": "cash"}, headers=idem()
        )
        assert r.status_code in (401, 403)


async def test_transactions_show_order_code(staff, admin):
    court = await new_court(admin)
    r = await book(staff, court["code"], await safe_hour())
    item = r.json()
    data = (await admin.get(f"{BK}/transactions", params={"q": item["order_code"]})).json()
    row = next(x for x in data["rows"] if x["code"] == item["code"])
    assert row["order_code"] == item["order_code"]

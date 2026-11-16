"""T-065: QR từng buổi – nội dung = mã con bỏ gạch; tiền về đúng số chỉ thu khối đó (một dòng sổ
``counter_qr``); lệch số / khối đã xử lý -> cần hoàn; mã con không bao giờ bị đọc thành mã đơn, kể
cả khi trường ``code`` của SePay chỉ có mã đơn; quyền ``booking.collect``.
"""

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import Booking, PaymentEntry, PaymentEntryItem
from app.modules.payments.models import BankTransaction
from app.modules.payments.service import extract_code
from tests.conftest import idem
from tests.helpers_booking import BK, new_court
from tests.helpers_web import checkout, sepay_payload, simulate, webhook
from tests.test_counter_qr import FD, blocks, qr, recurring

PERM = "booking.collect"


async def item_qr(client, code: str):
    return await client.get(f"{FD}/items/{code}/collect-qr")


async def entries_with(code: str) -> list[PaymentEntry]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(PaymentEntry)
                .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
                .join(Booking, Booking.id == PaymentEntryItem.booking_id)
                .where(Booking.code == code)
            )
        )


def test_child_code_wins_over_sepay_order_code():
    """AC5: SePay tách ``code`` theo mẫu BK + 11 số -> cắt mã con; đọc mã con từ nội dung trước."""
    child, order = "BK2026111000602", "BK20261110006"
    assert extract_code({"code": order, "content": f"{child} thanh toan"}) == child
    assert extract_code({"code": None, "content": f"MBVCB.123.{child}.CT"}) == child
    assert extract_code({"code": order, "content": f"{order} thanh toan"}) == order
    assert extract_code({"code": None, "content": f"FT25{order} chuyen"}) == order
    # Hai mã con khác nhau -> không đoán
    assert extract_code({"code": order, "content": f"{child} BK2026111000603"}) is None


async def test_item_qr_pays_only_that_block_then_order_qr_covers_the_rest(admin, anon):
    """AC1–AC3: QR buổi 2 -> chỉ buổi 2 Đã thanh toán, sổ 1 dòng; QR cả đơn = các buổi còn lại."""
    order = await recurring(admin, days_ahead=70)
    second = sorted(order["bookings"], key=lambda b: b["code"])[1]
    r = await item_qr(admin, second["code"])
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    info = r.json()
    pay_ref = second["code"].replace("-", "")
    assert pay_ref.startswith(order["order_code"].replace("-", ""))
    assert (info["order_code"], info["pay_ref"], info["status"], info["blocks"]) == (
        second["code"],
        pay_ref,
        "unpaid",
        1,
    )
    assert info["amount"] == second["payment"]["amount"]
    assert f"des={pay_ref}" in info["bank"]["qr_url"]

    # SePay điền ``code`` = mã đơn (cắt mã con) – tiền vẫn chỉ vào buổi 2
    payload = sepay_payload(order["order_code"].replace("-", ""), info["amount"])
    payload["content"] = f"{pay_ref} thanh toan san"
    assert (await webhook(anon, payload)).status_code == 200
    rows = {b.code: b for b in await blocks(order["order_code"])}
    assert {c: b.payment_status for c, b in rows.items()} == {
        c: ("paid" if c == second["code"] else "unpaid") for c in rows
    }
    assert (rows[second["code"]].payment_method, rows[second["code"]].collected_by_label) == (
        "transfer",
        "Hệ thống",
    )
    [entry] = await entries_with(second["code"])
    assert (entry.method, entry.source, entry.amount) == ("transfer", "counter_qr", info["amount"])
    after = (await item_qr(admin, second["code"])).json()
    assert (after["status"], after["amount"], after["blocks"]) == ("paid", 0, 0)

    rest = (await qr(admin, order["order_code"])).json()
    others = [b for b in order["bookings"] if b["code"] != second["code"]]
    assert rest["amount"] == sum(b["payment"]["amount"] for b in others)
    assert rest["blocks"] == len(others)


async def test_wrong_amount_or_handled_block_needs_refund(admin):
    """AC4: lệch số / đã thu -> cần hoàn, không đụng khối khác."""
    order = await recurring(admin, days_ahead=80)
    first = sorted(order["bookings"], key=lambda b: b["code"])[0]
    pay_ref, amount = first["code"].replace("-", ""), first["payment"]["amount"]
    assert await simulate(admin, pay_ref, amount + 1000) == "refund_needed"
    assert {b.payment_status for b in await blocks(order["order_code"])} == {"unpaid"}
    r = await admin.post(
        f"{BK}/items/{first['code']}/collect",
        json={"method": "cash", "version": first["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert await simulate(admin, pay_ref, amount) == "refund_needed"
    async with SessionLocal() as s:
        txns = list(
            await s.scalars(select(BankTransaction).where(BankTransaction.pay_ref == pay_ref))
        )
    assert {(t.outcome, t.refund_amount) for t in txns} == {
        ("refund_needed", amount + 1000),
        ("refund_needed", amount),
    }
    statuses = {b.code: b.payment_status for b in await blocks(order["order_code"])}
    assert statuses.pop(first["code"]) == "paid" and set(statuses.values()) == {"unpaid"}
    assert [e.method for e in await entries_with(first["code"])] == ["cash"]
    # Mã con không tồn tại -> không khớp
    assert await simulate(admin, "BK2000010199901", 1000) == "unmatched"


async def test_errors_and_permissions(admin, staff, customer, anon):
    """AC6 + lỗi: NV có booking.collect dùng được, gỡ quyền -> 403; vé / online -> E-PAY-1."""
    order = await recurring(admin, days_ahead=90)
    code = order["bookings"][0]["code"]
    assert (await item_qr(staff, code)).status_code == 200
    assert (await item_qr(customer, code)).status_code == 403
    async with SessionLocal() as s:
        row = await s.get(RolePermission, ("staff", PERM))
        if row is not None:
            await s.delete(row)
            await s.commit()
    try:
        assert (await item_qr(staff, code)).status_code == 403
        assert (await qr(staff, order["order_code"])).status_code == 403
    finally:
        if row is not None:
            async with SessionLocal() as s:
                s.add(RolePermission(role="staff", perm=PERM))
                await s.commit()

    r = await item_qr(admin, "BK-20000101-999-01")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-BOOK-3"
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 20)])
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    r = await item_qr(admin, f"{co['order_code']}-01")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1"


async def cancel(admin, order_code: str, codes: list[str]) -> None:
    r = await admin.post(
        f"{FD}/orders/{order_code}/cancel",
        json={"reason": "Đổi lịch", "codes": codes},
        headers=idem(),
    )
    assert r.status_code == 200, r.text


async def mark_uncollectible(codes: list[str]) -> None:
    """Máy B vừa đánh dấu Không thu được (buổi tương lai: đặt thẳng, API đòi đã tới giờ)."""
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code.in_(codes))
            .values(payment_status="uncollectible", uncollectible_reason="Máy B")
        )
        await s.commit()


async def test_closed_when_finished_without_money(admin):
    """AC8: máy B đánh dấu Không thu được nốt -> QR của máy A ``closed``, không ``paid``."""
    order = await recurring(admin, days_ahead=100)
    codes = sorted(b["code"] for b in order["bookings"])
    amounts = {b["code"]: b["payment"]["amount"] for b in order["bookings"]}
    # Buổi 1 trả bằng QR từng buổi, buổi 2 bị hủy
    assert await simulate(admin, codes[0].replace("-", ""), amounts[codes[0]]) == "applied"
    await cancel(admin, order["order_code"], [codes[1]])
    assert (await qr(admin, order["order_code"])).json()["status"] == "unpaid"

    await mark_uncollectible(codes[2:])
    whole = (await qr(admin, order["order_code"])).json()
    assert (whole["status"], whole["amount"], whole["blocks"]) == ("closed", 0, 0)
    one = (await item_qr(admin, codes[3])).json()
    assert (one["status"], one["amount"]) == ("closed", 0)
    assert (await item_qr(admin, codes[1])).json()["status"] == "closed"  # đã hủy


async def test_paid_ignores_cancelled_blocks(admin):
    """``paid`` khi mọi khối còn hiệu lực đã thu bằng tiền thật; khối hủy trước đó không tính."""
    order = await recurring(admin, days_ahead=110)
    codes = sorted(b["code"] for b in order["bookings"])
    await cancel(admin, order["order_code"], [codes[0]])
    info = (await qr(admin, order["order_code"])).json()
    assert await simulate(admin, info["pay_ref"], info["amount"]) == "applied"
    after = (await qr(admin, order["order_code"])).json()
    assert (after["status"], after["amount"]) == ("paid", 0)

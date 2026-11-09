"""T-058: "Thu cả đơn" bằng QR chuyển khoản – số tiền QR, tiền về đúng số thu cả đơn (một dòng sổ
``counter_qr``), lệch số / đã thu -> cần hoàn, gửi lại không đổi gì, chưa cài nhận tiền -> E-PAY-9.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking, BookingOrder, PaymentEntry
from app.modules.payments import api as payments_api
from app.modules.payments.models import BankTransaction
from tests.conftest import API, idem
from tests.helpers_booking import BK, new_court, random_phone, today
from tests.helpers_web import sepay_payload, simulate, webhook
from tests.test_recurring_list import create

FD = f"{API}/front-desk"


async def recurring(admin, days_ahead: int = 20, pct: int = 10) -> dict:
    """Đơn định kỳ 4 buổi (2 thứ × 2 tuần), chưa thu."""
    court = await new_court(admin)
    start = today() + timedelta(days=days_ahead)
    weekdays = (start.isoweekday(), (start + timedelta(days=1)).isoweekday())
    return await create(admin, court, "Khách QR", random_phone(), start, weekdays, pct=pct)


async def qr(client, code: str):
    return await client.get(f"{FD}/orders/{code}/collect-qr")


async def blocks(code: str) -> list[Booking]:
    async with SessionLocal() as s:
        order_id = select(BookingOrder.id).where(BookingOrder.code == code).scalar_subquery()
        return list(
            await s.scalars(
                select(Booking).where(Booking.order_id == order_id).order_by(Booking.seq)
            )
        )


async def entries_of(code: str) -> list[PaymentEntry]:
    async with SessionLocal() as s:
        return list(await s.scalars(select(PaymentEntry).where(PaymentEntry.order_code == code)))


async def test_qr_amount_then_exact_money_collects_the_whole_order(admin):
    """AC1–AC3: QR đúng tổng (đã giảm %), tiền về -> cả 4 buổi Đã thanh toán, 1 dòng sổ."""
    order = await recurring(admin)
    code = order["order_code"]
    r = await qr(admin, code)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    info = r.json()
    pay_ref = code.replace("-", "")
    assert info["order_code"] == code and info["pay_ref"] == pay_ref
    assert (info["amount"], info["status"], info["blocks"]) == (order["total"], "unpaid", 4)
    assert order["total"] < order["original_amount"]  # đã giảm %
    bank = info["bank"]
    assert bank["account_number"] == "0123456789" and bank["account_name"]
    assert f"amount={order['total']}" in bank["qr_url"] and f"des={pay_ref}" in bank["qr_url"]

    assert await simulate(admin, pay_ref, order["total"]) == "applied"
    after = (await qr(admin, code)).json()
    assert (after["status"], after["amount"], after["blocks"]) == ("paid", 0, 0)
    rows = await blocks(code)
    assert {(b.payment_status, b.payment_method, b.collected_by_label) for b in rows} == {
        ("paid", "transfer", "Hệ thống")
    }
    [entry] = await entries_of(code)
    assert (entry.kind, entry.method, entry.source) == ("in", "transfer", "counter_qr")
    assert entry.amount == order["total"] and entry.actor_label == "Hệ thống"
    assert entry.reference.startswith("sepay:sim-")

    tx = (await admin.get(f"{BK}/transactions", params={"q": code})).json()["items"]
    assert [(e["method"], e["source"], len(e["items"])) for e in tx] == [
        ("transfer", "counter_qr", 4)
    ]
    async with SessionLocal() as s:
        audits = list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "booking.counter_qr.paid", AuditLog.entity_code == code
                )
            )
        )
    assert len(audits) == 1 and audits[0].actor_type == "system"
    assert sorted(audits[0].detail["codes"]) == sorted(b.code for b in rows)


async def test_wrong_amount_or_already_paid_needs_refund(admin):
    """AC4, AC5: thiếu / thừa -> đơn giữ nguyên, cần hoàn; đã thu tiền mặt rồi -> cần hoàn."""
    order = await recurring(admin, days_ahead=30)
    code, total = order["order_code"], order["total"]
    pay_ref = code.replace("-", "")
    for amount in (total - 1000, total + 1000):
        assert await simulate(admin, pay_ref, amount) == "refund_needed"
    assert {b.payment_status for b in await blocks(code)} == {"unpaid"}
    assert await entries_of(code) == []
    async with SessionLocal() as s:
        refunds = list(
            await s.scalars(select(BankTransaction).where(BankTransaction.pay_ref == pay_ref))
        )
    assert {(t.outcome, t.refund_amount) for t in refunds} == {
        ("refund_needed", total - 1000),
        ("refund_needed", total + 1000),
    }

    r = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    assert await simulate(admin, pay_ref, total) == "refund_needed"
    assert [(e.method, e.source) for e in await entries_of(code)] == [("cash", "counter")]


async def test_resent_webhook_changes_nothing(admin, anon):
    """AC6: SePay gửi lại cùng giao dịch -> không đổi gì thêm."""
    order = await recurring(admin, days_ahead=40)
    payload = sepay_payload(order["order_code"].replace("-", ""), order["total"])
    for _ in range(2):
        assert (await webhook(anon, payload)).status_code == 200
    assert len(await entries_of(order["order_code"])) == 1
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(BankTransaction)
            .where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    assert n == 1


async def test_money_and_cash_at_once_collect_once(admin):
    order = await recurring(admin, days_ahead=50)
    code, total = order["order_code"], order["total"]
    cash = admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    money = simulate(admin, code.replace("-", ""), total)
    r, outcome = await asyncio.gather(cash, money)
    assert (r.status_code == 200) != (outcome == "applied"), (r.text, outcome)
    assert len(await entries_of(code)) == 1
    assert {b.payment_status for b in await blocks(code)} == {"paid"}


async def test_errors_permissions_and_missing_bank_settings(admin, staff, customer, monkeypatch):
    """AC7, AC8, mã lỗi: chưa cài nhận tiền -> E-PAY-9; không có đơn -> E-BOOK-3; NV -> 403."""
    order = await recurring(admin, days_ahead=60)
    code = order["order_code"]
    for client in (staff, customer):
        assert (await qr(client, code)).status_code == 403
    r = await qr(admin, "BK-20000101-999")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-BOOK-3"

    async def no_bank(*_args):
        return None

    monkeypatch.setattr(payments_api, "bank_info", no_bank)
    r = await qr(admin, code)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-PAY-9"
    assert "thu tiền mặt" in r.json()["detail"]["message"]
    monkeypatch.undo()

    # Mã đơn không tồn tại trong nội dung chuyển khoản -> không khớp như cũ
    assert await simulate(admin, "BK20000101999", 1000) == "unmatched"
    # Đơn đã hủy hết -> không còn gì để thu
    preview = (await admin.get(f"{FD}/orders/{code}/cancel-preview")).json()
    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={"reason": "Đổi lịch", "codes": [i["code"] for i in preview["cancellable"]]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    r = await qr(admin, code)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-4"

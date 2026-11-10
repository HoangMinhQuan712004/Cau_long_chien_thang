# ruff: noqa: E501
"""QA T-058 (API, AC1–AC8): "Thu cả đơn" bằng QR chuyển khoản ở Đơn đặt sân.

Góc nhìn độc lập với ``test_counter_qr.py`` của BACKEND: hình dạng hợp đồng, số tiền QR đúng bằng số "Thu cả đơn" tiền
mặt thu (kể cả khối đã bắt đầu, đã thu một phần, đã hủy / Không thu được), các cách SePay ghi mã trong nội dung,
thiếu / thừa ±1 đồng, hai người cùng trả một QR (song song), tiền mặt vs QR sau nhau, thăm dò liên tục không bị giới hạn.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Booking, BookingOrder, PaymentEntry
from app.modules.payments.models import BankTransaction
from tests.conftest import API, idem
from tests.helpers_booking import BK, book_order, new_court, random_phone, temp
from tests.helpers_web import checkout, sepay_payload, simulate, webhook
from tests.test_counter_qr import blocks, entries_of, qr, recurring

FD = f"{API}/front-desk"
FAR = (datetime.now(settings.tz) + timedelta(days=420)).date()


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz)


@pytest.fixture
def clock(monkeypatch):
    state = {"now": at(FAR, 0, 30)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int, minute: int = 0) -> None:
        state["now"] = at(day, hour, minute)

    return set_time


def ref(code: str) -> str:
    return code.replace("-", "")


async def pay(anon, code: str, amount: int, **overrides) -> tuple[str, dict]:
    """Gửi webhook SePay thật (có chữ ký). Trả (outcome, payload)."""
    payload = sepay_payload(ref(code), amount, **overrides)
    assert (await webhook(anon, payload)).status_code == 200
    async with SessionLocal() as s:
        txn = await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    return txn.outcome, payload


async def n_entries(code: str) -> int:
    return len(await entries_of(code))


async def paid_blocks(code: str) -> int:
    return sum(b.payment_status == "paid" for b in await blocks(code))


async def collect_item(admin, b, method="cash"):
    return await admin.post(
        f"{BK}/items/{b.code}/collect",
        json={"method": method, "version": b.version},
        headers=idem(),
    )


# ---------------------------------------------------------------- AC1: hợp đồng


async def test_ac1_contract_shape_and_headers(admin):
    order = await recurring(admin, days_ahead=70)
    code = order["order_code"]
    r = await qr(admin, code)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert set(d) == {"order_code", "pay_ref", "amount", "status", "blocks", "bank"}
    assert d["pay_ref"] == ref(code) and d["status"] == "unpaid" and d["blocks"] == 4
    assert set(d["bank"]) >= {"bank_name", "account_number", "account_name", "qr_url"}
    assert d["amount"] == order["total"] and d["amount"] > 0
    assert d["bank"]["qr_url"].startswith("https://") and ref(code) in d["bank"]["qr_url"]
    assert str(d["amount"]) in d["bank"]["qr_url"]
    # mã đơn gõ thường / có khoảng trắng vẫn tìm được hoặc báo gọn (không 500)
    lower = await qr(admin, code.lower())
    assert lower.status_code in (200, 404), lower.text
    # Thăm dò mỗi 3 giây suốt 15 phút = ~300 lượt: không bị giới hạn tần suất
    res = await asyncio.gather(*[qr(admin, code) for _ in range(40)])
    assert {r.status_code for r in res} == {200}


async def test_ac8_permissions(admin, staff, customer, anon):
    order = await recurring(admin, days_ahead=71)
    code = order["order_code"]
    assert (await qr(staff, code)).status_code == 403
    assert (await qr(customer, code)).status_code == 403
    assert (await qr(anon, code)).status_code == 401
    # Không rò rỉ: người không có quyền cũng không phân biệt được mã có / không có
    ghost = "BK-20000101-999"
    assert (await qr(staff, ghost)).status_code == 403
    assert (await qr(anon, ghost)).status_code == 401


# ---------------------------------------------------------------- số tiền QR = số tiền "Thu cả đơn" thu


async def test_qr_amount_equals_what_cash_collect_order_collects_in_every_state(
    admin, staff, clock
):
    d = FAR + timedelta(days=5)
    clock(d, 7)

    async def make(label: str):
        c1, c2, c3 = await new_court(admin), await new_court(admin), await new_court(admin)
        r = await book_order(
            staff,
            [(c1["code"], 10, 11), (c2["code"], 11, 12), (c3["code"], 12, 13)],
            customer=temp(label, random_phone()),
            day=d,
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def prepare(order, started: bool):
        b1, b2, b3 = order["bookings"]
        # b1 thu tiền mặt trước; b3 Không thu được / hủy tùy ca
        assert (
            await admin.post(
                f"{BK}/items/{b1['code']}/collect",
                json={"method": "cash", "version": 1},
                headers=idem(),
            )
        ).status_code == 200
        r = await admin.post(
            f"{FD}/items/{b3['code']}/cancel", json={"reason": "QA", "version": 1}, headers=idem()
        )
        assert r.status_code == 200, r.text
        if started:
            clock(d, 11, 30)  # b1 đã qua một nửa, b2 đang chơi; b3 đã hủy

    for started in (False, True):
        clock(d, 7)
        qr_order, cash_order = await make("QA QR"), await make("QA Tiền mặt")
        await prepare(qr_order, started)
        clock(d, 7)
        await prepare(cash_order, started)
        if started:
            clock(d, 11, 30)
        info = (await qr(admin, qr_order["order_code"])).json()
        collected = await admin.post(
            f"{BK}/orders/{cash_order['order_code']}/collect",
            json={"method": "cash"},
            headers=idem(),
        )
        assert collected.status_code == 200, collected.text
        assert (
            info["amount"]
            == collected.json()["amount"]
            == qr_order["bookings"][1]["payment"]["amount"]
        ), started
        assert (
            info["blocks"] == len(collected.json()["collected"]) == 1 and info["status"] == "unpaid"
        )


async def test_all_collected_or_all_cancelled_or_unknown_order_states(admin):
    order = await recurring(admin, days_ahead=72)
    code = order["order_code"]
    # Thu tiền mặt hết -> status paid, amount 0 (không phải lỗi) để popup đang hỏi lại thấy ngay
    r = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    done = await qr(admin, code)
    assert done.status_code == 200
    assert (done.json()["status"], done.json()["amount"], done.json()["blocks"]) == ("paid", 0, 0)
    # Hủy hết (đã thu -> hoàn) -> không còn khối chưa thu và cũng không có khối đã thu
    preview = (await admin.get(f"{FD}/orders/{code}/cancel-preview")).json()
    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={
            "reason": "QA",
            "codes": [i["code"] for i in preview["cancellable"]],
            "refund_confirmed": True,
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    gone = await qr(admin, code)
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "E-BOOK-4", gone.text
    missing = await qr(admin, "BK-20000101-999")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "E-BOOK-3"
    for bad in ("khong-phai-ma", "BK-1", "BK-20261106-001-01"):
        r = await qr(admin, bad)
        assert r.status_code in (404, 422), (bad, r.status_code)


# ---------------------------------------------------------------- AC2–AC6: tiền về


async def test_ac2_exact_money_collects_everything_with_one_entry_audit_and_system_collector(
    admin, anon
):
    order = await recurring(admin, days_ahead=73)
    code, total = order["order_code"], order["total"]
    outcome, payload = await pay(anon, code, total)
    assert outcome == "applied"
    rows = await blocks(code)
    assert {(b.payment_status, b.payment_method, b.collected_by_label) for b in rows} == {
        ("paid", "transfer", "Hệ thống")
    }
    assert all(b.paid_at is not None for b in rows)
    [entry] = await entries_of(code)
    assert (entry.kind, entry.method, entry.source, entry.amount) == (
        "in",
        "transfer",
        "counter_qr",
        total,
    )
    assert entry.reference == f"sepay:{payload['id']}"
    async with SessionLocal() as s:
        audits = list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "booking.counter_qr.paid", AuditLog.entity_code == code
                )
            )
        )
    assert len(audits) == 1 and audits[0].actor_type == "system"
    # Lịch sử thao tác: có trong danh mục, loại "Thu tiền", người làm Hệ thống, không lộ SĐT
    # Lịch sử thao tác: hiện dưới loại "Thu tiền" (gộp cùng thu tiền QR online), người làm Hệ thống
    log = (
        await admin.get(f"{API}/admin/audit-log", params={"action": "payment.collect", "size": 100})
    ).json()
    mine = [i for i in log["items"] if i["target"]["code"] == code]
    assert (
        len(mine) == 1 and mine[0]["actor"] == "system" and mine[0]["action_label"] == "Thu tiền"
    ), mine
    assert any("Đã thanh toán" in str(c["after"]) for c in mine[0]["changes"]), mine[0]["changes"]
    assert any("QR" in str(c["after"]) for c in mine[0]["changes"]), "ghi rõ phương thức QR"
    phone = (await blocks(code))[0].customer_phone
    assert phone and phone not in str(log) and phone not in str(audits[0].detail), (
        "không lộ SĐT khách"
    )


async def test_sua_10_11_money_after_the_five_minute_popup_is_still_accepted(admin, anon):
    """Sửa 10/11: 5 phút chỉ là thời gian popup chờ; máy chủ không hết hạn mã. Tiền đúng số về sau
    10 phút / 3 giờ / 1 ngày (giờ giao dịch trong quá khứ) vẫn thu khi đơn còn chưa thu."""
    order = await recurring(admin, days_ahead=75)
    code, total = order["order_code"], order["total"]
    first = (await qr(admin, code)).json()
    assert "expires_at" not in first and "expire" not in str(first).lower(), "không có hạn dùng mã"

    def vn_time(minutes_ago: int) -> str:
        return (datetime.now(settings.tz) - timedelta(minutes=minutes_ago)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    # Tạo lại mã sau 5 phút cho cùng số tiền; lệch số vẫn bị từ chối dù giao dịch cũ
    for minutes_ago in (10, 180, 24 * 60):
        again = (await qr(admin, code)).json()
        assert again["status"] != "paid" and again["amount"] == total
        outcome, _ = await pay(anon, code, total - 1, transactionDate=vn_time(minutes_ago))
        assert outcome == "refund_needed"
    outcome, _ = await pay(anon, code, total, transactionDate=vn_time(10))
    assert outcome == "applied", "tiền đúng số về sau 5 phút vẫn nhận"
    assert {b.payment_status for b in await blocks(code)} == {"paid"}
    assert (await qr(admin, code)).json()["status"] == "paid"


async def test_ac4_off_by_one_short_or_over_never_collects_and_exact_still_works_afterwards(
    admin, anon
):
    order = await recurring(admin, days_ahead=74)
    code, total = order["order_code"], order["total"]
    for amount in (total - 1, total + 1, 1, total * 2):
        outcome, _ = await pay(anon, code, amount)
        assert outcome == "refund_needed", amount
    assert await paid_blocks(code) == 0 and await n_entries(code) == 0
    async with SessionLocal() as s:
        refunds = list(
            await s.scalars(
                select(BankTransaction).where(
                    BankTransaction.outcome == "refund_needed",
                    BankTransaction.content.contains(ref(code)),
                )
            )
        )
    assert sorted(t.refund_amount for t in refunds) == sorted([total - 1, total + 1, 1, total * 2])
    assert all(ref(code) in (t.pay_ref or ref(code)) for t in refunds)
    # Sau các lượt sai, chuyển đúng số vẫn thu được
    assert (await pay(anon, code, total))[0] == "applied"
    assert await paid_blocks(code) == 4 and await n_entries(code) == 1


async def test_partial_cash_first_makes_the_old_total_a_mismatch_and_new_total_exact(admin, anon):
    order = await recurring(admin, days_ahead=75)
    code, total = order["order_code"], order["total"]
    first = (await blocks(code))[0]
    assert (await collect_item(admin, first)).status_code == 200
    remaining = (await qr(admin, code)).json()
    assert remaining["amount"] == total - first.amount and remaining["blocks"] == 3
    assert (await pay(anon, code, total))[0] == "refund_needed", "QR cũ in theo tổng cũ: lệch số"
    assert (await pay(anon, code, remaining["amount"]))[0] == "applied"
    assert await paid_blocks(code) == 4
    entries = await entries_of(code)
    assert sorted((e.method, e.source, e.amount) for e in entries) == sorted(
        [("cash", "counter", first.amount), ("transfer", "counter_qr", remaining["amount"])]
    )


async def test_ac5_cash_after_qr_and_qr_after_cash_never_collect_twice(admin, anon):
    qr_first = await recurring(admin, days_ahead=76)
    code = qr_first["order_code"]
    assert (await pay(anon, code, qr_first["total"]))[0] == "applied"
    r = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 409, "đã thu bằng QR rồi: không thu tiền mặt thêm"
    assert await n_entries(code) == 1

    cash_first = await recurring(admin, days_ahead=77)
    code2 = cash_first["order_code"]
    r = await admin.post(f"{BK}/orders/{code2}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200
    assert (await pay(anon, code2, cash_first["total"]))[0] == "refund_needed"
    assert await n_entries(code2) == 1 and await paid_blocks(code2) == 4
    assert {b.payment_method for b in await blocks(code2)} == {"cash"}, (
        "không đổi phương thức đã thu"
    )


async def test_ac6_resend_same_id_in_parallel_and_two_payers_collect_once(admin, anon):
    order = await recurring(admin, days_ahead=78)
    code, total = order["order_code"], order["total"]
    payload = sepay_payload(ref(code), total)
    res = await asyncio.gather(*[webhook(anon, payload) for _ in range(5)])
    assert {r.status_code for r in res} == {200}
    assert await n_entries(code) == 1 and await paid_blocks(code) == 4
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(BankTransaction)
            .where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    assert n == 1

    # Hai người cùng quét một QR và cùng trả đúng số (id khác nhau): chỉ một thu được, còn lại cần hoàn
    other = await recurring(admin, days_ahead=79)
    code2, total2 = other["order_code"], other["total"]
    outs = await asyncio.gather(*[pay(anon, code2, total2) for _ in range(5)])
    got = sorted(o for o, _ in outs)
    assert got.count("applied") == 1 and got.count("refund_needed") == 4, got
    assert await n_entries(code2) == 1 and await paid_blocks(code2) == 4


async def test_ac4_ac5_cash_and_qr_money_race_has_exactly_one_collector(admin, anon):
    for days in (80, 81, 82):
        order = await recurring(admin, days_ahead=days)
        code, total = order["order_code"], order["total"]
        cash = admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
        money = pay(anon, code, total)
        r, (outcome, _) = await asyncio.gather(cash, money)
        assert (r.status_code == 200) != (outcome == "applied"), (r.status_code, outcome)
        assert await n_entries(code) == 1 and await paid_blocks(code) == 4
        methods = {b.payment_method for b in await blocks(code)}
        assert methods == ({"cash"} if r.status_code == 200 else {"transfer"})


# ---------------------------------------------------------------- cách SePay ghi mã trong nội dung


async def test_code_extraction_variants_and_unmatched_cases(admin, anon):
    order = await recurring(admin, days_ahead=83)
    code, total = order["order_code"], order["total"]
    other = await recurring(admin, days_ahead=84)
    # Nội dung có hai mã khác nhau -> không đoán (unmatched), không thu đơn nào
    both = sepay_payload(None, total, content=f"CK {ref(code)} va {ref(other['order_code'])}")
    assert (await webhook(anon, both)).status_code == 200
    assert await paid_blocks(code) == 0 and await paid_blocks(other["order_code"]) == 0
    # Mã nằm trong nội dung (code null), chữ thường, kèm chữ khác
    text = sepay_payload(
        None, total, content=f"nguyen van a chuyen khoan {ref(code).lower()} cam on"
    )
    assert (await webhook(anon, text)).status_code == 200
    assert await paid_blocks(code) == 4 and await n_entries(code) == 1
    # Mã có gạch ngang trong nội dung không phải mẫu BK + 11 số: không khớp, không thu
    dashed = sepay_payload(None, other["total"], content=f"CK {other['order_code']}")
    assert (await webhook(anon, dashed)).status_code == 200
    assert await paid_blocks(other["order_code"]) == 0
    # Tiền ra (out) / sai tài khoản nhận: bỏ qua
    for extra in ({"transferType": "out"}, {"accountNumber": "9999999999"}):
        p = sepay_payload(ref(other["order_code"]), other["total"], **extra)
        assert (await webhook(anon, p)).status_code == 200
        assert await paid_blocks(other["order_code"]) == 0, extra
    # transactionDate hỏng: không lỗi 5xx, rơi về giờ hiện tại
    p = sepay_payload(ref(other["order_code"]), other["total"], transactionDate="không phải ngày")
    assert (await webhook(anon, p)).status_code == 200
    assert await paid_blocks(other["order_code"]) == 4
    [entry] = await entries_of(other["order_code"])
    assert abs((entry.occurred_at - datetime.now(settings.tz)).total_seconds()) < 120


async def test_online_checkout_pay_ref_is_not_confused_with_counter_orders(admin, anon):
    """Hồi quy T-008: lượt online vẫn thu theo đường cũ, không chạm đơn quầy cùng dãy số."""
    counter = await recurring(admin, days_ahead=85)
    court = await new_court(admin)
    r = await checkout(
        anon,
        [(court["code"], 19)],
        day=(datetime.now(settings.tz) + timedelta(days=2)).date(),
        phone=random_phone(),
    )
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["pay_ref"] != ref(counter["order_code"])
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    assert (
        await paid_blocks(counter["order_code"]) == 0
        and await n_entries(counter["order_code"]) == 0
    )
    async with SessionLocal() as s:
        online = list(
            await s.scalars(select(Booking).where(Booking.code.like(f"{co['order_code']}-%")))
        )
        orders = await s.scalar(
            select(func.count())
            .select_from(BookingOrder)
            .where(BookingOrder.code == co["order_code"])
        )
        entries = list(
            await s.scalars(select(PaymentEntry).where(PaymentEntry.order_code == co["order_code"]))
        )
    assert orders == 1 and {b.payment_status for b in online} == {"paid"}
    assert [(e.source, e.method) for e in entries] == [("online", "online_transfer")]

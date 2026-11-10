# ruff: noqa: E501
"""QA T-064 (API): "Không thu được" cả đơn – ``POST /booking/orders/{code}/uncollectible``.

Góc nhìn độc lập với ``test_order_uncollectible.py`` của BACKEND: biên đúng giây ``start_at`` (≤ now), đơn lẫn khối
đã thu / chưa thu / chưa tới giờ, trạng thái đơn theo T-039 AC7 và các tab / số đếm của Đơn đặt sân, không động tới
tiền (không dòng sổ, thu cả đơn sau đó chỉ lấy phần còn lại), QR sau khi đánh dấu (lệch số → cần hoàn), lý do biên,
quyền, Origin, Idempotency-Key, đồng thời, khung vẫn chiếm chỗ trên lịch. Đồng hồ engine đóng băng ở ngày xa.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Booking, PaymentEntry
from app.modules.payments.models import BankTransaction
from tests.conftest import API, idem
from tests.helpers_booking import BK, new_court, random_phone
from tests.helpers_web import sepay_payload, webhook
from tests.test_recurring_list import create

FD = f"{API}/front-desk"
FAR = (datetime.now(settings.tz) + timedelta(days=260)).date()


def at(day, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=settings.tz)


@pytest.fixture
def clock(monkeypatch):
    state = {"now": at(FAR, 8)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int, minute: int = 0, second: int = 0) -> None:
        state["now"] = at(day, hour, minute, second)

    return set_time


async def recurring(admin, clock, offset: int) -> tuple[dict, list[str], object]:
    """Đơn định kỳ 4 buổi 18–20h: ``start``, ``start+1``, ``start+7``, ``start+8``. Trả (đơn, mã con đã sắp xếp, start)."""
    clock(FAR, 8)
    start = FAR + timedelta(days=offset)
    court = await new_court(admin)
    weekdays = (start.isoweekday(), (start + timedelta(days=1)).isoweekday())
    order = await create(admin, court, "QA Bỏ Về", random_phone(), start, weekdays)
    codes = sorted(b["code"] for b in order["bookings"])
    assert len(codes) == 4
    return order, codes, start


async def mark(client, code: str, reason: str | None = "", headers: dict | None = None, **kw):
    body = {} if reason is None else {"reason": reason}
    return await client.post(
        f"{BK}/orders/{code}/uncollectible", json=body, headers=headers or idem(), **kw
    )


async def status_of(admin, codes: list[str]) -> dict[str, str]:
    async with SessionLocal() as s:
        rows = await s.scalars(select(Booking).where(Booking.code.in_(codes)))
        return {b.code: b.payment_status for b in rows}


async def order_row(admin, order_code: str) -> dict:
    r = await admin.get(f"{FD}/orders", params={"q": order_code, "size": 5})
    assert r.status_code == 200, r.text
    [row] = [x for x in r.json()["items"] if x["order_code"] == order_code]
    return row


async def audit_rows(codes: list[str]) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "payment.uncollectible", AuditLog.entity_code.in_(codes)
                )
            )
        )


async def entries(order_code: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(PaymentEntry)
            .where(PaymentEntry.order_code == order_code)
        )


async def pay_qr(anon, order_code: str, amount: int) -> str:
    payload = sepay_payload(order_code.replace("-", ""), amount)
    assert (await webhook(anon, payload)).status_code == 200
    async with SessionLocal() as s:
        txn = await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    return txn.outcome


# ---------------------------------------------------------------- biên giờ


async def test_boundary_exactly_at_start_counts_as_started_one_second_before_does_not(admin, clock):
    order, codes, start = await recurring(admin, clock, 3)
    clock(start, 17, 59, 59)  # 1 giây trước giờ bắt đầu buổi 1
    r = await mark(admin, order["order_code"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1", r.text
    assert set((await status_of(admin, codes)).values()) == {"unpaid"}
    assert await audit_rows(codes) == []
    clock(start, 18, 0, 0)  # đúng giây bắt đầu: start_at ≤ now
    r = await mark(admin, order["order_code"])
    assert r.status_code == 200, r.text
    assert (r.json()["marked"], r.json()["remaining_unpaid"]) == (codes[:1], codes[1:])


# ---------------------------------------------------------------- đơn lẫn trạng thái


async def test_paid_blocks_are_untouched_and_order_status_follows_t039(admin, clock):
    order, codes, start = await recurring(admin, clock, 5)
    oc = order["order_code"]
    # Buổi 1 thu tiền mặt; buổi 2 sẽ bị đánh dấu; buổi 3, 4 chưa tới giờ
    r = await admin.post(
        f"{BK}/items/{codes[0]}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )
    assert r.status_code == 200, r.text
    clock(start + timedelta(days=1), 18, 30)
    r = await mark(admin, oc, "Khách bận")
    assert r.status_code == 200, r.text
    assert (r.json()["marked"], r.json()["remaining_unpaid"]) == ([codes[1]], codes[2:])
    st = await status_of(admin, codes)
    assert st[codes[0]] == "paid", "buổi đã thu không bị chạm"
    assert st[codes[1]] == "uncollectible" and st[codes[2]] == st[codes[3]] == "unpaid"
    assert (await order_row(admin, oc))["status"] == "unpaid", (
        "còn buổi chưa thu → ở lại Chưa thanh toán"
    )
    # Hết giờ cả đơn: đánh dấu nốt; đơn chỉ còn paid + uncollectible → tab Không thu được
    clock(start + timedelta(days=9), 8)
    r = await mark(admin, oc)
    assert r.status_code == 200 and r.json()["marked"] == codes[2:], r.text
    assert (await order_row(admin, oc))["status"] == "uncollectible"
    listing = (await admin.get(f"{FD}/orders", params={"status": "uncollectible", "q": oc})).json()
    assert [x["order_code"] for x in listing["items"]] == [oc]
    assert (await admin.get(f"{FD}/orders", params={"status": "unpaid", "q": oc})).json()[
        "items"
    ] == []
    assert (
        listing["counts"]["all"]["uncollectible"] == 1 and listing["counts"]["all"]["unpaid"] == 0
    )
    # Hết khối chưa thu → E-BOOK-4 cho cả đánh dấu lẫn thu cả đơn; QR báo `closed`
    for call in (
        mark(admin, oc),
        admin.post(f"{BK}/orders/{oc}/collect", json={"method": "cash"}, headers=idem()),
    ):
        r = await call
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-BOOK-4", r.text
    # QR: hết khối chưa thu nhưng có khối Không thu được → `closed` (T-065), không phải "Đã nhận tiền"
    r = await admin.get(f"{FD}/orders/{oc}/collect-qr")
    assert r.status_code == 200 and r.json()["amount"] == 0 and r.json()["status"] == "closed", (
        r.text
    )
    # Tiền: không có dòng sổ nào cho đơn này ngoài lần thu tiền mặt buổi 1
    assert await entries(oc) == 1


async def test_remaining_collect_and_qr_use_only_what_is_still_unpaid_late_money_needs_refund(
    admin, anon, clock
):
    order, codes, start = await recurring(admin, clock, 9)
    oc = order["order_code"]
    clock(start, 19)
    qr_before = (await admin.get(f"{FD}/orders/{oc}/collect-qr")).json()
    assert qr_before["status"] == "unpaid"
    total_before = qr_before["amount"]
    r = await mark(admin, oc)
    assert r.status_code == 200 and r.json()["marked"] == codes[:1], r.text
    qr_after = (await admin.get(f"{FD}/orders/{oc}/collect-qr")).json()
    assert qr_after["amount"] < total_before, "số tiền QR chỉ còn phần chưa thu"
    # Tiền về theo mã QR cũ (đủ số cũ) → lệch số chưa thu → cần hoàn, đơn giữ nguyên
    assert await pay_qr(anon, oc, total_before) == "refund_needed"
    assert (await status_of(admin, codes))[codes[0]] == "uncollectible"
    assert await entries(oc) == 0
    # Tiền đúng số mới → thu phần còn lại, buổi đã đánh dấu vẫn Không thu được
    assert await pay_qr(anon, oc, qr_after["amount"]) == "applied"
    st = await status_of(admin, codes)
    assert st[codes[0]] == "uncollectible" and {st[c] for c in codes[1:]} == {"paid"}
    assert (await order_row(admin, oc))["status"] == "uncollectible"


async def test_cash_collect_after_marking_takes_only_the_remaining_blocks(admin, clock):
    order, codes, start = await recurring(admin, clock, 11)
    oc = order["order_code"]
    clock(start, 19)
    assert (await mark(admin, oc)).status_code == 200
    r = await admin.post(f"{BK}/orders/{oc}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    st = await status_of(admin, codes)
    assert st[codes[0]] == "uncollectible" and {st[c] for c in codes[1:]} == {"paid"}, (
        "Không thu được là trạng thái cuối"
    )


# ---------------------------------------------------------------- khung, hành động, nhật ký, lý do


async def test_slot_stays_occupied_actions_closed_and_one_audit_row_per_block_with_reason(
    admin, clock
):
    order, codes, start = await recurring(admin, clock, 13)
    oc = order["order_code"]
    clock(start + timedelta(days=1), 19)
    reason = "Khách " + "ê" * 194  # đúng 200 ký tự
    assert len(reason) == 200
    r = await mark(admin, oc, f"  {reason}  ")
    assert r.status_code == 200, r.text
    out = r.json()
    for b in out["bookings"]:
        if b["code"] in out["marked"]:
            assert b["payment"]["payment_status"] == "uncollectible"
            assert "collect" not in b["actions"] and "uncollectible" not in b["actions"], b[
                "actions"
            ]
        else:
            assert b["payment"]["payment_status"] == "unpaid"
    logs = await audit_rows(codes)
    assert sorted(a.entity_code for a in logs) == codes[:2]
    for a in logs:
        assert {"field": "Lý do", "before": None, "after": reason} in a.detail["changes"], a.detail
    # Khung vẫn chiếm chỗ trên lịch (đã đánh dấu chưa trả sân)
    cal = (await admin.get(f"{BK}/calendar", params={"date": start.isoformat()})).json()
    assert codes[0] in str(cal), "khối Không thu được vẫn hiện trên lịch"


@pytest.mark.parametrize(
    "reason, expect_ok",
    [
        ("", True),
        ("   ", True),
        ("<script>alert(1)</script> & 'x' \"y\"", True),
        ("😀 không đến", True),
        ("x" * 200, True),
        ("x" * 201, False),
        ("x" * 501, False),
    ],
)
async def test_reason_edges(admin, clock, reason, expect_ok):
    order, codes, start = await recurring(admin, clock, 15)
    clock(start, 19)
    r = await mark(admin, order["order_code"], reason)
    if not expect_ok:
        assert r.status_code == 422, r.text
        if len(reason) <= 500:  # 201–500: E-001 của nghiệp vụ; >500: kiểm tra định dạng của DTO
            assert r.json()["detail"]["code"] == "E-001", r.text
        assert set((await status_of(admin, codes)).values()) == {"unpaid"}, "lỗi thì không đánh dấu"
        assert await audit_rows(codes) == []
        return
    assert r.status_code == 200, r.text
    [log] = await audit_rows(codes)
    fields = [c["field"] for c in log.detail["changes"]]
    if reason.strip():
        assert {"field": "Lý do", "before": None, "after": reason.strip()} in log.detail["changes"]
    else:
        assert "Lý do" not in fields, "để trống thì audit không có ô Lý do"


async def test_reason_missing_or_null_does_not_crash(admin, clock):
    order, codes, start = await recurring(admin, clock, 17)
    clock(start, 19)
    r = await admin.post(
        f"{BK}/orders/{order['order_code']}/uncollectible", json={"reason": None}, headers=idem()
    )
    assert r.status_code in (200, 422), r.text
    r = await mark(admin, order["order_code"], reason=None)  # không có khóa reason
    assert r.status_code in (200, 422, 409), r.text
    assert r.status_code != 500


# ---------------------------------------------------------------- quyền, Origin, khóa, đồng thời


async def test_permissions_origin_idempotency_and_concurrency(admin, staff, customer, anon, clock):
    order, codes, start = await recurring(admin, clock, 19)
    oc = order["order_code"]
    clock(start, 19)
    assert (await mark(anon, oc)).status_code == 401
    assert (await mark(customer, oc)).status_code == 403
    miss = await admin.post(f"{BK}/orders/{oc}/uncollectible", json={"reason": ""})
    assert miss.status_code in (400, 422), miss.text
    evil = await mark(admin, oc, headers={**idem(), "Origin": "https://evil.example"})
    assert evil.status_code == 403, evil.text
    assert set((await status_of(admin, codes)).values()) == {"unpaid"}, (
        "các lần bị từ chối không đổi gì"
    )
    # Nhân viên mất quyền booking.uncollectible → 403
    perm = Perm.BOOKING_UNCOLLECTIBLE.value
    async with SessionLocal() as s:
        had = await s.scalar(
            select(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == perm
            )
        )
        if had is not None:
            await s.delete(had)
            await s.commit()
    try:
        assert (await mark(staff, oc)).status_code == 403
    finally:
        if had is not None:
            async with SessionLocal() as s:
                s.add(RolePermission(role="staff", perm=perm))
                await s.commit()
    # 4 lượt song song (Admin + NV, khóa khác nhau) → đúng một lượt đánh dấu
    rs = await asyncio.gather(mark(admin, oc), mark(staff, oc), mark(admin, oc), mark(staff, oc))
    codes_status = sorted(r.status_code for r in rs)
    assert codes_status.count(200) == 1 and all(c in (200, 422, 409) for c in codes_status), [
        r.text for r in rs
    ]
    assert len(await audit_rows(codes)) == 1, "chỉ một dòng nhật ký cho buổi đã tới giờ"
    # Gửi lại đúng khóa của lượt thắng → cùng kết quả, không thêm dòng
    key = idem()
    other, other_codes, other_start = await recurring(admin, clock, 21)
    clock(other_start, 19)
    a = await mark(admin, other["order_code"], headers=key)
    b = await mark(admin, other["order_code"], headers=key)
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert len(await audit_rows(other_codes)) == 1
    # Cùng khóa nhưng đổi lý do → không áp lần hai
    c = await mark(admin, other["order_code"], reason="khác", headers=key)
    assert c.status_code in (409, 422), c.text
    assert len(await audit_rows(other_codes)) == 1


async def test_unknown_and_odd_order_codes_never_5xx(admin, clock):
    clock(FAR, 8)
    for code in (
        "BK-20000101-999",
        "bk-20000101-999",
        "BK-20000101-999-01",
        "x" * 50,
        "%",
        "BK-2026",
    ):
        r = await mark(admin, code)
        assert r.status_code in (404, 422), (code, r.status_code, r.text)


async def test_order_with_nothing_paid_and_all_marked_has_no_qr(admin, clock):
    order, codes, start = await recurring(admin, clock, 23)
    oc = order["order_code"]
    clock(start + timedelta(days=9), 8)
    r = await mark(admin, oc)
    assert r.status_code == 200 and r.json()["marked"] == codes, r.text
    assert (await order_row(admin, oc))["status"] == "uncollectible"
    r = await admin.get(f"{FD}/orders/{oc}/collect-qr")
    assert r.status_code == 200 and (r.json()["status"], r.json()["amount"]) == ("closed", 0), (
        r.text
    )
    assert await entries(oc) == 0

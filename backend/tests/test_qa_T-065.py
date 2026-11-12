# ruff: noqa: E501
"""QA T-065 (API, AC1–AC8): QR từng buổi (mã con bỏ gạch), QR cho mọi người có ``booking.collect``, ``status`` unpaid / paid / closed.

Góc nhìn độc lập với ``test_item_collect_qr.py`` của BACKEND: mọi cách ngân hàng ghi nội dung (chỉ ``content``, ``code`` chỉ có mã đơn như SePay
thật, chữ thường, dính tiền tố của ngân hàng, cả mã đơn lẫn mã con), tiền lệch ±1 / gấp đôi / đúng số của cả đơn dán vào mã con, khối đã thu
tiền mặt / đã hủy / Không thu được, trùng giao dịch và nhiều người trả cùng lúc, tiền mặt ‖ QR trên cùng một khối, tiền về trễ, sổ tiền +
nhật ký, quyền, ``status`` ở mọi trạng thái, mã lạ không 5xx.
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import Booking, PaymentEntry, PaymentEntryItem
from app.modules.payments.models import BankTransaction
from tests.conftest import idem
from tests.helpers_booking import BK, new_court
from tests.helpers_web import checkout, sepay_payload, simulate, webhook
from tests.test_counter_qr import FD, blocks, qr, recurring

KEYS = {"order_code", "pay_ref", "amount", "status", "blocks", "bank", "qr_paid"}  # T-072


def ref(code: str) -> str:
    return code.replace("-", "")


async def item_qr(client, code: str):
    return await client.get(f"{FD}/items/{code}/collect-qr")


async def pay(anon, amount: int, content: str, code: str | None = None, **kw) -> tuple[str, dict]:
    """Webhook SePay thật. ``code`` = trường SePay tự tách (thường chỉ là mã đơn). Trả (outcome, payload)."""
    payload = sepay_payload(code, amount, content=content, **kw)
    assert (await webhook(anon, payload)).status_code == 200
    async with SessionLocal() as s:
        txn = await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    return txn.outcome, payload


async def states(order_code: str) -> dict[str, str]:
    return {b.code: b.payment_status for b in await blocks(order_code)}


async def n_entries(order_code: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(PaymentEntry)
            .where(PaymentEntry.order_code == order_code)
        )


async def sorted_blocks(admin, days_ahead: int):
    order = await recurring(admin, days_ahead=days_ahead)
    rows = sorted(await blocks(order["order_code"]), key=lambda b: b.code)
    return order, rows


# ---------------------------------------------------------------- AC1: hợp đồng QR từng buổi


async def test_ac1_item_qr_contract_amount_pay_ref_and_error_states(admin, anon, customer):
    order, rows = await sorted_blocks(admin, 90)
    b = rows[1]
    r = await item_qr(admin, b.code)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    info = r.json()
    assert set(info) == KEYS
    assert (
        info["order_code"],
        info["pay_ref"],
        info["amount"],
        info["status"],
        info["blocks"],
    ) == (
        b.code,
        ref(b.code),
        b.amount,
        "unpaid",
        1,
    )
    assert info["pay_ref"].startswith(ref(order["order_code"])), "mã con bắt đầu bằng mã đơn chung"
    assert f"amount={b.amount}" in info["bank"]["qr_url"] and ref(b.code) in info["bank"]["qr_url"]
    # Hỏi lại 3 giây / lần (mô phỏng 40 lượt song song) không bị giới hạn tần suất
    rs = await asyncio.gather(*[item_qr(admin, b.code) for _ in range(40)])
    assert {x.status_code for x in rs} == {200}
    # Mã lạ không 5xx; khối của booking online → E-PAY-1
    assert (await item_qr(admin, "BK-20000101-999-01")).status_code == 404
    for bad in ("khong-phai-ma", "BK-1", "%", "x" * 60):
        assert (await item_qr(admin, bad)).status_code in (404, 422), bad
    court = await new_court(admin)
    co = (await checkout(anon, [(court["code"], 19)])).json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    r = await item_qr(admin, co["order_code"] + "-01")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1", r.text


# ---------------------------------------------------------------- AC2, AC5: cách ghi nội dung


async def test_ac2_ac5_child_code_pays_only_its_block_in_every_bank_notation(admin, anon):
    order, rows = await sorted_blocks(admin, 92)
    oc = order["order_code"]
    notations = [
        # (chỉ content, code SePay tự tách = mã đơn)  – đúng như SePay thật cắt "BK + 11 số"
        lambda c: (f"{ref(c)} thanh toan san", ref(c)[:13]),
        lambda c: (f"{ref(c)} thanh toan san", None),
        lambda c: (f"mbvcb.123.{ref(c).lower()}.ct", ref(c)[:13].lower()),
        lambda c: (f"FT25{ref(c)} chuyen khoan", ref(c)[:13]),
        lambda c: (
            f"{ref(c)[:13]} {ref(c)} qr",
            ref(c)[:13],
        ),  # cả mã đơn lẫn mã con → mã con thắng
    ]
    for block, note in zip(rows, notations, strict=False):
        content, code = note(block.code)
        before = await states(oc)
        outcome, payload = await pay(anon, block.amount, content, code)
        assert outcome == "applied", (content, code, outcome)
        after = await states(oc)
        changed = {c for c in after if after[c] != before[c]}
        assert changed == {block.code}, f"chỉ khối {block.code} đổi, thực tế {changed}"
        assert after[block.code] == "paid"
    assert await n_entries(oc) == len(list(zip(rows, notations, strict=False))), (
        "mỗi lần tiền về một dòng sổ"
    )
    # Khối đã thu: chuyển tiếp cùng mã con → cần hoàn, không đổi gì
    first = rows[0]
    outcome, _ = await pay(anon, first.amount, ref(first.code), ref(first.code)[:13])
    assert outcome == "refund_needed"


async def test_ac2_entry_audit_and_collector_of_a_block_payment(admin, anon):
    order, rows = await sorted_blocks(admin, 94)
    b = rows[0]
    outcome, payload = await pay(anon, b.amount, ref(b.code), ref(b.code)[:13])
    assert outcome == "applied"
    async with SessionLocal() as s:
        entry = (
            await s.execute(
                select(PaymentEntry)
                .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
                .join(Booking, Booking.id == PaymentEntryItem.booking_id)
                .where(Booking.code == b.code)
            )
        ).scalar_one()
        items = (
            await s.scalars(select(PaymentEntryItem).where(PaymentEntryItem.entry_id == entry.id))
        ).all()
        audits = list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "booking.counter_qr.paid", AuditLog.entity_code == b.code
                )
            )
        )
    assert (entry.kind, entry.method, entry.source, entry.amount) == (
        "in",
        "transfer",
        "counter_qr",
        b.amount,
    )
    assert entry.reference == f"sepay:{payload['id']}" and entry.actor_label == "Hệ thống"
    assert len(items) == 1 and items[0].amount == b.amount
    assert len(audits) == 1 and audits[0].actor_type == "system"
    row = [x for x in await blocks(order["order_code"]) if x.code == b.code][0]
    assert (row.payment_status, row.payment_method, row.collected_by_label) == (
        "paid",
        "transfer",
        "Hệ thống",
    )
    assert row.paid_at is not None
    # Hiện ở Lịch sử giao dịch với mã con
    day = datetime.now(settings.tz).date()
    tx = (
        await admin.get(
            f"{BK}/transactions",
            params={
                "from": (day - timedelta(days=1)).isoformat(),
                "to": day.isoformat(),
                "q": b.code,
            },
        )
    ).json()
    assert any(i["code"] == b.code for e in tx["items"] for i in e["items"])


# ---------------------------------------------------------------- AC4: lệch số, khối không còn thu được


async def test_ac4_wrong_amount_or_non_collectible_block_needs_refund_and_touches_nothing(
    admin, anon
):
    order, rows = await sorted_blocks(admin, 96)
    oc = order["order_code"]
    target, cash, cancelled, bad = rows
    # Lệch ±1, gấp đôi, đúng số của CẢ ĐƠN dán vào mã con → hoàn, khối giữ nguyên, không dòng sổ
    total = sum(b.amount for b in rows)
    for amount in (target.amount - 1, target.amount + 1, target.amount * 2, total, 1):
        outcome, _ = await pay(anon, amount, ref(target.code), ref(target.code)[:13])
        assert outcome == "refund_needed", amount
    assert set((await states(oc)).values()) == {"unpaid"} and await n_entries(oc) == 0
    # Khối đã thu tiền mặt / đã hủy / Không thu được → hoàn
    assert (
        await admin.post(
            f"{BK}/items/{cash.code}/collect", json={"method": "cash", "version": 1}, headers=idem()
        )
    ).status_code == 200
    preview = (await admin.get(f"{FD}/orders/{oc}/cancel-preview")).json()
    assert cancelled.code in [i["code"] for i in preview["cancellable"]]
    r = await admin.post(
        f"{FD}/orders/{oc}/cancel",
        json={"reason": "QA", "codes": [cancelled.code], "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code == bad.code)
            .values(payment_status="uncollectible", uncollectible_reason="Máy B")
        )
        await s.commit()
    entries_before = await n_entries(oc)
    for blk in (cash, cancelled, bad):
        outcome, _ = await pay(anon, blk.amount, ref(blk.code), ref(blk.code)[:13])
        assert outcome == "refund_needed", blk.code
    st = await states(oc)
    assert (st[target.code], st[cash.code], st[cancelled.code], st[bad.code]) == (
        "unpaid",
        "paid",
        "cancelled",
        "uncollectible",
    )
    assert await n_entries(oc) == entries_before, "tiền cần hoàn không vào sổ"
    # Mã con lạ (cùng đơn, số thứ tự không có) → không khớp, không đụng gì
    outcome, _ = await pay(anon, 100_000, f"{ref(oc)}99", ref(oc))
    assert outcome in ("unmatched", "refund_needed")
    assert (await states(oc))[target.code] == "unpaid"
    # Và đúng số vẫn thu được sau mọi lần lệch
    outcome, _ = await pay(anon, target.amount, ref(target.code), ref(target.code)[:13])
    assert outcome == "applied"


# ---------------------------------------------------------------- AC3, AC5: QR cả đơn sau khi thu lẻ


async def test_ac3_ac5_order_qr_after_one_block_paid_covers_only_the_rest(admin, anon):
    order, rows = await sorted_blocks(admin, 98)
    oc = order["order_code"]
    full = (await qr(admin, oc)).json()
    assert full["amount"] == sum(b.amount for b in rows) and full["pay_ref"] == ref(oc)
    outcome, _ = await pay(anon, rows[1].amount, ref(rows[1].code), ref(oc))
    assert outcome == "applied"
    rest = (await qr(admin, oc)).json()
    assert (
        rest["status"] == "unpaid"
        and rest["blocks"] == 3
        and rest["amount"] == full["amount"] - rows[1].amount
    )
    # QR cả đơn cũ (tổng cũ) → lệch số → hoàn; không thu nhầm
    outcome, _ = await pay(anon, full["amount"], ref(oc), ref(oc))
    assert outcome == "refund_needed"
    # Mã con của khối còn lại, nhưng số của CẢ phần còn lại → hoàn (mã con không bị đọc thành mã đơn)
    outcome, _ = await pay(anon, rest["amount"], ref(rows[0].code), ref(oc))
    assert outcome == "refund_needed"
    assert (await states(oc))[rows[0].code] == "unpaid"
    # QR cả đơn đúng số mới → thu các khối còn lại; khối đã thu bằng QR lẻ giữ nguyên một dòng sổ
    outcome, _ = await pay(anon, rest["amount"], ref(oc), ref(oc))
    assert outcome == "applied"
    assert set((await states(oc)).values()) == {"paid"}
    assert await n_entries(oc) == 2
    done = (await qr(admin, oc)).json()
    assert (done["status"], done["amount"]) == ("paid", 0)


# ---------------------------------------------------------------- trùng, đồng thời


async def test_replay_duplicates_and_races_collect_a_block_exactly_once(admin, anon):
    order, rows = await sorted_blocks(admin, 100)
    oc = order["order_code"]
    a, b = rows[0], rows[1]
    payload = sepay_payload(ref(oc), a.amount, content=ref(a.code))
    rs = await asyncio.gather(*[webhook(anon, payload) for _ in range(5)])
    assert {r.status_code for r in rs} == {200}
    async with SessionLocal() as s:
        n_txn = await s.scalar(
            select(func.count())
            .select_from(BankTransaction)
            .where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    assert n_txn == 1 and await n_entries(oc) == 1
    # 5 người trả đúng số khối b cùng lúc (id khác nhau) → đúng 1 thu, 4 cần hoàn
    results = await asyncio.gather(*[pay(anon, b.amount, ref(b.code), ref(oc)) for _ in range(5)])
    outs = sorted(o for o, _ in results)
    assert outs == ["applied"] + ["refund_needed"] * 4, outs
    assert await n_entries(oc) == 2
    # Tiền mặt ‖ QR trên cùng một khối: đúng một bên thu
    c = rows[2]
    cash, (outcome, _) = await asyncio.gather(
        admin.post(
            f"{BK}/items/{c.code}/collect", json={"method": "cash", "version": 1}, headers=idem()
        ),
        pay(anon, c.amount, ref(c.code), ref(oc)),
    )
    row = [x for x in await blocks(oc) if x.code == c.code][0]
    assert row.payment_status == "paid"
    if outcome == "applied":
        assert row.payment_method == "transfer" and cash.status_code != 200
    else:
        assert (
            row.payment_method == "cash" and cash.status_code == 200 and outcome == "refund_needed"
        )


async def test_late_money_after_the_popup_window_is_still_accepted_when_exact(admin, anon):
    order, rows = await sorted_blocks(admin, 102)
    b = rows[0]
    for minutes in (10, 180):
        when = (datetime.now(settings.tz) - timedelta(minutes=minutes)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        outcome, _ = await pay(
            anon, b.amount - 1, ref(b.code), ref(order["order_code"]), transactionDate=when
        )
        assert outcome == "refund_needed"
    when = (datetime.now(settings.tz) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    outcome, _ = await pay(
        anon, b.amount, ref(b.code), ref(order["order_code"]), transactionDate=when
    )
    assert outcome == "applied"
    assert (await item_qr(admin, b.code)).json()["status"] == "paid"


# ---------------------------------------------------------------- AC6: quyền


async def test_ac6_permissions_staff_with_collect_and_without(admin, staff, customer, anon):
    order, rows = await sorted_blocks(admin, 104)
    oc, code = order["order_code"], rows[0].code
    for who, expect in ((staff, 200), (customer, 403), (anon, 401)):
        assert (await item_qr(who, code)).status_code == expect, who
        assert (await qr(who, oc)).status_code == expect, who
    perm = Perm.BOOKING_COLLECT.value
    async with SessionLocal() as s:
        had = await s.scalar(
            select(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == perm
            )
        )
        assert had is not None, "mặc định Nhân viên có booking.collect"
        await s.delete(had)
        await s.commit()
    try:
        assert (await item_qr(staff, code)).status_code == 403
        assert (await qr(staff, oc)).status_code == 403
        # Không phân biệt mã có / không có với người không có quyền
        assert (await item_qr(staff, "BK-20000101-999-01")).status_code == 403
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm=perm))
            await s.commit()
    assert (await item_qr(staff, code)).status_code == 200


# ---------------------------------------------------------------- AC8: status unpaid / paid / closed


async def test_ac8_status_unpaid_paid_closed_for_item_and_order_qr(admin, anon):
    order, rows = await sorted_blocks(admin, 106)
    oc = order["order_code"]
    a, b, c, d = rows
    assert (await item_qr(admin, a.code)).json()["status"] == "unpaid"
    assert (await qr(admin, oc)).json()["status"] == "unpaid"
    # Khối a thu bằng QR → item QR của a: paid, amount 0? (không còn khối chưa thu của chính nó)
    assert (await pay(anon, a.amount, ref(a.code), ref(oc)))[0] == "applied"
    info = (await item_qr(admin, a.code)).json()
    assert info["status"] == "paid", info
    # Khối b bị máy khác đánh dấu Không thu được → item QR của b: closed, không phải "Đã nhận tiền"
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code == b.code)
            .values(payment_status="uncollectible", uncollectible_reason="Máy B")
        )
        await s.commit()
    assert (await item_qr(admin, b.code)).json()["status"] == "closed"
    assert (await qr(admin, oc)).json()["status"] == "unpaid", "đơn còn khối c, d chưa thu"
    # Hủy c, đánh dấu nốt d → đơn hết khối chưa thu, có Không thu được → closed
    preview = (await admin.get(f"{FD}/orders/{oc}/cancel-preview")).json()
    assert c.code in [i["code"] for i in preview["cancellable"]]
    r = await admin.post(
        f"{FD}/orders/{oc}/cancel",
        json={"reason": "QA", "codes": [c.code], "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (await item_qr(admin, c.code)).json()["status"] == "closed", "khối đã hủy → closed"
    assert (await qr(admin, oc)).json()["status"] == "unpaid"
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code == d.code)
            .values(payment_status="uncollectible", uncollectible_reason="Máy B")
        )
        await s.commit()
    done = (await qr(admin, oc)).json()
    assert (done["status"], done["amount"], done["blocks"]) == ("closed", 0, 0), done
    assert (await item_qr(admin, d.code)).json()["status"] == "closed"


async def test_ac8_paid_is_not_blocked_by_cancelled_blocks_and_all_cancelled_is_closed(admin, anon):
    order, rows = await sorted_blocks(admin, 108)
    oc = order["order_code"]
    a, b, c, d = rows
    # Hủy 1 buổi (chưa thu) rồi trả QR các buổi còn lại → paid (khối hủy không chặn)
    r = await admin.post(
        f"{FD}/orders/{oc}/cancel",
        json={"reason": "QA", "codes": [d.code], "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    rest = (await qr(admin, oc)).json()
    assert rest["blocks"] == 3 and rest["status"] == "unpaid"
    assert (await pay(anon, rest["amount"], ref(oc), ref(oc)))[0] == "applied"
    done = (await qr(admin, oc)).json()
    assert (done["status"], done["amount"]) == ("paid", 0), done
    # Đơn khác: hủy hết → closed, không phải paid, không 409
    order2, rows2 = await sorted_blocks(admin, 110)
    preview = (await admin.get(f"{FD}/orders/{order2['order_code']}/cancel-preview")).json()
    r = await admin.post(
        f"{FD}/orders/{order2['order_code']}/cancel",
        json={
            "reason": "QA",
            "codes": [i["code"] for i in preview["cancellable"]],
            "refund_confirmed": True,
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    gone = await qr(admin, order2["order_code"])
    assert (
        gone.status_code == 200 and gone.json()["status"] == "closed" and gone.json()["amount"] == 0
    )
    assert (await item_qr(admin, rows2[0].code)).json()["status"] == "closed"

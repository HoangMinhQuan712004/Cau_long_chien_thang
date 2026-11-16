# ruff: noqa: E501
"""QA T-068 (API, AC2, AC4–AC7): thu tiền vé quầy bằng QR – ``GET /front-desk/items/{mã vé}/collect-qr`` và webhook SePay.

Góc nhìn độc lập với ``test_ticket_collect_qr.py`` của BACKEND: mọi cách ngân hàng ghi nội dung (``code`` của SePay = mã sự kiện đúng như
SePay thật, ``code`` rỗng, chữ thường, dính tiền tố ngân hàng, cả mã sự kiện lẫn mã vé), lệch ±1 / gấp đôi / số của cả sự kiện dán vào mã
vé, vé đã thu tiền mặt / Không thu được, mã chỉ có mã sự kiện, mã vé không tồn tại, hai mã vé trong một nội dung, gửi lại và nhiều người trả cùng
lúc, tiền mặt ‖ QR trên cùng vé, sổ tiền + Lịch sử giao dịch, ``status`` unpaid / paid / closed, quyền ``booking.collect``, vé online.
Đồng hồ engine đóng băng ở 06:00 hôm nay khi đăng ký vé (sự kiện 9h–11h luôn ở tương lai) và ở 10:00 khi đánh dấu Không thu được (T-067).
"""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine import common
from app.modules.booking_engine.models import PaymentEntry, PaymentEntryItem, Ticket
from app.modules.payments.models import BankTransaction
from tests.conftest import idem
from tests.helpers_booking import BK, FD, new_court, random_phone, temp, today
from tests.helpers_web import sepay_payload, simulate, webhook

KEYS = {"order_code", "pay_ref", "amount", "status", "blocks", "bank", "qr_paid"}  # T-072
PRICE = 50_000


@pytest.fixture
def clock(monkeypatch):
    """``clock(giờ)``: đặt giờ engine hôm nay (mặc định 06:00 để sự kiện 9h–11h còn ở tương lai)."""
    day = datetime.now(settings.tz).date()
    state = {"now": datetime(day.year, day.month, day.day, 6, tzinfo=settings.tz)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_hour(hour: int) -> None:
        state["now"] = datetime(day.year, day.month, day.day, hour, tzinfo=settings.tz)

    return set_hour


def ref(code: str) -> str:
    return code.replace("-", "")


async def event_today(admin, price: int = PRICE, capacity: int = 20) -> dict:
    court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": today().isoformat(),
            "start_hour": 9,
            "end_hour": 11,
            "name": "QA sự kiện vé QR",
            "capacity": capacity,
            "ticket_price": price,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def counter_tickets(admin, ev: dict, n: int) -> list[str]:
    codes = []
    for i in range(n):
        r = await admin.post(
            f"{FD}/sessions/{ev['code']}/tickets",
            json={"customer": temp(f"QA Vé {i}", random_phone())},
            headers=idem(),
        )
        assert r.status_code == 201, r.text
        codes.append(r.json()["code"])
    return codes


async def make(admin, n: int = 4, price: int = PRICE) -> tuple[dict, list[str]]:
    ev = await event_today(admin, price)
    return ev, await counter_tickets(admin, ev, n)


async def item_qr(client, code: str):
    return await client.get(f"{FD}/items/{code}/collect-qr")


async def pay(anon, amount: int, content: str, code: str | None = None, **kw) -> tuple[str, dict]:
    payload = sepay_payload(code, amount, content=content, **kw)
    assert (await webhook(anon, payload)).status_code == 200
    async with SessionLocal() as s:
        txn = await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    return txn.outcome, payload


async def states(ev: dict) -> dict[str, str]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(Ticket.code, Ticket.payment_status).where(Ticket.code.like(f"{ev['code']}-V%"))
        )
        return dict(rows.all())


async def entries_for(ev: dict) -> list[PaymentEntry]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(PaymentEntry)
                .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
                .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
                .where(Ticket.code.like(f"{ev['code']}-V%"))
            )
        )


async def cash(client, code: str):
    return await client.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )


async def mark_uncollectible(code: str) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(Ticket)
            .where(Ticket.code == code)
            .values(payment_status="uncollectible", uncollectible_reason="QA")
        )
        await s.commit()


# ---------------------------------------------------------------- hợp đồng


async def test_item_qr_contract_for_a_counter_ticket(admin, anon, clock):
    ev, codes = await make(admin)
    r = await item_qr(admin, codes[1])
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
        codes[1],
        ref(codes[1]),
        PRICE,
        "unpaid",
        1,
    )
    assert info["pay_ref"].startswith(ref(ev["code"])), "mã vé bắt đầu bằng mã sự kiện"
    assert f"amount={PRICE}" in info["bank"]["qr_url"] and ref(codes[1]) in info["bank"]["qr_url"]
    rs = await asyncio.gather(*[item_qr(admin, codes[1]) for _ in range(30)])
    assert {x.status_code for x in rs} == {200}, "hỏi lại 3 giây / lần không bị giới hạn tần suất"
    assert (await item_qr(admin, f"{ev['code']}-V99")).status_code == 404
    for bad in ("khong-phai-ma", "BK-1", "%", "x" * 60):
        assert (await item_qr(admin, bad)).status_code in (404, 422), bad


async def test_online_ticket_has_no_qr(admin, anon):
    """Vé online đã trả trước: 422 E-PAY-1 (không dùng đồng hồ đóng băng: lượt giữ chỗ phải còn hạn lúc tiền về)."""
    from tests.qa_tickets import buy, mk_event

    event = await mk_event(admin)
    co = await buy(anon, event["code"], seats=1)
    assert co.status_code == 201, co.text
    body = co.json()
    assert await simulate(admin, body["pay_ref"], body["amount"]) == "applied"
    [online_ticket] = await states_all(event["code"])
    r = await item_qr(admin, online_ticket)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1", r.text


async def states_all(event_code: str) -> list[str]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(select(Ticket.code).where(Ticket.code.like(f"{event_code}-V%")))
        )


# ---------------------------------------------------------------- AC2, AC5: cách ghi nội dung


async def test_ac2_ac5_ticket_code_pays_only_that_ticket_in_every_bank_notation(admin, anon, clock):
    ev, codes = await make(admin, 6)
    notations = [
        lambda c: (
            f"{ref(c)} thanh toan ve",
            ref(ev["code"]),
        ),  # SePay cắt "BK + 11 số" → mã sự kiện
        lambda c: (f"{ref(c)} thanh toan ve", None),
        lambda c: (f"mbvcb.123.{ref(c).lower()}.ct", ref(ev["code"]).lower()),
        lambda c: (f"FT25{ref(c)} chuyen khoan", ref(ev["code"])),
        lambda c: (
            f"{ref(ev['code'])} {ref(c)} qr",
            ref(ev["code"]),
        ),  # cả mã sự kiện lẫn mã vé → mã vé thắng
        lambda c: (f"  {ref(c)}  ", ref(ev["code"])),
    ]
    for code, note in zip(codes, notations, strict=True):
        before = await states(ev)
        content, sepay_code = note(code)
        outcome, _ = await pay(anon, PRICE, content, sepay_code)
        assert outcome == "applied", (content, sepay_code, outcome)
        after = await states(ev)
        assert {c for c in after if after[c] != before[c]} == {code}, "chỉ đúng một vé đổi"
        assert after[code] == "paid"
    entries = await entries_for(ev)
    assert len(entries) == len(codes), "mỗi lần tiền về một dòng sổ"
    assert {(e.kind, e.method, e.source, e.amount, e.actor_label) for e in entries} == {
        ("in", "transfer", "counter_qr", PRICE, "Hệ thống")
    }
    # Lịch sử giao dịch hiện từng vé
    day = today().isoformat()
    tx = (
        await admin.get(f"{BK}/transactions", params={"from": day, "to": day, "q": codes[0]})
    ).json()
    assert any(
        i["code"] == codes[0] and i["kind"] == "ticket" for e in tx["items"] for i in e["items"]
    )
    # Vé đã thu: chuyển tiếp theo cùng mã vé → cần hoàn
    outcome, _ = await pay(anon, PRICE, ref(codes[0]), ref(ev["code"]))
    assert outcome == "refund_needed"
    assert len(await entries_for(ev)) == len(codes)


# ---------------------------------------------------------------- AC4: lệch số, vé đã xử lý, không khớp


async def test_ac4_wrong_amount_or_handled_ticket_needs_refund_and_other_tickets_stay(
    admin, anon, clock
):
    ev, codes = await make(admin, 4)
    target, paid_cash, bad, spare = codes
    total = PRICE * len(codes)
    for amount in (PRICE - 1, PRICE + 1, PRICE * 2, total, 1):
        outcome, _ = await pay(anon, amount, ref(target), ref(ev["code"]))
        assert outcome == "refund_needed", amount
    assert set((await states(ev)).values()) == {"unpaid"} and await entries_for(ev) == []
    # Thu tiền mặt / Không thu được rồi mới chuyển khoản → cần hoàn, trạng thái giữ nguyên
    assert (await cash(admin, paid_cash)).status_code == 200
    await mark_uncollectible(bad)
    before = len(await entries_for(ev))
    for code in (paid_cash, bad):
        outcome, _ = await pay(anon, PRICE, ref(code), ref(ev["code"]))
        assert outcome == "refund_needed", code
    st = await states(ev)
    assert (st[target], st[paid_cash], st[bad], st[spare]) == (
        "unpaid",
        "paid",
        "uncollectible",
        "unpaid",
    )
    assert len(await entries_for(ev)) == before, "tiền cần hoàn không vào sổ"
    # Chỉ có mã sự kiện / mã vé không tồn tại / hai mã vé khác nhau → không khớp, không vé nào bị áp
    for content, code in (
        (ref(ev["code"]), ref(ev["code"])),
        (f"{ref(ev['code'])}V99", ref(ev["code"])),
        (f"{ref(target)} {ref(spare)}", ref(ev["code"])),
    ):
        outcome, _ = await pay(anon, PRICE, content, code)
        assert outcome in ("unmatched", "refund_needed"), (content, outcome)
    st = await states(ev)
    assert (st[target], st[spare]) == ("unpaid", "unpaid"), "không đoán vé"
    # Và đúng số vẫn thu được sau mọi lần lệch
    assert (await pay(anon, PRICE, ref(target), ref(ev["code"])))[0] == "applied"


# ---------------------------------------------------------------- trùng, đồng thời, trễ


async def test_replay_races_and_late_money_collect_a_ticket_exactly_once(admin, anon, clock):
    ev, codes = await make(admin, 3)
    a, b, c = codes
    payload = sepay_payload(ref(ev["code"]), PRICE, content=ref(a))
    rs = await asyncio.gather(*[webhook(anon, payload) for _ in range(5)])
    assert {r.status_code for r in rs} == {200}
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(BankTransaction)
            .where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    assert n == 1 and len(await entries_for(ev)) == 1
    # 5 người trả đúng số vé b cùng lúc (id khác nhau) → 1 thu + 4 hoàn
    results = await asyncio.gather(*[pay(anon, PRICE, ref(b), ref(ev["code"])) for _ in range(5)])
    assert sorted(o for o, _ in results) == ["applied"] + ["refund_needed"] * 4
    assert len(await entries_for(ev)) == 2
    # Tiền mặt ‖ QR trên cùng vé c: đúng một bên thu
    cash_r, (outcome, _) = await asyncio.gather(
        cash(admin, c), pay(anon, PRICE, ref(c), ref(ev["code"]))
    )
    assert (await states(ev))[c] == "paid"
    assert (outcome == "applied") != (cash_r.status_code == 200), (outcome, cash_r.status_code)
    # Tiền về trễ vẫn nhận nếu đúng số: tạo vé mới
    [late] = await counter_tickets(admin, ev, 1)
    assert (
        await pay(
            anon, PRICE - 1, ref(late), ref(ev["code"]), transactionDate="2020-01-01 10:00:00"
        )
    )[0] == "refund_needed"
    assert (
        await pay(anon, PRICE, ref(late), ref(ev["code"]), transactionDate="2020-01-01 10:00:00")
    )[0] == "applied"


# ---------------------------------------------------------------- AC6: status, Không thu được


async def test_ac6_status_unpaid_paid_closed_and_uncollectible_needs_started_event(
    admin, anon, clock
):
    ev, codes = await make(admin, 3)
    a, b, c = codes
    assert (await item_qr(admin, a)).json()["status"] == "unpaid"
    assert (await pay(anon, PRICE, ref(a), ref(ev["code"])))[0] == "applied"
    assert (await item_qr(admin, a)).json()["status"] == "paid"
    # Trước giờ sự kiện: Không thu được bị từ chối (E-PAY-1); sau giờ bắt đầu: được
    r = await admin.post(
        f"{BK}/items/{b}/uncollectible", json={"reason": "QA", "version": 1}, headers=idem()
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1", r.text
    assert (await states(ev))[b] == "unpaid"
    clock(10)
    r = await admin.post(
        f"{BK}/items/{b}/uncollectible", json={"reason": "QA", "version": 1}, headers=idem()
    )
    assert r.status_code == 200, r.text
    # Máy khác đánh dấu rồi → popup QR của máy này thấy `closed`, không phải "Đã nhận tiền"
    info = (await item_qr(admin, b)).json()
    assert (info["status"], info["amount"]) == ("closed", 0), info
    assert (await pay(anon, PRICE, ref(b), ref(ev["code"])))[0] == "refund_needed"
    assert (await states(ev))[b] == "uncollectible"
    assert (await item_qr(admin, c)).json()["status"] == "unpaid", "vé khác không đổi"


# ---------------------------------------------------------------- AC7: quyền


async def test_ac7_permissions_staff_with_collect_and_without(admin, staff, customer, anon, clock):
    ev, codes = await make(admin, 2)
    code = codes[0]
    for who, expect in ((staff, 200), (customer, 403), (anon, 401)):
        assert (await item_qr(who, code)).status_code == expect, who
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
        assert (await item_qr(staff, f"{ev['code']}-V99")).status_code == 403, (
            "không phân biệt mã có / không có"
        )
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm=perm))
            await s.commit()
    assert (await item_qr(staff, code)).status_code == 200


# ---------------------------------------------------------------- hồi quy: mã con booking và mã vé không lẫn


async def test_booking_child_code_and_ticket_code_in_the_same_day_do_not_cross(admin, anon, clock):
    ev, codes = await make(admin, 2)
    court = await new_court(admin)
    r = await admin.post(
        f"{FD}/bookings",
        json={
            "date": today().isoformat(),
            "blocks": [{"resource_code": court["code"], "start_hour": 12, "end_hour": 13}],
            "customer": temp("QA Cùng Ngày", random_phone()),
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    order = r.json()
    child = order["bookings"][0]
    # Mã con booking thu đúng khối của nó, vé không bị chạm
    assert (
        await pay(anon, child["payment"]["amount"], ref(child["code"]), ref(order["order_code"]))
    )[0] == "applied"
    assert set((await states(ev)).values()) == {"unpaid"}
    # Mã vé thu đúng vé, booking không bị chạm
    assert (await pay(anon, PRICE, ref(codes[0]), ref(ev["code"])))[0] == "applied"
    assert (await states(ev))[codes[1]] == "unpaid"
    # QR của booking vẫn hoạt động; QR vé không trả thông tin booking
    assert (await item_qr(admin, child["code"])).json()["pay_ref"] == ref(child["code"])
    assert (await item_qr(admin, codes[1])).json()["pay_ref"] == ref(codes[1])

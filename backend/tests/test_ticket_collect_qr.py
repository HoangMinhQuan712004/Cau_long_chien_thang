"""T-068: QR cho vé quầy – nội dung = mã vé bỏ gạch (``BK20261110002V05``); tiền về đúng số chỉ
thu vé đó (một dòng sổ ``counter_qr``, mục là vé); lệch số / vé đã xử lý -> cần hoàn; mã vé không
bao giờ bị đọc thành mã sự kiện / mã con / mã đơn, kể cả khi trường ``code`` của SePay chỉ có mã sự
kiện; chuyển theo mã sự kiện -> không khớp như cũ; vé online -> 422; quyền ``booking.collect``.
"""

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import PaymentEntry, PaymentEntryItem, Ticket
from app.modules.payments.service import extract_code
from tests.conftest import idem
from tests.helpers_booking import BK, FD, safe_hour, today
from tests.helpers_web import sepay_payload, simulate, webhook
from tests.test_ticket_online import buy, new_event

PERM = "booking.collect"


async def today_event(admin, price: int) -> dict:
    """Vé quầy chỉ đăng ký cho sự kiện hôm nay: sự kiện ở khung giờ đang diễn ra."""
    hour = await safe_hour()
    return await new_event(admin, day=today(), hours=(hour, hour + 1), price=price)


async def counter_tickets(admin, ev: dict, n: int) -> list[dict]:
    out = []
    for _ in range(n):
        r = await admin.post(
            f"{FD}/sessions/{ev['code']}/tickets",
            json={"customer": {"member_code": "HV0012"}},
            headers=idem(),
        )
        assert r.status_code == 201, r.text
        out.append(r.json())
    return out


async def item_qr(client, code: str):
    return await client.get(f"{FD}/items/{code}/collect-qr")


async def statuses(ev: dict) -> dict[str, str]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(Ticket.code, Ticket.payment_status).where(Ticket.code.like(f"{ev['code']}-V%"))
        )
        return dict(rows.all())


async def entries_with(code: str) -> list[PaymentEntry]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(PaymentEntry)
                .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
                .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
                .where(Ticket.code == code)
            )
        )


def test_ticket_code_wins_over_event_child_and_order_codes():
    """AC5: SePay cắt mã vé thành mã sự kiện ở trường ``code`` -> đọc mã vé từ nội dung trước."""
    ticket, event = "BK20261110002V05", "BK20261110002"
    assert extract_code({"code": event, "content": f"{ticket} thanh toan"}) == ticket
    assert extract_code({"code": None, "content": f"MBVCB.9.{ticket}.CT"}) == ticket
    assert extract_code({"code": event, "content": f"{ticket} BK2026111000301"}) == ticket
    assert extract_code({"code": event, "content": f"{event} chuyen"}) == event  # mã sự kiện
    assert extract_code({"code": event, "content": f"{ticket} BK20261110002V06"}) is None


async def test_ticket_qr_pays_only_that_ticket(admin, anon):
    """AC2: QR vé 2 -> chỉ vé 2 Đã thanh toán (``code`` của SePay = mã sự kiện), sổ 1 dòng."""
    ev = await today_event(admin, 45_000)
    t1, t2 = await counter_tickets(admin, ev, 2)
    r = await item_qr(admin, t2["code"])
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    info = r.json()
    pay_ref = t2["code"].replace("-", "")
    assert pay_ref.startswith(ev["code"].replace("-", "")) and pay_ref.endswith(t2["code"][-3:])
    assert (
        info["order_code"],
        info["pay_ref"],
        info["amount"],
        info["status"],
        info["blocks"],
    ) == (
        t2["code"],
        pay_ref,
        45_000,
        "unpaid",
        1,
    )
    assert f"des={pay_ref}" in info["bank"]["qr_url"]

    payload = sepay_payload(ev["code"].replace("-", ""), 45_000)
    payload["content"] = f"{pay_ref} chuyen tien ve"
    assert (await webhook(anon, payload)).status_code == 200
    assert await statuses(ev) == {t1["code"]: "unpaid", t2["code"]: "paid"}
    async with SessionLocal() as s:
        paid = await s.scalar(select(Ticket).where(Ticket.code == t2["code"]))
    assert (paid.payment_method, paid.collected_by_label) == ("transfer", "Hệ thống")
    [entry] = await entries_with(t2["code"])
    assert (entry.kind, entry.method, entry.source, entry.amount) == (
        "in",
        "transfer",
        "counter_qr",
        45_000,
    )
    tx = (await admin.get(f"{BK}/transactions", params={"q": t2["code"]})).json()["items"]
    assert [(e["source"], [i["kind"] for i in e["items"]]) for e in tx] == [
        ("counter_qr", ["ticket"])
    ]
    after = (await item_qr(admin, t2["code"])).json()
    assert (after["status"], after["amount"], after["blocks"]) == ("paid", 0, 0)


async def test_wrong_amount_handled_ticket_or_event_code_only(admin):
    """AC4: lệch số / đã thu -> cần hoàn, vé khác không đổi; chỉ mã sự kiện -> không khớp."""
    ev = await today_event(admin, 30_000)
    t1, t2 = await counter_tickets(admin, ev, 2)
    pay_ref = t1["code"].replace("-", "")
    assert await simulate(admin, pay_ref, 31_000) == "refund_needed"
    r = await admin.post(
        f"{BK}/items/{t1['code']}/collect",
        json={"method": "cash", "version": t1["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert await simulate(admin, pay_ref, 30_000) == "refund_needed"
    assert await statuses(ev) == {t1["code"]: "paid", t2["code"]: "unpaid"}
    assert [e.method for e in await entries_with(t1["code"])] == ["cash"]
    # Chuyển theo mã sự kiện: không tự áp cho vé nào (như trước T-068)
    assert await simulate(admin, ev["code"].replace("-", ""), 30_000) == "unmatched"
    assert await statuses(ev) == {t1["code"]: "paid", t2["code"]: "unpaid"}
    assert await simulate(admin, f"{ev['code'].replace('-', '')}V99", 30_000) == "unmatched"


async def test_closed_online_and_permissions(admin, staff, customer, anon):
    """AC6, AC7: Không thu được / hủy -> ``closed``; vé online -> 422; quyền ``booking.collect``."""
    ev = await today_event(admin, 20_000)
    t1, t2 = await counter_tickets(admin, ev, 2)
    async with SessionLocal() as s:  # máy khác đánh dấu Không thu được (vé tương lai: đặt thẳng)
        await s.execute(
            update(Ticket)
            .where(Ticket.code == t1["code"])
            .values(payment_status="uncollectible", uncollectible_reason="Máy B")
        )
        await s.commit()
    closed = (await item_qr(admin, t1["code"])).json()
    assert (closed["status"], closed["amount"]) == ("closed", 0)

    assert (await item_qr(staff, t2["code"])).status_code == 200
    assert (await item_qr(customer, t2["code"])).status_code == 403
    async with SessionLocal() as s:
        row = await s.get(RolePermission, ("staff", PERM))
        if row is not None:
            await s.delete(row)
            await s.commit()
    try:
        assert (await item_qr(staff, t2["code"])).status_code == 403
    finally:
        if row is not None:
            async with SessionLocal() as s:
                s.add(RolePermission(role="staff", perm=PERM))
                await s.commit()

    later = await new_event(admin, price=20_000)  # ngày mai: còn bán online
    r = await buy(anon, later["code"], 1)
    assert r.status_code == 201, r.text
    co = r.json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    [online] = list(await statuses(later))
    r = await item_qr(admin, online)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1"
    assert "Vé đặt online" in r.json()["detail"]["message"]
    r = await item_qr(admin, f"{ev['code']}-V99")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "E-BOOK-3"

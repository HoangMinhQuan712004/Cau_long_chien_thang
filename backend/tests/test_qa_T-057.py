# ruff: noqa: E501
"""QA T-057 (API, AC1–AC8, AC10, AC11): sổ tiền vào – Lịch sử giao dịch chỉ hiện tiền vào, báo cáo theo ngày tiền về.

Góc nhìn độc lập với ``test_payment_ledger.py`` của BACKEND: ranh giới nửa đêm giờ VN (cả giờ giao dịch SePay),
hoàn nhiều phương thức, thẻ chỉ theo ngày + sân, lọc / tìm / phân trang, báo cáo theo ngày tiền về (ngày âm), vé,
bảo mật, Idempotency-Key, đồng thời. Đồng hồ engine đóng băng; ngày cách ly để không lẫn tiền của test khác.
Thu chuyển khoản tại quầy chỉ có qua QR (T-058): test dùng webhook với ``transactionDate`` tự đặt.
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import common, report_revenue
from app.modules.booking_engine.models import PaymentEntry
from app.modules.booking_engine.tenant import current_tenant_id
from app.modules.payments.models import BankTransaction
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, new_court, random_phone, temp
from tests.helpers_web import sepay_payload, simulate, tomorrow, webhook
from tests.qa_tickets import buy, tickets_of
from tests.test_recurring_list import create

FD = f"{API}/front-desk"
FAR = (datetime.now(settings.tz) + timedelta(days=400)).date()
ENTRY_KEYS = {
    "kind",
    "method",
    "source",
    "amount",
    "occurred_at",
    "order_code",
    "customer_name",
    "customer_phone",
    "member_code",
    "actor_label",
    "items",
}
ITEM_KEYS = {"code", "kind", "resource_name", "play_date", "start_at", "end_at", "amount"}


def at(day, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=settings.tz)


@pytest.fixture
def clock(monkeypatch):
    """``clock(ngày, giờ, phút, giây)`` đặt giờ engine."""
    state = {"now": at(FAR, 0, 30)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int, minute: int = 0, second: int = 0) -> None:
        state["now"] = at(day, hour, minute, second)

    return set_time


async def collect(client, code, version=1):
    return await client.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": version}, headers=idem()
    )


async def qr_pay(anon, order_code: str, amount: int, when: datetime) -> str:
    """Tiền chuyển khoản QR về lúc ``when`` (giờ giao dịch do ngân hàng ghi). Trả outcome của lượt."""
    payload = sepay_payload(
        order_code.replace("-", ""),
        amount,
        transactionDate=when.strftime("%Y-%m-%d %H:%M:%S"),
    )
    assert (await webhook(anon, payload)).status_code == 200
    async with SessionLocal() as s:
        txn = await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == str(payload["id"]))
        )
    return txn.outcome


async def ledger(client, frm, to=None, **params) -> dict:
    r = await client.get(
        f"{BK}/transactions",
        params={"from": frm.isoformat(), "to": (to or frm).isoformat(), **params},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def counter_booking(staff, court, day, hour, name="Khách Sổ"):
    r = await book(staff, court["code"], hour, customer=temp(name, random_phone()), day=day)
    assert r.status_code == 201, r.text
    return r.json()


async def revenue_of(day) -> tuple[int, int]:
    """(doanh thu theo ngày tiền về, lượt đặt theo ngày chơi) của một ngày."""
    async with SessionLocal() as s:
        t = await report_revenue.totals(s, current_tenant_id(), day, day)
    return t.revenue, t.bookings


async def court_revenue(frm, to, code: str) -> int:
    async with SessionLocal() as s:
        rows = await report_revenue.by_court(s, current_tenant_id(), frm, to)
    return next(c.revenue for c in rows if c.code == code)


def codes(entry: dict) -> list[str]:
    return [i["code"] for i in entry["items"]]


def vn_clock(entry: dict) -> str:
    return datetime.fromisoformat(entry["occurred_at"]).astimezone(settings.tz).strftime("%H:%M:%S")


# ---------------------------------------------------------------- nửa đêm giờ VN


async def test_midnight_vn_boundary_decides_the_day_of_the_money(admin, staff, anon, clock):
    d = FAR + timedelta(days=10)
    clock(d, 8)
    court = await new_court(admin)
    a = await counter_booking(staff, court, d, 10)
    b = await counter_booking(staff, court, d, 11)
    clock(d, 23, 59, 59)
    assert (await collect(admin, a["code"])).status_code == 200
    # Chuyển khoản QR về đúng 00:00:00 ngày kế (= 17:00:00 UTC của ngày d)
    assert (
        await qr_pay(anon, b["order_code"], b["payment"]["amount"], at(d + timedelta(days=1), 0))
        == "applied"
    )

    amount_a, amount_b = a["payment"]["amount"], b["payment"]["amount"]
    day1, day2 = await ledger(admin, d), await ledger(admin, d + timedelta(days=1))
    assert [codes(e) for e in day1["items"]] == [[a["code"]]]
    assert [codes(e) for e in day2["items"]] == [[b["code"]]]
    assert vn_clock(day1["items"][0]) == "23:59:59" and vn_clock(day2["items"][0]) == "00:00:00"
    assert day1["cards"] == {"net": amount_a, "cash": amount_a, "transfer": 0, "refund": 0}
    assert day2["cards"] == {"net": amount_b, "cash": 0, "transfer": amount_b, "refund": 0}
    both = await ledger(admin, d, d + timedelta(days=1))
    assert both["total"] == 2 and both["cards"]["net"] == amount_a + amount_b
    assert (await revenue_of(d))[0] == amount_a
    assert (await revenue_of(d + timedelta(days=1)))[0] == amount_b
    assert (await ledger(admin, d + timedelta(days=2)))["total"] == 0


# ---------------------------------------------------------------- thẻ, lọc, phân trang


async def test_cards_follow_only_date_and_court_while_rows_follow_every_filter(
    admin, staff, anon, clock
):
    d = FAR + timedelta(days=20)
    clock(d, 7)
    ca, cb = await new_court(admin), await new_court(admin)
    x = await counter_booking(staff, ca, d, 15, "QA Thẻ X")
    y = await counter_booking(staff, cb, d, 15, "QA Thẻ Y")
    z = await counter_booking(staff, ca, d, 16, "QA Thẻ Z")
    clock(d, 9)
    assert (await collect(admin, x["code"])).status_code == 200
    assert await qr_pay(anon, y["order_code"], y["payment"]["amount"], at(d, 10)) == "applied"
    clock(d, 11)
    assert (await collect(admin, z["code"])).status_code == 200
    clock(d, 12)
    r = await admin.post(
        f"{FD}/items/{z['code']}/cancel",
        json={"reason": "QA hoàn", "version": 2, "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    ax, ay, az = (b["payment"]["amount"] for b in (x, y, z))

    everything = await ledger(admin, d)
    assert everything["total"] == 4 and everything["size"] == 8
    assert [(e["kind"], codes(e)) for e in everything["items"]] == [
        ("refund", [z["code"]]),
        ("in", [z["code"]]),
        ("in", [y["code"]]),
        ("in", [x["code"]]),
    ], "mới nhất trước"
    cards = everything["cards"]
    assert cards == {"net": ax + ay, "cash": ax + az, "transfer": ay, "refund": az}
    # Thẻ không đổi theo phương thức / loại / tìm kiếm / trang
    for params in (
        {"method": "cash"},
        {"method": "transfer"},
        {"kind": "refund"},
        {"q": x["code"]},
        {"page": 2},
    ):
        assert (await ledger(admin, d, **params))["cards"] == cards, params
    assert (await ledger(admin, d, method="cash"))[
        "total"
    ] == 3  # x, z thu, z hoàn (phương thức gốc)
    assert (await ledger(admin, d, method="transfer"))["total"] == 1
    assert (await ledger(admin, d, kind="refund"))["total"] == 1
    assert (await ledger(admin, d, kind="in", method="cash"))["total"] == 2
    # Thẻ theo sân
    on_a = await ledger(admin, d, resource=ca["code"])
    assert (
        on_a["cards"] == {"net": ax, "cash": ax + az, "transfer": 0, "refund": az}
        and on_a["total"] == 3
    )
    on_b = await ledger(admin, d, resource=cb["code"])
    assert (
        on_b["cards"] == {"net": ay, "cash": 0, "transfer": ay, "refund": 0} and on_b["total"] == 1
    )
    assert (await ledger(admin, d, resource="KHONG-CO"))["total"] == 0
    # Phân trang và tham số sai
    page2 = await ledger(admin, d, page=2)
    assert page2["items"] == [] and page2["total"] == 4 and page2["page"] == 2
    for bad in ({"page": 0}, {"method": "card"}, {"kind": "out"}):
        assert (await admin.get(f"{BK}/transactions", params=bad)).status_code == 422, bad


async def test_order_cancel_refunds_each_original_method_on_the_cancel_day(admin, anon, clock):
    d = FAR + timedelta(days=30)
    clock(d, 7)
    court = await new_court(admin)
    start = d + timedelta(days=7)
    order = await create(
        admin,
        court,
        "QA Đơn Hoàn",
        random_phone(),
        start,
        (start.isoweekday(), (start + timedelta(days=1)).isoweekday()),
        pct=10,
    )
    code = order["order_code"]
    first = order["bookings"][0]
    clock(d, 8)
    assert (await collect(admin, first["code"], first["version"])).status_code == 200
    cash_amount = first["payment"]["amount"]
    # Các buổi còn lại thu bằng QR chuyển khoản (tiền mặt + chuyển khoản trong cùng một đơn)
    rest = order["total"] - cash_amount
    assert await qr_pay(anon, code, rest, at(d, 9)) == "applied"
    later = d + timedelta(days=2)  # trước buổi đầu tiên
    clock(later, 9)
    preview = (await admin.get(f"{FD}/orders/{code}/cancel-preview")).json()
    assert preview["refund_total"] == order["total"] and preview["unpaid_total"] == 0
    assert len(preview["cancellable"]) == len(order["bookings"])
    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={
            "reason": "QA hủy đơn",
            "codes": [i["code"] for i in preview["cancellable"]],
            "refund_confirmed": True,
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text

    refunds = (await ledger(admin, later, q=code))["items"]
    assert sorted(
        (e["kind"], e["method"], e["amount"], len(e["items"])) for e in refunds
    ) == sorted(
        [
            ("refund", "cash", cash_amount, 1),
            ("refund", "transfer", rest, len(order["bookings"]) - 1),
        ]
    ), "mỗi phương thức gốc một dòng hoàn"
    kept = await ledger(admin, d, q=code)
    assert sorted((e["method"], e["amount"]) for e in kept["items"]) == sorted(
        [("cash", cash_amount), ("transfer", rest)]
    ) and {e["kind"] for e in kept["items"]} == {"in"}
    assert kept["cards"]["refund"] == 0, "ngày thu không đổi sau khi hủy"
    got = (await ledger(admin, later))["cards"]
    assert got["refund"] == order["total"] and got["net"] == -order["total"]
    assert (await revenue_of(d))[0] == order["total"]
    assert (await revenue_of(later))[0] == -order["total"], "ngày hoàn có thể âm"


# ---------------------------------------------------------------- tìm kiếm


async def test_search_by_order_child_name_phone_and_wildcards_are_literal(admin, staff, clock):
    d = FAR + timedelta(days=40)
    clock(d, 7)
    court = await new_court(admin)
    phone = random_phone()
    r = await book(staff, court["code"], 14, customer=temp("QA Trần Đình Ánh", phone), day=d)
    assert r.status_code == 201, r.text
    bk = r.json()
    other = await counter_booking(staff, court, d, 15, "QA Người Khác")
    clock(d, 9)
    assert (await collect(admin, bk["code"])).status_code == 200
    assert (await collect(admin, other["code"])).status_code == 200

    async def total(q):
        return (await ledger(admin, d, q=q))["total"]

    assert await total(bk["code"]) == 1 and await total(bk["code"].lower()) == 1
    assert await total(bk["order_code"]) == 1
    assert await total("trần đình ánh") == 1 and await total("TRẦN ĐÌNH") == 1
    spaced = f"{phone[:4]} {phone[4:7]}.{phone[7:]}"
    assert await total(spaced) == 1 and await total(phone) == 1
    entry = (await ledger(admin, d, q=phone))["items"][0]
    assert entry["customer_phone"] == phone, "T-061: SĐT đầy đủ, tìm theo SĐT vẫn đúng"
    assert await total("KHONG-CO-MA-NAY") == 0
    # Ký tự đại diện của SQL LIKE phải được hiểu là chữ, không khớp tất cả
    for wild in ("%", "_", "%%", "___"):
        assert await total(wild) == 0, wild
    assert await total("'; DROP TABLE booking.payment_entry;--") == 0
    assert await total("x" * 100) == 0
    too_long = await admin.get(f"{BK}/transactions", params={"q": "x" * 101})
    assert too_long.status_code == 422, "q tối đa 100 ký tự"


# ---------------------------------------------------------------- báo cáo theo ngày tiền về


async def test_ac7_report_money_follows_receipt_day_but_bookings_follow_play_day(
    admin, staff, clock
):
    play = FAR + timedelta(days=70)
    receipt, cancel_day = play + timedelta(days=3), play + timedelta(days=5)
    clock(play, 7)
    court = await new_court(admin)
    play_before, receipt_before = await revenue_of(play), await revenue_of(receipt)
    b = await counter_booking(staff, court, play, 20)
    amount = b["payment"]["amount"]
    clock(receipt, 10)  # thu 3 ngày sau ngày chơi
    assert (await collect(admin, b["code"])).status_code == 200

    assert await revenue_of(play) == (play_before[0], play_before[1] + 1), (
        "ngày chơi: tiền không đổi, lượt +1"
    )
    assert await revenue_of(receipt) == (receipt_before[0] + amount, receipt_before[1]), (
        "ngày thu: tiền +n, lượt không đổi"
    )
    assert await court_revenue(play, play, court["code"]) == 0
    assert await court_revenue(receipt, receipt, court["code"]) == amount, (
        "doanh thu theo sân theo ngày tiền về"
    )

    clock(cancel_day, 9)
    r = await admin.post(
        f"{FD}/items/{b['code']}/cancel",
        json={"reason": "QA hoàn báo cáo", "version": 2, "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (await revenue_of(receipt))[0] == receipt_before[0] + amount, "ngày thu giữ nguyên"
    assert (await revenue_of(cancel_day))[0] == -amount, "ngày hủy giảm đúng n đ (âm)"
    assert await court_revenue(cancel_day, cancel_day, court["code"]) == -amount
    assert await court_revenue(play, cancel_day, court["code"]) == 0, "thu rồi hoàn = 0 trên cả kỳ"
    async with SessionLocal() as s:
        days = await report_revenue.daily(s, current_tenant_id(), play, cancel_day)
        whole = await report_revenue.totals(s, current_tenant_id(), play, cancel_day)
    assert [x.revenue for x in days] == [0, 0, 0, amount, 0, -amount]
    assert sum(x.revenue for x in days) == whole.revenue == 0
    assert whole.bookings == play_before[1], "booking đã hủy không còn là lượt đặt (T-051)"


# ---------------------------------------------------------------- vé sự kiện


async def test_tickets_are_one_entry_per_payment_and_refund_per_ticket(anon, admin):
    c1, c2 = await new_court(admin), await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [c1["code"], c2["code"]],
            "date": tomorrow().isoformat(),
            "start_hour": 9,
            "end_hour": 11,
            "name": "QA sự kiện sổ tiền",
            "capacity": 4,
            "ticket_price": 40_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    co = await buy(anon, ev["code"], seats=2, phone=random_phone())
    assert co.status_code == 201, co.text
    assert await simulate(admin, co.json()["pay_ref"], co.json()["amount"]) == "applied"
    today_vn = datetime.now(settings.tz).date()
    [entry] = (await ledger(admin, today_vn, q=ev["code"]))["items"]
    assert (entry["kind"], entry["method"], entry["source"], entry["amount"]) == (
        "in",
        "transfer",
        "online",
        80_000,
    )
    assert entry["actor_label"] == "Hệ thống" and set(entry) == ENTRY_KEYS
    assert [i["kind"] for i in entry["items"]] == ["ticket", "ticket"]
    assert all(set(i) == ITEM_KEYS and i["amount"] == 40_000 for i in entry["items"])
    names = entry["items"][0]["resource_name"]
    assert c1["name"] in names and c2["name"] in names and "," in names
    for c in (c1, c2):
        found = (await ledger(admin, today_vn, resource=c["code"], q=ev["code"]))["items"]
        assert [e["amount"] for e in found] == [80_000], (
            "lọc theo sân nào của sự kiện cũng thấy dòng"
        )
    outside = await new_court(admin)
    assert (await ledger(admin, today_vn, resource=outside["code"], q=ev["code"]))["total"] == 0

    first, second = [t["code"] for t in await tickets_of(ev["code"])]
    refunded = 0
    for code in (first, second):
        r = await admin.post(
            f"{FD}/items/{code}/cancel",
            json={"reason": "QA hoàn vé", "version": 1, "refund_confirmed": True},
            headers=idem(),
        )
        assert r.status_code == 200, r.text
        refunded += 40_000
        rows = (await ledger(admin, today_vn, q=ev["code"], kind="refund"))["items"]
        assert sum(e["amount"] for e in rows) == refunded
        assert all(e["method"] == "transfer" and e["items"][0]["kind"] == "ticket" for e in rows)
    allrows = (await ledger(admin, today_vn, q=ev["code"]))["items"]
    assert sum(e["amount"] if e["kind"] == "in" else -e["amount"] for e in allrows) == 0
    # Gửi lại tiền về sau khi hủy hết: không thêm dòng
    assert await simulate(admin, co.json()["pay_ref"], co.json()["amount"]) != "applied"
    assert (await ledger(admin, today_vn, q=ev["code"]))["total"] == len(allrows)


# ---------------------------------------------------------------- bảo mật, Idempotency-Key, đồng thời


async def test_ac11_shape_phone_permissions_and_no_internal_ids(
    admin, staff, customer, anon, clock
):
    d = FAR + timedelta(days=50)
    clock(d, 7)
    court = await new_court(admin)
    phone = random_phone()
    r = await book(staff, court["code"], 12, customer=temp("QA Che Số", phone), day=d)
    assert r.status_code == 201
    clock(d, 9)
    assert (await collect(admin, r.json()["code"])).status_code == 200
    out = await ledger(admin, d)
    assert set(out) == {"date_from", "date_to", "cards", "items", "total", "page", "size"}
    [entry] = out["items"]
    assert set(entry) == ENTRY_KEYS and all(set(i) == ITEM_KEYS for i in entry["items"])
    text = str(out)
    assert "customer_phone_masked" not in text
    assert "customer_id" not in text and "public_id" not in text and "'id'" not in text
    assert entry["customer_phone"] == phone, "T-061: SĐT đầy đủ như đã lưu"
    assert (
        await staff.get(f"{BK}/transactions", params={"from": d.isoformat(), "to": d.isoformat()})
    ).status_code == 200
    assert (await customer.get(f"{BK}/transactions")).status_code == 403
    assert (await anon.get(f"{BK}/transactions")).status_code == 401
    # Khoảng ngày giữ mã lỗi cũ
    for params, code in (
        ({"from": d.isoformat(), "to": (d - timedelta(days=1)).isoformat()}, "E-016"),
        ({"from": (d - timedelta(days=93)).isoformat(), "to": d.isoformat()}, "E-020"),
    ):
        r = await admin.get(f"{BK}/transactions", params=params)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, r.text
    ok = await admin.get(
        f"{BK}/transactions",
        params={"from": (d - timedelta(days=91)).isoformat(), "to": d.isoformat()},
    )
    assert ok.status_code == 200, "đúng 92 ngày là tối đa"


async def test_collect_replay_and_parallel_collects_write_exactly_one_entry(admin, clock):
    d = FAR + timedelta(days=60)
    clock(d, 7)
    court = await new_court(admin)
    start = d + timedelta(days=7)
    order = await create(
        admin,
        court,
        "QA Song Song",
        random_phone(),
        start,
        (start.isoweekday(), (start + timedelta(days=1)).isoweekday()),
        pct=0,
    )
    code = order["order_code"]
    clock(d, 9)
    key = idem()
    first = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=key)
    assert first.status_code == 200, first.text
    again = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=key)
    assert again.status_code == 200 and again.json()["amount"] == first.json()["amount"]
    assert (await ledger(admin, d, q=code))["total"] == 1, "replay cùng khóa không ghi thêm dòng"
    third = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert third.status_code == 409, "khóa mới: đơn không còn khối chưa thu"
    assert (await ledger(admin, d, q=code))["total"] == 1

    # 5 lệnh thu cả đơn song song trên đơn khác: đúng một thắng, một dòng sổ
    other = await create(
        admin, court, "QA Song Song 2", random_phone(), start + timedelta(days=14), (1,), pct=0
    )
    res = await asyncio.gather(
        *[
            admin.post(
                f"{BK}/orders/{other['order_code']}/collect",
                json={"method": "cash"},
                headers=idem(),
            )
            for _ in range(5)
        ]
    )
    assert sorted(r.status_code for r in res).count(200) == 1, [r.text for r in res]
    assert all(r.status_code in (200, 409) for r in res)
    assert (await ledger(admin, d, q=other["order_code"]))["total"] == 1
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(PaymentEntry)
            .where(PaymentEntry.order_code == other["order_code"])
        )
    assert n == 1

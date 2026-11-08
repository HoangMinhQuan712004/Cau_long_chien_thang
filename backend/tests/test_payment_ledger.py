"""T-057 (ADR-014): sổ tiền vào – một dòng mỗi lần nhận / hoàn tiền, Lịch sử giao dịch và báo cáo
theo ngày tiền về; lượt đặt vẫn theo ngày chơi.

Test có ``clock`` đóng băng đồng hồ engine ở một ngày xa (không lẫn tiền của test khác trong ngày).
"""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import common, report_revenue
from app.modules.booking_engine.models import Booking, PaymentEntry, PaymentEntryItem
from app.modules.booking_engine.tenant import current_tenant_id
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, new_court, random_phone, safe_hour, temp
from tests.helpers_web import checkout, sepay_payload, tomorrow, webhook
from tests.test_recurring_list import create

FD = f"{API}/front-desk"
FAR = (datetime.now(settings.tz) + timedelta(days=200)).date()


def at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz)


@pytest.fixture
def clock(monkeypatch):
    """``clock(ngày, giờ)`` đặt giờ engine."""
    state = {"now": at(FAR, 0, 30)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int, minute: int = 0) -> None:
        state["now"] = at(day, hour, minute)

    return set_time


async def collect(client, code, version=1):
    return await client.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": version}, headers=idem()
    )


async def entries(client, day, **params) -> dict:
    r = await client.get(
        f"{BK}/transactions", params={"from": day.isoformat(), "to": day.isoformat(), **params}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def revenue(day) -> tuple[int, int]:
    """(doanh thu theo ngày tiền về, lượt đặt theo ngày chơi) của một ngày."""
    tid = current_tenant_id()
    async with SessionLocal() as s:
        t = await report_revenue.totals(s, tid, day, day)
        daily = await report_revenue.daily(s, tid, day, day)
    assert daily[0].revenue == t.revenue
    return t.revenue, t.bookings


async def ledger_rows(code: str) -> list[tuple[str, int]]:
    """(loại, tiền mục) của các dòng sổ có booking ``code``."""
    async with SessionLocal() as s:
        rows = await s.execute(
            select(PaymentEntry.kind, PaymentEntryItem.amount)
            .join(PaymentEntryItem, PaymentEntryItem.entry_id == PaymentEntry.id)
            .join(Booking, Booking.id == PaymentEntryItem.booking_id)
            .where(Booking.code == code)
            .order_by(PaymentEntry.id)
        )
        return [tuple(r) for r in rows]


# ------------------------------------------------------------------ AC2, AC7


async def test_recurring_collect_is_one_entry_on_collect_day(admin, clock):
    """Định kỳ 4 buổi tuần sau, thu hôm nay -> 1 dòng 4 mục; tiền ở hôm nay, lượt ở ngày chơi."""
    clock(FAR, 8)
    court = await new_court(admin)
    start = FAR + timedelta(days=7)
    order = await create(
        admin,
        court,
        "Khách Định Kỳ",
        random_phone(),
        start,
        (start.isoweekday(), (start + timedelta(days=1)).isoweekday()),
        pct=10,
    )
    money_before, plays_before = await revenue(FAR)
    r = await admin.post(
        f"{BK}/orders/{order['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    collected = r.json()
    assert len(collected["collected"]) == 4

    [entry] = (await entries(admin, FAR, q=order["order_code"]))["items"]
    assert (entry["kind"], entry["method"], entry["source"]) == ("in", "cash", "counter")
    assert entry["amount"] == collected["amount"]
    assert sorted(i["code"] for i in entry["items"]) == sorted(collected["collected"])
    assert sum(i["amount"] for i in entry["items"]) == entry["amount"]
    assert all(i["play_date"] > FAR.isoformat() for i in entry["items"])

    assert await revenue(FAR) == (money_before + collected["amount"], plays_before)
    # Lượt đặt ở ngày chơi: 4 buổi trong hai tuần từ ``start`` (create() lấy 14 ngày)
    async with SessionLocal() as s:
        t = await report_revenue.totals(s, current_tenant_id(), start, start + timedelta(days=13))
    assert t.bookings >= 4


# ------------------------------------------------------------------ AC5


async def test_refund_lands_on_cancel_day_and_past_day_is_unchanged(admin, staff, clock):
    day, later = FAR + timedelta(days=20), FAR + timedelta(days=23)
    clock(day, 0, 30)
    court = await new_court(admin)
    r = await book(staff, court["code"], 10, customer=temp("Khách Hoàn", random_phone()), day=day)
    assert r.status_code == 201, r.text
    code, amount = r.json()["code"], r.json()["payment"]["amount"]
    clock(day, 8)
    assert (await collect(admin, code)).status_code == 200
    day_money, _ = await revenue(day)
    later_money, _ = await revenue(later)

    clock(later, 9)
    r = await admin.post(
        f"{FD}/items/{code}/cancel",
        json={"reason": "Khách báo bận", "version": 2, "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text

    assert (await revenue(day))[0] == day_money  # ngày đã qua không đổi
    assert (await revenue(later))[0] == later_money - amount
    [kept] = (await entries(admin, day, q=code))["items"]
    assert (kept["kind"], kept["amount"]) == ("in", amount)
    got = await entries(admin, later, q=code)
    [refund] = got["items"]
    assert (refund["kind"], refund["method"], refund["amount"]) == ("refund", "cash", amount)
    assert [i["code"] for i in refund["items"]] == [code]
    assert got["cards"]["refund"] >= amount
    assert await ledger_rows(code) == [("in", amount), ("refund", amount)]


async def test_order_cancel_is_one_refund_entry_and_unpaid_cancel_writes_nothing(admin, clock):
    clock(FAR + timedelta(days=30), 8)
    court = await new_court(admin)
    start = FAR + timedelta(days=37)
    order = await create(
        admin,
        court,
        "Khách Hủy Đơn",
        random_phone(),
        start,
        (start.isoweekday(), (start + timedelta(days=2)).isoweekday()),
    )
    code = order["order_code"]
    r = await admin.post(f"{BK}/orders/{code}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    total = r.json()["amount"]
    preview = (await admin.get(f"{FD}/orders/{code}/cancel-preview")).json()
    r = await admin.post(
        f"{FD}/orders/{code}/cancel",
        json={
            "reason": "Đổi lịch",
            "codes": [i["code"] for i in preview["cancellable"]],
            "refund_confirmed": True,
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    got = (await entries(admin, FAR + timedelta(days=30), q=code))["items"]
    assert [(e["kind"], e["amount"], len(e["items"])) for e in got] == [
        ("refund", total, 4),
        ("in", total, 4),
    ]

    # Hủy khoản chưa thu: không có dòng sổ
    other = await create(admin, court, "Chưa Thu", random_phone(), start + timedelta(days=21), (1,))
    child = other["bookings"][0]["code"]
    r = await admin.post(
        f"{FD}/items/{child}/cancel", json={"reason": "Khách báo bận", "version": 1}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert await ledger_rows(child) == []


# ------------------------------------------------------------------ AC3, AC4


async def test_online_money_is_one_system_entry_and_resend_adds_nothing(anon, admin):
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 19), (court["code"], 20)])
    assert r.status_code == 201, r.text
    co = r.json()
    payload = sepay_payload(co["pay_ref"], co["amount"])
    assert (await webhook(anon, payload)).status_code == 200
    assert (await webhook(anon, payload)).status_code == 200  # SePay gửi lại cùng id

    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                select(PaymentEntry).where(PaymentEntry.reference == f"sepay:{payload['id']}")
            )
        )
    assert len(rows) == 1
    [entry] = (await entries(admin, datetime.now(settings.tz).date(), q=co["order_code"]))["items"]
    assert (entry["kind"], entry["method"], entry["source"]) == ("in", "transfer", "online")
    assert entry["actor_label"] == "Hệ thống" and entry["amount"] == co["amount"]
    assert entry["order_code"] == co["order_code"] and len(entry["items"]) == 2
    assert entry["items"][0]["play_date"] == tomorrow().isoformat()

    # Tiền không khớp đơn: không vào sổ
    stray = sepay_payload(None, 77_000, content="chuyen tien an trua")
    assert (await webhook(anon, stray)).status_code == 200
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(PaymentEntry)
            .where(PaymentEntry.reference == f"sepay:{stray['id']}")
        )
    assert n == 0


# ------------------------------------------------------------------ AC11


async def test_two_desks_collect_once_and_customer_cannot_view(admin, staff, customer):
    court = await new_court(admin)
    r = await book(
        staff, court["code"], await safe_hour(), customer=temp("Hai Máy", random_phone())
    )
    code = r.json()["code"]
    results = await asyncio.gather(collect(admin, code), collect(staff, code))
    assert sorted(x.status_code for x in results) == [200, 409]
    loser = next(x for x in results if x.status_code == 409)
    assert loser.json()["detail"]["code"] == "E-012"
    assert len(await ledger_rows(code)) == 1
    assert (await customer.get(f"{BK}/transactions")).status_code in (401, 403)


def test_split_by_hours_keeps_the_sum_for_refunds():
    minutes = {"S02": 60, "S01": 60, "S10": 60}
    assert sum(report_revenue.split_by_hours(-100, minutes).values()) == -100
    assert report_revenue.split_by_hours(-100, minutes) == {
        code: -part for code, part in report_revenue.split_by_hours(100, minutes).items()
    }

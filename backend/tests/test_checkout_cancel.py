"""Hủy giữ chỗ đơn online chưa thanh toán + một người một đơn chờ (E-WEB-4 kèm đơn cũ)."""

import asyncio

from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.api import expire_holds
from app.modules.booking_engine.models import Allocation, Booking, Checkout, Hold
from tests import test_play_rooms as base
from tests.conftest import API
from tests.helpers_booking import new_court, random_phone
from tests.helpers_web import WEB, checkout, simulate
from tests.test_online_payments import shift_expiry
from tests.test_ticket_online import buy, event_info, new_event

people = base.people  # fixture: hội viên có tài khoản liên kết

MA = f"{API}/member-area"
PENDING_MESSAGE = "Bạn còn đơn chưa thanh toán. Hãy thanh toán hoặc hủy đơn đó để đặt đơn mới."


async def cancel(client, token: str):
    return await client.post(f"{WEB}/checkouts/{token}/cancel")


def detail(r) -> dict:
    return r.json()["detail"]


async def expire_now(pay_ref: str) -> None:
    """Quá hạn + quá ân hạn rồi chạy việc hết hạn như worker."""
    await shift_expiry(pay_ref, 3600)
    async with SessionLocal() as s:
        await expire_holds(s)
        await s.commit()


async def _court(admin) -> str:
    return (await new_court(admin))["code"]


async def test_cancel_releases_slot_and_is_idempotent(anon, admin):
    code = await _court(admin)
    phone = random_phone()
    r = await checkout(anon, [(code, 10), (code, 11)], phone=phone)
    assert r.status_code == 201, r.text
    co = r.json()

    r = await cancel(anon, co["token"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "cancelled" and out["bank"] is None
    assert [i["code"] for i in out["items"]] == [i["code"] for i in co["items"]]
    async with SessionLocal() as s:
        c = await s.scalar(select(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
        holds = list(await s.scalars(select(Hold).where(Hold.checkout_id == c.id)))
        allocs = list(
            await s.scalars(select(Allocation).where(Allocation.hold_id.in_([h.id for h in holds])))
        )
        audits = list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "checkout.cancel", AuditLog.entity_code == co["pay_ref"]
                )
            )
        )
    assert c.status == "cancelled" and {h.status for h in holds} == {"released"}
    assert allocs and not any(a.active for a in allocs)
    assert len(audits) == 1 and audits[0].actor_type == "web"

    # Gọi lại -> cùng kết quả, không ghi thêm nhật ký
    again = await cancel(anon, co["token"])
    assert again.status_code == 200 and again.json()["status"] == "cancelled"
    seen = await anon.get(f"{WEB}/checkouts/{co['token']}")
    assert seen.status_code == 200 and seen.json()["status"] == "cancelled"
    found = await anon.post(f"{WEB}/lookup", json={"code": co["order_code"], "phone": phone})
    assert found.status_code == 200 and found.json()["status"] == "cancelled"

    # Khung mở lại ngay: người khác đặt được; chính SĐT đó cũng đặt đơn mới được
    other = await checkout(anon, [(code, 10)])
    assert other.status_code == 201, other.text
    mine = await checkout(anon, [(code, 11)], phone=phone)
    assert mine.status_code == 201, mine.text


async def test_cancel_refused_once_money_recorded_or_expired(anon, admin):
    code = await _court(admin)
    co = (await checkout(anon, [(code, 13)])).json()
    assert await simulate(admin, co["pay_ref"], 10_000) == "partial"
    r = await cancel(anon, co["token"])
    assert r.status_code == 409 and detail(r)["code"] == "E-WEB-12"
    assert detail(r)["reason"] == "partially_paid"
    assert await simulate(admin, co["pay_ref"], co["amount"] - 10_000) == "applied"
    r = await cancel(anon, co["token"])
    assert r.status_code == 409 and detail(r)["reason"] == "paid"

    late = (await checkout(anon, [(code, 15)])).json()
    await expire_now(late["pay_ref"])
    r = await cancel(anon, late["token"])
    assert r.status_code == 409 and detail(r)["reason"] == "expired"

    # Quá hạn nhưng worker chưa xử lý: vẫn hủy được (khung trả ngay)
    slow = (await checkout(anon, [(code, 17)])).json()
    await shift_expiry(slow["pay_ref"], 3600)
    r = await cancel(anon, slow["token"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"

    r = await cancel(anon, "khong-co-token-nay")
    assert r.status_code == 404 and detail(r)["code"] == "E-WEB-6"


async def test_member_checkout_cancel_only_by_that_member(anon, admin, people):
    host, other = await people("Chủ Đơn Hủy"), await people("Người Khác")
    code = await _court(admin)
    r = await checkout(host.client, [(code, 9)], as_member=True, phone_token=None)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    for client in (anon, other.client):
        r = await cancel(client, token)
        assert r.status_code == 404 and detail(r)["code"] == "E-WEB-6"
    r = await cancel(host.client, token)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "checkout.cancel", AuditLog.entity_code == r.json()["pay_ref"]
            )
        )
    assert row.actor_type == "customer"


async def test_payment_after_cancel_goes_refund_path(anon, admin):
    code = await _court(admin)
    co = (await checkout(anon, [(code, 19)])).json()
    assert (await cancel(anon, co["token"])).status_code == 200
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "refund_needed"
    async with SessionLocal() as s:
        c = await s.scalar(select(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
        made = await s.scalar(select(Booking.id).where(Booking.checkout_id == c.id))
    assert c.status == "cancelled" and c.paid_amount == 0 and made is None


async def test_cancel_races_payment_exactly_one_wins(anon, admin):
    """Hủy ∥ tiền về: khóa dòng checkout -> hoặc hủy (tiền cần hoàn) hoặc đã trả (từ chối hủy)."""
    code = await _court(admin)
    co = (await checkout(anon, [(code, 21)])).json()
    r, outcome = await asyncio.gather(
        cancel(anon, co["token"]), simulate(admin, co["pay_ref"], co["amount"])
    )
    if r.status_code == 200:
        assert outcome == "refund_needed"
    else:
        assert r.status_code == 409 and detail(r)["reason"] == "paid" and outcome == "applied"


async def test_ticket_cancel_frees_seats(anon, admin):
    ev = await new_event(admin, capacity=2)
    r = await buy(anon, ev["code"], 2)
    assert r.status_code == 201, r.text
    assert (await event_info(anon, ev["code"]))["taken"] == 2
    r = await cancel(anon, r.json()["token"])
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (await event_info(anon, ev["code"]))["taken"] == 0
    assert (await buy(anon, ev["code"], 2)).status_code == 201


async def test_pending_order_blocks_new_court_and_ticket(anon, admin):
    code = await _court(admin)
    ev = await new_event(admin, name="Giao lưu chặn đơn")
    phone = random_phone()
    first = (await checkout(anon, [(code, 8), (code, 9)], phone=phone)).json()

    r = await checkout(anon, [(code, 12)], phone=phone)
    assert r.status_code == 409, r.text
    body = detail(r)
    assert body["code"] == "E-WEB-4" and body["message"] == PENDING_MESSAGE
    pending = body["pending"]
    assert pending["order_code"] == first["order_code"] and pending["kind"] == "court"
    assert (pending["start_time"], pending["end_time"]) == ("08:00", "10:00")
    assert pending["title"] == first["items"][0]["resource_name"]
    assert pending["pay_token"] == first["token"] and pending["paid_amount"] == 0
    r = await buy(anon, ev["code"], 1, phone=phone)
    assert r.status_code == 409 and detail(r)["pending"]["order_code"] == first["order_code"]

    # Đơn vé đang chờ cũng chặn đặt sân
    other_phone = random_phone()
    ticket = (await buy(anon, ev["code"], 1, phone=other_phone)).json()
    r = await checkout(anon, [(code, 14)], phone=other_phone)
    assert r.status_code == 409
    assert detail(r)["pending"]["kind"] == "ticket"
    assert detail(r)["pending"]["title"] == "Giao lưu chặn đơn"
    assert detail(r)["pending"]["pay_token"] == ticket["token"]

    # Hết hạn -> đặt mới được
    await expire_now(first["pay_ref"])
    assert (await checkout(anon, [(code, 12)], phone=phone)).status_code == 201


async def test_member_pending_payment(admin, customer, people):
    host = await people("Chờ Thanh Toán")
    r = await host.client.get(f"{MA}/pending-payment")
    assert r.status_code == 200 and r.json() is None
    code = await _court(admin)
    co = (await checkout(host.client, [(code, 16)], as_member=True, phone_token=None)).json()
    got = (await host.client.get(f"{MA}/pending-payment")).json()
    assert got["order_code"] == co["order_code"] and got["pay_token"] == co["token"]
    assert got["amount"] == co["amount"] and got["expires_at"]
    assert (await cancel(host.client, co["token"])).status_code == 200
    assert (await host.client.get(f"{MA}/pending-payment")).json() is None
    r = await customer.get(f"{MA}/pending-payment")
    assert r.status_code == 403


async def test_overdue_pending_does_not_block_and_is_closed_on_new_order(anon, admin, people):
    """Quá expires_at, worker chưa chạy (còn trong ân hạn): không còn là đơn chờ – đặt mới được
    ngay (sân và vé); đơn cũ thành expired, khung cũ mở."""
    code = await _court(admin)
    ev = await new_event(admin, capacity=1)
    phone = random_phone()
    old = (await checkout(anon, [(code, 6)], phone=phone)).json()
    await shift_expiry(old["pay_ref"], 5)  # trong ân hạn 60 giây: worker chưa đóng
    r = await checkout(anon, [(code, 7)], phone=phone)
    assert r.status_code == 201, r.text
    async with SessionLocal() as s:
        c = await s.scalar(select(Checkout).where(Checkout.pay_ref == old["pay_ref"]))
        holds = list(await s.scalars(select(Hold).where(Hold.checkout_id == c.id)))
        alloc = await s.scalar(select(Allocation).where(Allocation.hold_id == holds[0].id))
    assert c.status == "expired" and {h.status for h in holds} == {"expired"}
    assert alloc.active is False
    assert (await checkout(anon, [(code, 6)])).status_code == 201  # khung cũ mở
    assert await simulate(admin, old["pay_ref"], old["amount"]) == "refund_needed"

    # Vé: lượt vé quá hạn của SĐT khác không chặn mua tiếp, ghế được trả
    buyer = random_phone()
    first = (await buy(anon, ev["code"], 1, phone=buyer)).json()
    await shift_expiry(first["pay_ref"], 5)
    r = await buy(anon, ev["code"], 1, phone=buyer)
    assert r.status_code == 201, r.text

    # Hội viên: đơn quá hạn không còn hiện ở thẻ "Chờ thanh toán"
    host = await people("Quá Hạn")
    co = (await checkout(host.client, [(code, 8)], as_member=True, phone_token=None)).json()
    await shift_expiry(co["pay_ref"], 5)
    assert (await host.client.get(f"{MA}/pending-payment")).json() is None

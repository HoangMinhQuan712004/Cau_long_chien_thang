"""T-008: tiền về (webhook SePay, giả lập), hết hạn + ân hạn, tra cứu, Tiền về cần xử lý."""

import asyncio
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update

from app.core.config import Settings, settings
from app.core.db import SessionLocal
from app.modules.booking_engine.api import expire_holds, publish_outbox
from app.modules.booking_engine.models import Booking, Checkout, Hold
from app.modules.members.models import Customer
from app.modules.payments.models import BankTransaction
from tests.conftest import idem
from tests.helpers_booking import BK, book, calendar, new_court, random_phone, safe_hour
from tests.helpers_web import (
    PAY,
    WEB,
    checkout,
    sepay_payload,
    simulate,
    tomorrow,
    web_calendar,
    webhook,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


async def new_checkout(anon, admin, hours=(19, 20), phone=None, name="Khách Online") -> dict:
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], h) for h in hours], phone=phone, name=name)
    assert r.status_code == 201, r.text
    return {**r.json(), "court": court}


async def drain_outbox() -> None:
    """Phát hết outbox (test khác để lại nhiều sự kiện; mỗi lượt phát tối đa 100)."""
    while await publish_outbox(SessionLocal):
        pass


async def txn(provider_txn_id: str) -> BankTransaction:
    async with SessionLocal() as s:
        return await s.scalar(
            select(BankTransaction).where(BankTransaction.provider_txn_id == provider_txn_id)
        )


async def shift_expiry(pay_ref: str, seconds_ago: int) -> None:
    """Đẩy hạn giữ chỗ về quá khứ (giả lập thời gian trôi)."""
    async with SessionLocal() as s:
        await s.execute(
            update(Checkout)
            .where(Checkout.pay_ref == pay_ref)
            .values(expires_at=func.now() - timedelta(seconds=seconds_ago))
        )
        await s.execute(
            update(Hold)
            .where(
                Hold.checkout_id
                == select(Checkout.id).where(Checkout.pay_ref == pay_ref).scalar_subquery()
            )
            .values(expires_at=func.now() - timedelta(seconds=seconds_ago))
        )
        await s.commit()


# ------------------------------------------------------------------ tiền về đủ (AC21, AC24, AC31)


async def test_paid_creates_bookings_with_same_codes(anon, admin, staff):
    phone = random_phone()
    co = await new_checkout(anon, admin, hours=(19, 20), phone=phone, name="Lê Văn Online")
    r = await webhook(anon, sepay_payload(co["pay_ref"], co["amount"], id=900001))
    assert r.status_code == 200 and r.json() == {"success": True}
    t = await txn("900001")
    assert t.outcome == "applied" and t.refund_amount == 0
    assert t.booking_codes == [co["items"][0]["code"]]

    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "paid" and view["bank"] is None and view["paid_at"]
    assert view["paid_amount"] == co["amount"]

    item = (await staff.get(f"{BK}/items/{co['items'][0]['code']}")).json()
    assert item["source"] == "online" and item["created_by"] == "Khách đặt online"
    assert item["payment"]["payment_status"] == "paid"
    assert item["payment"]["payment_method"] == "online_transfer"
    assert item["payment"]["collected_by"] == "Khách đặt online"
    assert item["payment"]["amount"] == co["items"][0]["amount"]
    assert item["actions"] == []
    cal = await calendar(staff, tomorrow())
    block = next(b for b in cal["blocks"] if b["code"] == co["items"][0]["code"])
    assert (block["type"], block["source"], block["payment_status"]) == (
        "booking",
        "online",
        "paid",
    )
    # Khung vẫn bị chiếm (allocation chuyển sang booking, không có khoảnh khắc trống)
    again = await checkout(anon, [(co["court"]["code"], 19)])
    assert again.status_code == 409

    # Gửi lại cùng id -> không cộng lần hai
    r = await webhook(anon, sepay_payload(co["pay_ref"], co["amount"], id=900001))
    assert r.json() == {"success": True}
    async with SessionLocal() as s:
        row = await s.scalar(select(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
        assert row.paid_amount == co["amount"]
        assert await s.scalar(select(func.count()).where(Booking.checkout_id == row.id)) == 1

    # Outbox -> members tạo hồ sơ tạm khi tiền về (không tạo lúc giữ chỗ)
    async with SessionLocal() as s:
        assert await s.scalar(select(Customer).where(Customer.phone == phone)) is None
    await drain_outbox()
    async with SessionLocal() as s:
        created = await s.scalar(select(Customer).where(Customer.phone == phone))
    assert created.kind == "temp" and created.full_name == "Lê Văn Online"


async def test_partial_then_full_and_overpay(anon, admin):
    co = await new_checkout(anon, admin, hours=(9,))
    half = co["amount"] // 2
    assert await simulate(admin, co["pay_ref"], half) == "partial"
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "pending" and view["paid_amount"] == half
    assert await simulate(admin, co["pay_ref"], co["amount"] - half + 5_000) == "applied"
    async with SessionLocal() as s:
        t = await s.scalar(
            select(BankTransaction).where(
                BankTransaction.pay_ref == co["pay_ref"], BankTransaction.outcome == "applied"
            )
        )
    assert t.refund_amount == 5_000


async def test_concurrent_webhooks_create_booking_once(anon, admin):
    co = await new_checkout(anon, admin, hours=(15,))
    r1, r2 = await asyncio.gather(
        webhook(anon, sepay_payload(co["pay_ref"], co["amount"], id=910001)),
        webhook(anon, sepay_payload(co["pay_ref"], co["amount"], id=910002)),
    )
    assert r1.status_code == r2.status_code == 200
    outcomes = sorted([(await txn("910001")).outcome, (await txn("910002")).outcome])
    assert outcomes == ["applied", "refund_needed"]
    async with SessionLocal() as s:
        row = await s.scalar(select(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
        assert row.paid_amount == co["amount"]  # tiền thừa ghi ở giao dịch, không cộng vào
        assert await s.scalar(select(func.count()).where(Booking.checkout_id == row.id)) == 1


# ------------------------------------------------------------------ hết hạn + ân hạn (AC14, AC22)


async def test_expiry_grace_and_late_money(anon, admin, staff):
    co = await new_checkout(anon, admin, hours=(11,))
    await shift_expiry(co["pay_ref"], 30)  # quá 5 phút nhưng còn trong ân hạn 60 giây
    async with SessionLocal() as s:
        await expire_holds(s)
        await s.commit()
    view = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert view["status"] == "pending"
    cal = await calendar(staff, tomorrow())
    assert [b for b in cal["blocks"] if co["court"]["code"] in b["resource_codes"]]
    # Tiền về trong ân hạn vẫn được nhận
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"

    late = await new_checkout(anon, admin, hours=(12,))
    assert await simulate(admin, late["pay_ref"], 10_000) == "partial"
    await shift_expiry(late["pay_ref"], 90)
    async with SessionLocal() as s:
        assert await expire_holds(s) >= 1
        await s.commit()
    view = (await anon.get(f"{WEB}/checkouts/{late['token']}")).json()
    assert view["status"] == "expired" and view["bank"] is None
    cal = await calendar(staff, tomorrow())
    assert not [b for b in cal["blocks"] if late["court"]["code"] in b["resource_codes"]]
    assert (await checkout(anon, [(late["court"]["code"], 12)])).status_code == 201  # trống lại
    # Phần đã trả trước khi hết hạn -> cần hoàn (qua sự kiện outbox)
    await drain_outbox()
    async with SessionLocal() as s:
        partial = await s.scalar(
            select(BankTransaction).where(BankTransaction.pay_ref == late["pay_ref"])
        )
    assert (partial.outcome, partial.refund_amount) == ("refund_needed", 10_000)
    # Tiền về sau khi hết hạn -> không tạo booking, cần hoàn toàn bộ
    assert await simulate(admin, late["pay_ref"], late["amount"]) == "refund_needed"
    async with SessionLocal() as s:
        assert (
            await s.scalar(select(func.count()).where(Booking.code == late["items"][0]["code"]))
            == 0
        )


# ------------------------------------------------------------------ webhook (AC19–AC20, SEC5)


async def test_webhook_signature_and_body(anon, monkeypatch):
    payload = sepay_payload("BK20991231001", 100_000, id=920001)
    r = await webhook(anon, payload, secret="wrong")
    assert r.status_code == 401 and r.json() == {"success": False}
    r = await anon.post(f"{PAY}/sepay/webhook", json=payload)  # thiếu header
    assert r.status_code == 401
    assert await txn("920001") is None
    r = await webhook(anon, {"id": 920002, "transferType": "in"})  # thiếu transferAmount
    assert r.status_code == 400
    monkeypatch.setattr(settings, "SEPAY_WEBHOOK_SECRET", "")
    r = await webhook(anon, payload)
    assert r.status_code == 503 and r.json() == {"success": False}


async def test_webhook_classification(anon):
    r = await webhook(anon, sepay_payload(None, 50_000, id=930001, content="chuyen tien an trua"))
    assert r.status_code == 200 and (await txn("930001")).outcome == "unmatched"
    await webhook(anon, sepay_payload("BK20991231001", 50_000, id=930002))
    assert (await txn("930002")).outcome == "unmatched"  # không có lượt thanh toán mang mã này
    await webhook(anon, sepay_payload("BK20991231001", 50_000, id=930003, transferType="out"))
    assert (await txn("930003")).outcome == "ignored"
    await webhook(anon, sepay_payload("BK20991231001", 50_000, id=930004, accountNumber="999"))
    assert (await txn("930004")).outcome == "ignored"


async def test_webhook_code_from_content(anon, admin):
    co = await new_checkout(anon, admin, hours=(16,))
    payload = sepay_payload(
        None, co["amount"], id=940001, content=f"chuyen {co['pay_ref'].lower()} ok"
    )
    await webhook(anon, payload)
    t = await txn("940001")
    assert (t.code, t.outcome) == (co["pay_ref"], "applied")
    two = sepay_payload(None, 1000, id=940002, content="BK20991231001 BK20991231002")
    await webhook(anon, two)
    assert (await txn("940002")).code is None  # hai mã khác nhau -> không đoán


# ------------------------------------------------------------------ tra cứu (AC25–AC27, SEC2)


async def test_lookup(anon, admin, staff):
    phone = random_phone()
    co = await new_checkout(anon, admin, hours=(17, 18), phone=phone)
    code = co["items"][0]["code"]
    spaced = f"{phone[:4]} {phone[4:7]}.{phone[7:]}"
    r = await anon.post(
        f"{WEB}/lookup", json={"code": f" {code.replace('-', '').lower()} ", "phone": spaced}
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["status"] == "pending" and res["hours"] == 2
    assert res["pending"]["pay_ref"] == co["pay_ref"] and res["pending"]["bank"]["qr_url"]
    assert res["phone_masked"] == f"{phone[:4]} xxx {phone[-3:]}" and phone not in r.text

    await simulate(admin, co["pay_ref"], co["amount"])
    res = (await anon.post(f"{WEB}/lookup", json={"code": code, "phone": phone})).json()
    assert (res["status"], res["payment_method_label"]) == ("paid", "Chuyển khoản")
    assert res["pending"] is None and res["paid_at"]

    not_found = {
        "code": "E-WEB-7",
        "message": "Không tìm thấy booking. Kiểm tra lại mã và số điện thoại.",
    }
    for body in (
        {"code": code, "phone": random_phone()},
        {"code": "BK-20000101-001", "phone": phone},
        {"code": code, "phone": "abc"},
    ):
        r = await anon.post(f"{WEB}/lookup", json=body)
        assert r.status_code == 404 and r.json()["detail"] == not_found

    # Booking tại quầy cũng tra được
    court = await new_court(admin)
    hour = await safe_hour()
    b = (await book(staff, court["code"], hour, customer={"member_code": "HV0012"})).json()
    res = (await anon.post(f"{WEB}/lookup", json={"code": b["code"], "phone": "0912111222"})).json()
    assert res["status"] == "unpaid" and res["payment_method_label"] is None


async def test_lookup_expired_and_rate_limit(anon, admin):
    phone = random_phone()
    co = await new_checkout(anon, admin, hours=(7,), phone=phone)
    await shift_expiry(co["pay_ref"], 120)
    async with SessionLocal() as s:
        await expire_holds(s)
        await s.commit()
    res = (
        await anon.post(f"{WEB}/lookup", json={"code": co["items"][0]["code"], "phone": phone})
    ).json()
    assert res["status"] == "expired" and res["pending"] is None
    for _ in range(9):  # lần tra cứu ở trên + 9 = 10 lần/phút được phép
        await anon.post(f"{WEB}/lookup", json={"code": "x", "phone": "y"})
    r = await anon.post(f"{WEB}/lookup", json={"code": "x", "phone": "y"})
    assert r.status_code == 429


async def test_lookup_requires_origin(anon):
    anon.headers.pop("Origin")
    r = await anon.post(f"{WEB}/lookup", json={"code": "x", "phone": "y"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"


# ---------------------------------------------- Tiền về cần xử lý (AC32, SEC7–SEC8)


async def test_bank_transactions_admin_only_and_resolve(anon, admin, staff, customer):
    await webhook(anon, sepay_payload(None, 77_000, id=950001, content="khong ro"))
    for client in (staff, customer):
        assert (await client.get(f"{PAY}/bank-transactions")).status_code == 403
    assert (await anon.get(f"{PAY}/bank-transactions")).status_code == 401
    rows = (await admin.get(f"{PAY}/bank-transactions")).json()
    row = next(x for x in rows if x["provider_txn_id"] == "950001")
    assert row["outcome"] == "unmatched" and row["resolved_at"] is None
    path = f"{PAY}/bank-transactions/{row['id']}/resolve"
    r = await admin.post(path, json={"note": "  "}, headers=idem())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001"
    r = await staff.post(path, json={"note": "x"}, headers=idem())
    assert r.status_code == 403
    r = await admin.post(path, json={"note": "Đã gọi khách, hoàn tiền tay"}, headers=idem())
    assert r.status_code == 200 and r.json()["resolved_by_label"] == "Admin"
    r = await admin.post(path, json={"note": "lần hai"}, headers=idem())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-PAY-2"
    pending = (await admin.get(f"{PAY}/bank-transactions")).json()
    assert row["id"] not in [x["id"] for x in pending]
    everything = (
        await admin.get(f"{PAY}/bank-transactions", params={"needs_action": False})
    ).json()
    assert row["id"] in [x["id"] for x in everything]


async def test_simulate_guard(admin, staff, monkeypatch):
    body = {"pay_ref": "BK20991231001", "amount": 1000}
    assert (await staff.post(f"{PAY}/dev/simulate", json=body, headers=idem())).status_code == 403
    monkeypatch.setattr(settings, "PAYMENTS_SIMULATE", False)
    for client in (admin, staff):
        r = await client.post(f"{PAY}/dev/simulate", json=body, headers=idem())
        assert r.status_code == 404


# ------------------------------------------------------------------ ENV (staging / production)


def test_env_values_and_guards():
    with pytest.raises(ValidationError):
        Settings(ENV="prod")
    strong = "x" * 40
    with pytest.raises(ValidationError):
        Settings(ENV="production", SECRET_KEY=strong, PAYMENTS_SIMULATE=True)
    with pytest.raises(ValidationError):
        Settings(ENV="staging", SECRET_KEY="change-me")
    key = "dGVzdC1rZXktZm9yLXBheW1lbnRzLWVuY3J5cHRpb24="
    with pytest.raises(ValidationError):  # thiếu khóa mã hóa ở staging (T-012)
        Settings(ENV="staging", SECRET_KEY=strong)
    staging = Settings(
        ENV="staging", SECRET_KEY=strong, PAYMENTS_SIMULATE=True, PAYMENTS_ENCRYPTION_KEY=key
    )
    assert staging.is_deployed and not staging.is_production
    assert Settings(ENV="development").is_deployed is False


def test_staging_hides_api_docs():
    code = "from app.main import app; print(app.docs_url, app.openapi_url)"
    env = {
        **os.environ,
        "ENV": "staging",
        "SECRET_KEY": "s" * 40,
        "PAYMENTS_ENCRYPTION_KEY": "dGVzdC1rZXktZm9yLXBheW1lbnRzLWVuY3J5cHRpb24=",
    }
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split()[-2:] == ["None", "None"]


async def test_web_calendar_after_payment_shows_booked(anon, admin):
    co = await new_checkout(anon, admin, hours=(13,))
    await simulate(admin, co["pay_ref"], co["amount"])
    cal = (await web_calendar(anon)).json()
    row = next(x for x in cal["resources"] if x["code"] == co["court"]["code"])
    assert {s["start_hour"]: s["state"] for s in row["slots"]}[13] == "booked"


def test_settings_errors_do_not_echo_env_values():
    """Lỗi cấu hình (in ra docker logs) nêu tên biến, không in giá trị bí mật."""
    secret = "S3cret-" + "k" * 40
    db_url = "postgresql+asyncpg://user:Pw-should-not-leak@db:5432/caulong"
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None, ENV="staging", SECRET_KEY=secret, DATABASE_URL=db_url)
    message = str(e.value)
    assert "PAYMENTS_ENCRYPTION_KEY" in message
    assert secret not in message and "Pw-should-not-leak" not in message
    assert "input_value" not in message

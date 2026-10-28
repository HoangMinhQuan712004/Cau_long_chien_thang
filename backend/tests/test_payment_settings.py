"""T-012: Cài đặt thanh toán online (tài khoản nhận tiền, khóa SePay, công tắc)."""

from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine.api import expire_holds
from app.modules.booking_engine.models import Checkout, Hold
from app.modules.payments import config as payment_config
from app.modules.payments.models import PaymentSettings
from tests.conftest import API, idem
from tests.helpers_booking import new_court, random_phone
from tests.helpers_web import checkout, sepay_payload, webhook

PAY = f"{API}/payments"
SECRET = "owner-webhook-secret-0123456789"
SECRET2 = "owner-NEW-webhook-secret-9876543210"
ACCOUNT = "9704221234567"


async def expire_pending_checkouts() -> None:
    """Lượt chờ do test khác để lại sẽ chặn đổi tài khoản (E-PAY-3) – cho hết hạn hẳn."""
    past = func.now() - timedelta(minutes=10)
    async with SessionLocal() as s:
        await s.execute(
            update(Checkout).where(Checkout.status == "pending").values(expires_at=past)
        )
        await s.execute(update(Hold).where(Hold.status == "active").values(expires_at=past))
        await expire_holds(s)
        await s.commit()


@pytest.fixture(autouse=True)
async def empty_settings():
    """Mỗi test bắt đầu / kết thúc với bảng trống -> test khác vẫn dùng SEPAY_* của .env."""
    await expire_pending_checkouts()
    async with SessionLocal() as s:
        await s.execute(delete(PaymentSettings))
        await s.commit()
    payment_config.clear_cache()
    yield
    async with SessionLocal() as s:
        await s.execute(delete(PaymentSettings))
        await s.commit()
    payment_config.clear_cache()


def body(**over) -> dict:
    data = {
        "bank_code": "VCB",
        "account_number": ACCOUNT,
        "account_name": "San Cầu Lông Chiến Thắng",
        "online_toggle": True,
        "webhook_secret": SECRET,
        "current_password": settings.FIRST_ADMIN_PASSWORD,
        **over,
    }
    return {k: v for k, v in data.items() if v is not ...}


async def put(client, **over):
    return await client.put(f"{PAY}/settings", json=body(**over), headers=idem())


async def test_get_falls_back_to_env_then_db_is_the_only_source(admin):
    d = (await admin.get(f"{PAY}/settings")).json()
    assert d["account_number"] == settings.SEPAY_ACCOUNT_NUMBER and d["online_enabled"] is True
    assert d["updated_at"] is None and d["secret_set"] is True
    assert d["webhook_url"].endswith("/api/v1/payments/sepay/webhook")
    assert d["pay_code_hint"] == "BK + 11 chữ số"

    # Dòng DB mới không kế thừa khóa của .env: bật công tắc thiếu khóa -> E-PAY-4
    r = await put(admin, webhook_secret=...)
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "E-PAY-4",
        "message": "Chưa đủ thông tin để bật đặt online.",
    }
    r = await put(admin, webhook_secret=..., online_toggle=False)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["missing"] == ["webhook_secret"] and d["online_enabled"] is False
    assert d["account_name"] == "SAN CAU LONG CHIEN THANG" and d["bank_name"] == "Vietcombank"
    assert d["updated_by_label"] == "Admin" and d["updated_at"]

    d = (await put(admin)).json()
    assert d["online_enabled"] is True and d["secret_last4"] == SECRET[-4:]
    assert SECRET not in str(d)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"bank_code": "XYZ"}, "Chọn ngân hàng."),
        ({"account_number": "12345"}, "Số tài khoản gồm 6–20 chữ số."),
        ({"account_number": "12a4567"}, "Số tài khoản gồm 6–20 chữ số."),
        ({"account_name": "A"}, "Tên chủ tài khoản 2–50 ký tự, không dấu."),
        ({"account_name": "NGUYEN 123"}, "Tên chủ tài khoản 2–50 ký tự, không dấu."),
        ({"webhook_secret": "x" * 15}, "Khóa bí mật 16–128 ký tự."),
    ],
)
async def test_field_validation(admin, over, message):
    r = await put(admin, **over)
    assert r.status_code == 422 and r.json()["detail"] == {"code": "E-PAY-4", "message": message}
    async with SessionLocal() as s:
        assert await s.scalar(select(PaymentSettings)) is None


async def test_password_required_and_lockout(admin, staff):
    r = await put(admin, current_password="sai-mat-khau")
    assert r.status_code == 400 and r.json()["detail"] == {
        "code": "E-AUTH-7",
        "message": "Mật khẩu không đúng.",
    }
    for _ in range(4):
        assert (await put(admin, current_password="sai")).status_code == 400
    r = await put(admin)  # đúng mật khẩu nhưng đang bị khóa
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"
    async with SessionLocal() as s:
        assert await s.scalar(select(PaymentSettings)) is None
    for client in (staff,):
        assert (await client.get(f"{PAY}/settings")).status_code == 403
        assert (await client.get(f"{PAY}/banks")).status_code == 403


async def test_secret_encrypted_kept_and_rotated(admin, anon):
    assert (await put(admin)).status_code == 200
    async with SessionLocal() as s:
        row = await s.scalar(select(PaymentSettings))
    assert row.webhook_secret_enc and SECRET.encode() not in row.webhook_secret_enc
    assert payment_config.decrypt_secret(row.webhook_secret_enc) == SECRET

    d = (await put(admin, webhook_secret=None)).json()
    assert d["secret_last4"] == SECRET[-4:]  # null -> giữ khóa cũ

    # Webhook ký bằng khóa trong DB; đổi khóa -> khóa cũ bị từ chối
    pay = sepay_payload(None, 1000, accountNumber=ACCOUNT)
    assert (await webhook(anon, pay, secret=SECRET)).status_code == 200
    assert (await put(admin, webhook_secret=SECRET2)).status_code == 200
    assert (await webhook(anon, sepay_payload(None, 1000), secret=SECRET)).status_code == 401
    assert (await webhook(anon, sepay_payload(None, 1000), secret=SECRET2)).status_code == 200
    seen = (await admin.get(f"{PAY}/settings")).json()["last_webhook_at"]
    assert seen

    async with SessionLocal() as s:
        details = [
            str(d)
            for d in await s.scalars(
                select(AuditLog.detail).where(AuditLog.action == "payments.settings.update")
            )
        ]
    assert details and all(
        SECRET not in d and SECRET2 not in d and ACCOUNT not in d for d in details
    )
    assert any(ACCOUNT[-4:] in d for d in details)


async def test_qr_and_account_filter_use_db(admin, anon):
    assert (await put(admin)).status_code == 200
    court = await new_court(admin)
    co = (await checkout(anon, [(court["code"], 9)], phone=random_phone())).json()
    assert co["bank"]["account_number"] == ACCOUNT and f"acc={ACCOUNT}" in co["bank"]["qr_url"]
    assert "bank=Vietcombank" in co["bank"]["qr_url"]
    # Chuyển vào số TK khác -> bỏ qua; đúng số TK -> tạo booking
    other = sepay_payload(co["pay_ref"], co["amount"], accountNumber="0123456789")
    assert (await webhook(anon, other, secret=SECRET)).status_code == 200
    mine = sepay_payload(co["pay_ref"], co["amount"], accountNumber=ACCOUNT)
    await webhook(anon, mine, secret=SECRET)
    view = (await anon.get(f"{API}/web/booking/checkouts/{co['token']}")).json()
    assert view["status"] == "paid"


async def test_account_change_blocked_while_checkout_pending(admin, anon):
    assert (await put(admin)).status_code == 200
    court = await new_court(admin)
    assert (await checkout(anon, [(court["code"], 10)], phone=random_phone())).status_code == 201
    assert (await admin.get(f"{PAY}/settings")).json()["pending_checkouts"] >= 1
    for over in ({"account_number": "9704220000001"}, {"bank_code": "ACB"}):
        r = await put(admin, **over)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-PAY-3"
    # Tên chủ TK, khóa, công tắc vẫn đổi được
    assert (await put(admin, account_name="TEN MOI")).status_code == 200
    assert (await put(admin, online_toggle=False)).status_code == 200


async def test_toggle_off_disables_public_booking(admin, anon):
    assert (await put(admin, online_toggle=False)).status_code == 200
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 11)], phone=random_phone())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-WEB-5"


async def test_banks_list(admin):
    banks = (await admin.get(f"{PAY}/banks")).json()
    assert len(banks) >= 20 and {"code", "short_name", "name"} <= set(banks[0])
    assert "VCB" in [b["code"] for b in banks]


async def test_account_name_normalisation():
    from app.modules.payments.settings_service import normalize_account_name

    assert normalize_account_name("  Nguyễn  Văn Đạt  ") == "NGUYEN VAN DAT"
    assert normalize_account_name("đỗ thị ánh") == "DO THI ANH"

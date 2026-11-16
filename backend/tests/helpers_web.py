"""Helper dùng chung cho test web khách (T-008)."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import date, datetime, timedelta

from app.core.config import settings
from app.modules.members.api import normalize_phone
from tests.conftest import API, SEPAY_SECRET, idem
from tests.helpers_booking import random_phone, today

WEB = f"{API}/web/booking"
PAY = f"{API}/payments"


def tomorrow() -> date:
    return today() + timedelta(days=1)


async def web_calendar(client, day: date | None = None):
    return await client.get(f"{WEB}/calendar", params={"date": (day or tomorrow()).isoformat()})


# phone_token theo SĐT (T-013 AC25–26): dùng lại trong hạn 30 phút, khỏi vướng giới hạn gửi mã
_phone_tokens: dict[str, str] = {}


async def phone_token(client, phone: str, *, required: bool = True) -> str | None:
    """Xác minh SĐT qua OTP chế độ thử -> ``phone_token`` (cache theo SĐT).

    ``required=False``: gửi mã bị từ chối (SĐT sai, đặt online tắt…) -> ``None`` để test
    kiểm lỗi của chính lệnh tạo lượt."""
    if phone not in _phone_tokens:
        r = await client.post(f"{WEB}/phone/request", json={"phone": phone})
        if not required and r.status_code != 202:
            return None
        assert r.status_code == 202, r.text
        r = await client.post(
            f"{WEB}/phone/verify", json={"phone": phone, "otp": r.json()["test_otp"]}
        )
        assert r.status_code == 200, r.text
        _phone_tokens[phone] = r.json()["phone_token"]
    return _phone_tokens[phone]


async def checkout(client, slots, day: date | None = None, phone=None, name="Khách Web", **extra):
    phone = phone or random_phone()
    body = {
        "date": (day or tomorrow()).isoformat(),
        "slots": [{"resource_code": c, "start_hour": h} for c, h in slots],
        "full_name": name,
        "phone": phone,
        **extra,
    }
    if "phone_token" not in body:
        body["phone_token"] = await phone_token(client, normalize_phone(phone), required=False)
    return await client.post(f"{WEB}/checkouts", json=body, headers=idem())


async def simulate(admin, pay_ref: str, amount: int):
    r = await admin.post(
        f"{PAY}/dev/simulate", json={"pay_ref": pay_ref, "amount": amount}, headers=idem()
    )
    assert r.status_code == 200, r.text
    return r.json()["outcome"]


def signed(payload: dict, secret: str = SEPAY_SECRET, ts: int | None = None):
    raw = json.dumps(payload).encode()
    stamp = str(ts if ts is not None else int(time.time()))
    sig = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {
        "Content-Type": "application/json",
        "X-SePay-Signature": f"sha256={sig}",
        "X-SePay-Timestamp": stamp,
    }


def sepay_payload(code: str | None, amount: int, **overrides) -> dict:
    return {
        "id": uuid.uuid4().int % 10**12,
        "gateway": "Vietcombank",
        "transactionDate": datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S"),
        "accountNumber": "0123456789",
        "code": code,
        "content": f"{code or ''} thanh toan san",
        "transferType": "in",
        "transferAmount": amount,
        "referenceCode": "FT123",
        **overrides,
    }


async def webhook(client, payload: dict, **sign_kwargs):
    raw, headers = signed(payload, **sign_kwargs)
    return await client.post(f"{PAY}/sepay/webhook", content=raw, headers=headers)

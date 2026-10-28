"""Helper dùng chung cho test web khách (T-008)."""

import hashlib
import hmac
import json
import time
import uuid
from datetime import date, timedelta

from tests.conftest import API, SEPAY_SECRET, idem
from tests.helpers_booking import random_phone, today

WEB = f"{API}/web/booking"
PAY = f"{API}/payments"


def tomorrow() -> date:
    return today() + timedelta(days=1)


async def web_calendar(client, day: date | None = None):
    return await client.get(f"{WEB}/calendar", params={"date": (day or tomorrow()).isoformat()})


async def checkout(client, slots, day: date | None = None, phone=None, name="Khách Web", **extra):
    body = {
        "date": (day or tomorrow()).isoformat(),
        "slots": [{"resource_code": c, "start_hour": h} for c, h in slots],
        "full_name": name,
        "phone": phone or random_phone(),
        **extra,
    }
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
        "transactionDate": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
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

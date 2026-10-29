"""QA acceptance tests for T-012 (owner-managed online payment settings).

Source of truth: board/tasks/T-012-cai-dat-thanh-toan.md (AC1-AC11, SEC1-SEC8).
Written from the spec BEFORE the BE handoff; every assumption sits in section 1.
UI-only criteria (AC1-AC7 page rendering, QR preview, password dialog, simulate block,
menu) are verified by hand (see qa/T-012-report.md).

ASSUMED CONTRACT (beyond the spec):
  * PUT /payments/settings returns 200 with the same body as GET
  * the server normalises the account holder name (upper case, no diacritics)
  * toggling online on with an incomplete configuration (no secret saved in the DB row) is
    refused with 422 E-PAY-4 "Chưa đủ thông tin để bật đặt online."
  * the wrong-password counter is per Admin account: 5 wrong answers (400 E-AUTH-7) lock saving
    for 15 minutes (further attempts, even with the right password, answer 429 E-SEC-5)
  * audit action ``payments.settings.update`` with a ``detail`` JSON (no secret, no full
    account number)
  * table payments.settings(webhook_secret_enc bytea, secret_last4, last_webhook_at, ...)
  * the webhook secret is still verified through ``X-SePay-Signature: sha256=<hex>`` over
    ``"{timestamp}.{raw_body}"`` (T-008)
The settings row is global (one per tenant): this module starts and ends with an empty table
(then waits for the <= 10 s config cache), so other test modules keep using the SEPAY_* env.
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from tests.conftest import API, ORIGIN, idem
from tests.helpers_web import phone_token

P = f"{API}/payments"
W = f"{API}/web/booking"
BK = f"{API}/booking"
SECRET = "qa-t012-webhook-secret-0123456789"
SECRET2 = "qa-t012-NEW-webhook-secret-9876543210"
ACCOUNT = "9704221234567"
CACHE_WAIT = 11  # config cache is <= 10 s


# ---------------------------------------------------------------------------
# 1. Contract helpers
# ---------------------------------------------------------------------------


def code_of(resp) -> str | None:
    try:
        detail = resp.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return None
    return detail.get("code") if isinstance(detail, dict) else None


def err(resp, status: int, code: str) -> None:
    assert resp.status_code == status, (status, code, resp.status_code, resp.text)
    assert code_of(resp) == code, (code, resp.text)


def body(**over) -> dict:
    base = {
        "bank_code": "VCB",
        "account_number": ACCOUNT,
        "account_name": "SAN CAU LONG QA",
        "online_toggle": True,
        "webhook_secret": SECRET,
        "current_password": settings.FIRST_ADMIN_PASSWORD,
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not ...}


async def put(client, payload: dict, *, key="auto"):
    headers = {}
    if key == "auto":
        headers = idem()
    elif key is not None:
        headers = {"Idempotency-Key": key}
    return await client.put(f"{P}/settings", json=payload, headers=headers)


async def configure(admin, **over) -> dict:
    r = await put(admin, body(**over))
    assert r.status_code == 200, r.text
    return r.json()


async def sql(query: str, **params):
    async with SessionLocal() as s:
        res = await s.execute(text(query), params)
        rows = res.mappings().all() if res.returns_rows else []
        await s.commit()
        return rows


@pytest.fixture(scope="module", autouse=True)
async def clean_table():
    """Empty table before and after the module (+ wait for the config cache to expire)."""
    await expire_all_pending()  # earlier modules leave pending checkouts that block account changes
    await sql("DELETE FROM payments.settings")
    await asyncio.sleep(CACHE_WAIT)
    yield
    await expire_all_pending()
    await sql("DELETE FROM payments.settings")
    await asyncio.sleep(CACHE_WAIT)


def sign(raw: bytes, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return {
        "X-SePay-Signature": f"sha256={mac}",
        "X-SePay-Timestamp": ts,
        "Content-Type": "application/json",
    }


def payload(account: str = ACCOUNT, pay_ref: str | None = None, amount: int = 1000) -> dict:
    return {
        "id": uuid.uuid4().int % 10**12,
        "gateway": "Vietcombank",
        "transactionDate": datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S"),
        "accountNumber": account,
        "code": pay_ref,
        "content": f"CK {pay_ref}" if pay_ref else "qa t012",
        "transferType": "in",
        "transferAmount": amount,
        "accumulated": 0,
        "referenceCode": "FT" + uuid.uuid4().hex[:10],
        "description": "",
    }


async def webhook(client, data: dict, secret: str):
    raw = json.dumps(data).encode()
    return await client.post(f"{P}/sepay/webhook", content=raw, headers=sign(raw, secret))


async def court(admin) -> dict:
    r = await admin.post(
        f"{BK}/resources",
        json={
            "name": f"QA t012 {uuid.uuid4().hex[:6]}",
            "resource_type_code": "thuong",
            "open_time": "00:00",
            "close_time": "24:00",
            "peak_bands": [],
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def web_checkout(anon, code: str, hour: int = 10):
    ph = "09" + str(uuid.uuid4().int)[:8]
    return await anon.post(
        f"{W}/checkouts",
        json={
            "date": (date.today() + timedelta(days=21)).isoformat(),
            "slots": [{"resource_code": code, "start_hour": hour}],
            "full_name": "QA T012",
            "phone": ph,
            "phone_token": await phone_token(anon, ph, required=False),
        },
        headers=idem(),
    )


async def expire_all_pending() -> None:
    from app.modules.booking_engine import api as engine_api

    await sql(
        "UPDATE booking.checkout SET expires_at = now() - interval '10 minutes' "
        "WHERE status='pending'"
    )
    await sql(
        "UPDATE booking.hold SET expires_at = now() - interval '10 minutes' WHERE status='active'"
    )
    async with SessionLocal() as s:
        await engine_api.expire_holds(s)
        await s.commit()


# ---------------------------------------------------------------------------
# 2. Permissions, shape, banks (AC1, AC3, AC9 shape, SEC1, SEC6)
# ---------------------------------------------------------------------------

ENDPOINTS = [
    ("GET", f"{P}/settings", None),
    ("PUT", f"{P}/settings", body()),
    ("GET", f"{P}/banks", None),
]


@pytest.mark.parametrize("idx", range(3))
async def test_sec1_admin_only(idx, anon, customer, staff, admin):
    method, path, data = ENDPOINTS[idx]
    for name, client, want in (
        ("anon", anon, 401),
        ("customer", customer, 403),
        ("staff", staff, 403),
    ):
        r = await client.request(method, path, json=data, headers=idem())
        assert r.status_code == want, (name, method, path, r.status_code, r.text)
        assert code_of(r) == ("E-AUTH-1" if want == 401 else "E-AUTH-2")
    if method == "GET":
        assert (await admin.request(method, path)).status_code == 200


async def test_sec6_foreign_origin_blocked(admin):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    cookies = dict(admin.cookies)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": "https://evil.example"},
        cookies=cookies,
    ) as evil:
        r = await put(evil, body(account_name="EVIL CHANGE"))
        assert r.status_code == 403 and code_of(r) == "E-SEC-1"
    got = (await admin.get(f"{P}/settings")).json()
    assert got["account_name"] != "EVIL CHANGE"


async def test_banks_list_shape(admin):
    r = await admin.get(f"{P}/banks")
    assert r.status_code == 200, r.text
    banks = (
        r.json()
        if isinstance(r.json(), list)
        else next(v for v in r.json().values() if isinstance(v, list))
    )
    assert len(banks) >= 20
    for b in banks:
        assert {"code", "short_name", "name"} <= set(b)
    codes = [b["code"] for b in banks]
    assert len(set(codes)) == len(codes) and "VCB" in codes


async def test_ac1_ac3_get_shape_and_webhook_url(admin):
    await configure(admin)
    d = (await admin.get(f"{P}/settings")).json()
    for k in (
        "bank_code",
        "bank_name",
        "account_number",
        "account_name",
        "online_toggle",
        "online_enabled",
        "missing",
        "secret_set",
        "secret_last4",
        "webhook_url",
        "pay_code_hint",
        "last_webhook_at",
        "updated_at",
        "updated_by_label",
        "pending_checkouts",
        "simulate_enabled",
    ):
        assert k in d, k
    assert d["online_enabled"] is True and d["missing"] == []
    assert d["secret_set"] is True and d["secret_last4"] == SECRET[-4:]
    assert d["webhook_url"].startswith("http") and d["webhook_url"].endswith(
        "/api/v1/payments/sepay/webhook"
    )
    assert "11" in d["pay_code_hint"] and "BK" in d["pay_code_hint"]
    assert d["updated_by_label"] == "Admin" and d["updated_at"]
    assert d["simulate_enabled"] is bool(settings.PAYMENTS_SIMULATE)
    assert d["bank_name"], "bank name is resolved from the fixed VietQR list"


# ---------------------------------------------------------------------------
# 3. Validation (AC2, AC4, E-PAY-4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "over",
    [
        {"bank_code": ""},
        {"bank_code": "NOTABANK"},
        {"bank_code": None},
        {"account_number": "12345"},
        {"account_number": "1" * 21},
        {"account_number": "12345abc90"},
        {"account_number": ""},
        {"account_name": "A"},
        {"account_name": "A" * 51},
        {"account_name": "NGUYEN 123"},
        {"account_name": ""},
        {"webhook_secret": "x" * 15},
        {"webhook_secret": "x" * 129},
    ],
)
async def test_e_pay_4_field_validation(admin, over):
    await configure(admin)
    before = (await admin.get(f"{P}/settings")).json()
    r = await put(admin, body(**over))
    assert r.status_code == 422, (over, r.status_code, r.text)
    assert (await admin.get(f"{P}/settings")).json()["updated_at"] == before["updated_at"], (
        "nothing saved"
    )


async def test_forbidden_and_missing_fields(admin):
    await configure(admin)
    for extra in ({"tenant_id": 2}, {"secret_last4": "0000"}, {"online_enabled": True}):
        r = await put(admin, {**body(), **extra})
        assert r.status_code == 422, (extra, r.text)
    no_pw = body()
    no_pw.pop("current_password")
    assert (await put(admin, no_pw)).status_code == 422


async def test_ac2_account_name_is_normalised(admin):
    d = await configure(admin, account_name="  Nguyễn  Văn Đạt  ")
    assert d["account_name"] == "NGUYEN VAN DAT"
    d = await configure(admin, account_name="san cau long")
    assert d["account_name"] == "SAN CAU LONG"


async def test_ac4_cannot_enable_without_secret_and_data(admin):
    await sql("DELETE FROM payments.settings")
    await asyncio.sleep(CACHE_WAIT)
    r = await put(admin, body(webhook_secret=...))  # no secret saved yet
    err(r, 422, "E-PAY-4")
    assert "bật đặt online" in r.json()["detail"]["message"]
    d = await configure(admin, online_toggle=False, webhook_secret=...)
    assert d["online_enabled"] is False and "webhook_secret" in d["missing"]
    assert d["secret_set"] is False and d["secret_last4"] in (None, "")
    ok = await configure(admin)  # secret provided -> can enable
    assert ok["online_enabled"] is True and ok["missing"] == []


async def test_ac4_toggle_off_disables_public_booking(admin, anon):
    await configure(admin)
    assert (
        await anon.get(
            f"{W}/calendar", params={"date": (date.today() + timedelta(days=3)).isoformat()}
        )
    ).json()["online_enabled"] is True
    await configure(admin, online_toggle=False, webhook_secret=...)
    cal = (
        await anon.get(
            f"{W}/calendar", params={"date": (date.today() + timedelta(days=3)).isoformat()}
        )
    ).json()
    assert cal["online_enabled"] is False
    c = await court(admin)
    err(await web_checkout(anon, c["code"]), 503, "E-WEB-5")
    await configure(admin)  # back on
    assert (await web_checkout(anon, c["code"])).status_code == 201


async def test_keep_secret_when_omitted_and_replace_when_given(admin):
    await configure(admin)
    d = await configure(admin, webhook_secret=...)
    assert d["secret_set"] is True and d["secret_last4"] == SECRET[-4:], "omitted -> unchanged"
    d = await configure(admin, webhook_secret=None)
    assert d["secret_last4"] == SECRET[-4:], "null -> unchanged"
    d = await configure(admin, webhook_secret=SECRET2)
    assert d["secret_last4"] == SECRET2[-4:]
    await configure(admin)


# ---------------------------------------------------------------------------
# 4. Password confirmation (AC5, SEC3, SEC4)
# ---------------------------------------------------------------------------


async def test_ac5_sec3_wrong_or_missing_password_changes_nothing(admin):
    await configure(admin)
    before = (await admin.get(f"{P}/settings")).json()
    for pw in ("", "wrong-password", settings.FIRST_ADMIN_PASSWORD + "x"):
        r = await put(admin, body(account_name="HACKED NAME", current_password=pw))
        assert r.status_code in (400, 422), (pw, r.status_code, r.text)
        if r.status_code == 400:
            assert (
                code_of(r) == "E-AUTH-7" and "Mật khẩu không đúng" in r.json()["detail"]["message"]
            )
    after = (await admin.get(f"{P}/settings")).json()
    assert (
        after["account_name"] == before["account_name"]
        and after["updated_at"] == before["updated_at"]
    )


async def test_sec4_five_wrong_passwords_lock_saving(admin):
    await configure(admin)
    codes = []
    for _ in range(5):
        r = await put(admin, body(current_password="definitely-wrong"))
        codes.append(r.status_code)
    assert codes[:4] == [400] * 4 and codes[4] in (400, 429), codes
    locked = await put(admin, body(account_name="AFTER LOCK"))  # right password, still locked
    err(locked, 429, "E-SEC-5")
    assert (await admin.get(f"{P}/settings")).json()["account_name"] != "AFTER LOCK"


async def test_idempotent_put_and_missing_key(admin):
    k = str(uuid.uuid4())
    a = await put(admin, body(account_name="IDEM NAME"), key=k)
    b = await put(admin, body(account_name="IDEM NAME"), key=k)
    assert (
        a.status_code == b.status_code == 200 and a.json()["updated_at"] == b.json()["updated_at"]
    )
    assert (await put(admin, body(), key=None)).status_code == 400
    c = await put(admin, body(account_name="OTHER BODY"), key=k)
    assert c.status_code == 422, "same key with another body"
    await configure(admin)


# ---------------------------------------------------------------------------
# 5. Pending checkouts block account change (AC6, SEC5)
# ---------------------------------------------------------------------------


async def test_ac6_sec5_account_change_blocked_while_checkout_pending(admin, anon):
    await expire_all_pending()
    await configure(admin)
    c = await court(admin)
    co = await web_checkout(anon, c["code"])
    assert co.status_code == 201, co.text
    assert co.json()["bank"]["account_number"] == ACCOUNT, "QR comes from the DB settings"
    assert (await admin.get(f"{P}/settings")).json()["pending_checkouts"] >= 1
    r = await put(admin, body(account_number="9704220000001"))
    err(r, 409, "E-PAY-3")
    assert "lượt chờ thanh toán" in r.json()["detail"]["message"]
    r = await put(admin, body(bank_code="ACB"))
    err(r, 409, "E-PAY-3")
    assert (await admin.get(f"{P}/settings")).json()["account_number"] == ACCOUNT
    # name, secret and the switch are allowed meanwhile
    assert (await put(admin, body(account_name="TEN MOI KHAC"))).status_code == 200
    assert (await put(admin, body(webhook_secret=SECRET2))).status_code == 200
    assert (await put(admin, body(online_toggle=False))).status_code == 200
    # after the checkout expires the account can be changed
    await expire_all_pending()
    ok = await put(admin, body(account_number="9704220000001", bank_code="ACB"))
    assert ok.status_code == 200, ok.text
    assert ok.json()["account_number"] == "9704220000001" and ok.json()["bank_code"] == "ACB"
    await configure(admin)


# ---------------------------------------------------------------------------
# 6. Backend reads the DB config (AC8, AC10, SEC8)
# ---------------------------------------------------------------------------


async def test_ac8_qr_and_account_filter_use_db_config(admin, anon):
    await expire_all_pending()
    await configure(admin, account_number=ACCOUNT)
    c = await court(admin)
    co = (await web_checkout(anon, c["code"])).json()
    assert co["bank"]["account_number"] == ACCOUNT and f"acc={ACCOUNT}" in co["bank"]["qr_url"]
    # a transfer into another account is ignored, into the configured one it is processed
    other = payload(account="0123456789", pay_ref=co["pay_ref"], amount=co["amount"])
    assert (await webhook(anon, other, SECRET)).status_code == 200
    row = await sql(
        "SELECT outcome FROM payments.bank_transaction WHERE provider_txn_id=:i", i=str(other["id"])
    )
    assert row[0]["outcome"] == "ignored"
    mine = payload(account=ACCOUNT, pay_ref=co["pay_ref"], amount=co["amount"])
    assert (await webhook(anon, mine, SECRET)).status_code == 200
    row = await sql(
        "SELECT outcome FROM payments.bank_transaction WHERE provider_txn_id=:i", i=str(mine["id"])
    )
    assert row[0]["outcome"] == "applied"


async def test_ac8_empty_db_falls_back_to_env(admin, anon):
    await sql("DELETE FROM payments.settings")
    await asyncio.sleep(CACHE_WAIT)
    d = (await admin.get(f"{P}/settings")).json()
    if settings.SEPAY_ACCOUNT_NUMBER:  # conftest supplies fake SEPAY_* for the whole test session
        assert d["account_number"] == settings.SEPAY_ACCOUNT_NUMBER
        assert d["online_enabled"] is True
        cal = (
            await anon.get(
                f"{W}/calendar", params={"date": (date.today() + timedelta(days=3)).isoformat()}
            )
        ).json()
        assert cal["online_enabled"] is True
    await configure(admin)


async def test_ac10_last_webhook_at_only_for_valid_signature(admin, anon):
    await configure(admin)
    t0 = (await admin.get(f"{P}/settings")).json()["last_webhook_at"]
    bad = payload()
    raw = json.dumps(bad).encode()
    assert (
        await anon.post(
            f"{P}/sepay/webhook", content=raw, headers=sign(raw, "wrong-secret-0123456789")
        )
    ).status_code == 401
    assert (await admin.get(f"{P}/settings")).json()["last_webhook_at"] == t0, (
        "rejected request leaves it alone"
    )
    await asyncio.sleep(1.1)
    assert (
        await webhook(anon, payload(), SECRET)
    ).status_code == 200  # unmatched but signed: counts
    t1 = (await admin.get(f"{P}/settings")).json()["last_webhook_at"]
    assert t1 and t1 != t0
    assert datetime.fromisoformat(t1) <= datetime.now(settings.tz) + timedelta(seconds=5)


async def test_sec8_old_secret_rejected_new_secret_accepted(admin, anon):
    await configure(admin, webhook_secret=SECRET)
    assert (await webhook(anon, payload(), SECRET)).status_code == 200
    await configure(admin, webhook_secret=SECRET2)
    assert (await webhook(anon, payload(), SECRET)).status_code == 401, "old key no longer valid"
    assert (await webhook(anon, payload(), SECRET2)).status_code == 200
    await configure(admin)


async def test_no_secret_means_webhook_503(admin, anon):
    await sql("DELETE FROM payments.settings")
    await asyncio.sleep(CACHE_WAIT)
    await configure(admin, online_toggle=False, webhook_secret=...)
    if not settings.SEPAY_WEBHOOK_SECRET:
        raw = json.dumps(payload()).encode()
        r = await anon.post(f"{P}/sepay/webhook", content=raw, headers=sign(raw, SECRET))
        assert r.status_code == 503
    await configure(admin)


# ---------------------------------------------------------------------------
# 7. Secret handling and audit (AC9, AC11, SEC2)
# ---------------------------------------------------------------------------


async def test_sec2_secret_never_returned_logged_or_stored_in_plain(admin, anon, caplog):
    with caplog.at_level("DEBUG"):
        put_resp = await put(admin, body(webhook_secret=SECRET2))
        get_resp = await admin.get(f"{P}/settings")
        bad = await put(admin, body(webhook_secret="short"))
        await webhook(anon, payload(), SECRET2)
    assert put_resp.status_code == 200
    for r in (put_resp, get_resp, bad):
        assert SECRET2 not in r.text, "secret leaked in a response"
    assert SECRET2 not in caplog.text and settings.FIRST_ADMIN_PASSWORD not in caplog.text
    rows = await sql("SELECT webhook_secret_enc, secret_last4 FROM payments.settings")
    enc = bytes(rows[0]["webhook_secret_enc"])
    assert SECRET2.encode() not in enc and SECRET2[-8:].encode() not in enc, "stored encrypted"
    assert rows[0]["secret_last4"] == SECRET2[-4:]
    dump = await sql("SELECT row_to_json(t)::text AS j FROM payments.settings t")
    assert SECRET2 not in dump[0]["j"]
    audit = await sql(
        "SELECT detail::text AS d FROM audit_log WHERE action='payments.settings.update'"
    )
    assert audit and all(SECRET2 not in a["d"] and SECRET not in a["d"] for a in audit)
    await configure(admin)


async def test_ac11_audit_row_for_each_successful_save_only(admin):
    await configure(admin, account_number=ACCOUNT)
    n0 = len(await sql("SELECT 1 FROM audit_log WHERE action='payments.settings.update'"))
    rejected = await put(admin, body(current_password="nope-nope"))
    assert rejected.status_code == 400
    bad_input = await put(admin, body(account_number="1"))
    assert bad_input.status_code == 422
    assert len(await sql("SELECT 1 FROM audit_log WHERE action='payments.settings.update'")) == n0
    new_account = "9704229999888"
    ok = await put(
        admin,
        body(account_number=new_account, account_name="DOI TEN AUDIT", webhook_secret=SECRET2),
    )
    assert ok.status_code == 200, ok.text
    rows = await sql(
        "SELECT actor_label, detail::text AS d FROM audit_log "
        "WHERE action='payments.settings.update' ORDER BY id DESC LIMIT 1"
    )
    assert (
        len(await sql("SELECT 1 FROM audit_log WHERE action='payments.settings.update'")) == n0 + 1
    )
    d = rows[0]["d"]
    assert rows[0]["actor_label"] == "Admin"
    assert ACCOUNT[-4:] in d and new_account[-4:] in d, "last 4 digits old -> new"
    assert ACCOUNT not in d and new_account not in d, "never the full account number"
    assert SECRET2 not in d and SECRET not in d
    assert "DOI TEN AUDIT" in d or "account_name" in d
    await configure(admin)


async def test_ac9_encryption_key_required_outside_development():
    cls = type(settings)
    base = {"_env_file": None, "SECRET_KEY": "x" * 40}
    cls(**base, ENV="development", PAYMENTS_ENCRYPTION_KEY=None)  # temporary key + warning
    good_key = "0" * 43 + "="  # 32 bytes url-safe base64
    cls(**base, ENV="staging", PAYMENTS_ENCRYPTION_KEY=good_key)
    for env in ("staging", "production"):
        with pytest.raises(
            ValueError, match="(?i)PAYMENTS_ENCRYPTION_KEY"
        ):  # pydantic ValidationError
            cls(**base, ENV=env, PAYMENTS_ENCRYPTION_KEY=None)


# ---------------------------------------------------------------------------
# 8. Simulate block (AC7, SEC7)
# ---------------------------------------------------------------------------


async def test_ac7_sec7_simulate_flag_is_reported_and_enforced(admin, anon):
    await configure(admin)
    flag = bool(settings.PAYMENTS_SIMULATE)
    assert (await admin.get(f"{P}/settings")).json()["simulate_enabled"] is flag
    old = settings.PAYMENTS_SIMULATE
    try:
        object.__setattr__(settings, "PAYMENTS_SIMULATE", False)
        assert (await admin.get(f"{P}/settings")).json()["simulate_enabled"] is False
        r = await admin.post(
            f"{P}/dev/simulate", json={"pay_ref": "BK00000000000", "amount": 1}, headers=idem()
        )
        assert r.status_code == 404
    finally:
        object.__setattr__(settings, "PAYMENTS_SIMULATE", old)
    c = await court(admin)
    co = (await web_checkout(anon, c["code"])).json()
    sim = await admin.post(
        f"{P}/dev/simulate", json={"pay_ref": co["pay_ref"], "amount": co["amount"]}, headers=idem()
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["outcome"] == "applied"

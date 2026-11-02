"""T-008: lịch khách, lượt thanh toán (giữ chỗ 5 phút), xem trạng thái."""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine.models import Checkout
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, calendar, new_court, random_phone, safe_hour, today
from tests.helpers_web import WEB, checkout, phone_token, tomorrow, web_calendar

# ------------------------------------------------------------------ lịch (AC1–AC2, SEC1)


async def test_public_calendar_states_and_prices(anon, admin, staff):
    court = await new_court(admin, open_time="06:00", close_time="22:00")
    day = tomorrow()
    # Sự kiện 9–11h, booking quầy không đặt được ngày mai -> dùng giữ chỗ online cho ô 12h
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": day.isoformat(),
            "start_hour": 9,
            "end_hour": 11,
            "name": "Giao lưu",
            "capacity": 8,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    event_code = r.json()["code"]
    held = await checkout(anon, [(court["code"], 12)], name="Bí Mật Người Khác")
    assert held.status_code == 201

    r = await web_calendar(anon, day)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    cal = r.json()
    assert cal["online_enabled"] is True and cal["hold_minutes"] == 5
    assert cal["server_now"]
    row = next(x for x in cal["resources"] if x["code"] == court["code"])
    slots = {s["start_hour"]: s for s in row["slots"]}
    assert [s["start_hour"] for s in row["slots"]] == cal["columns"]
    assert slots[5]["state"] == "closed" if 5 in slots else True
    assert slots[9] == {
        "start_hour": 9,
        "state": "event",
        "price": None,
        "band": None,
        "taken": 0,
        "capacity": 8,
        "event_code": event_code,  # T-023: mở popup sự kiện / mua vé
    }
    assert slots[12]["state"] == "booked" and slots[12]["price"] is None
    assert slots[13]["state"] == "free" and slots[13]["price"] > 0 and slots[13]["band"]
    # Không lộ tên / SĐT / mã của người khác; sân ngừng không hiện
    assert "Bí Mật" not in r.text and held.json()["order_code"] not in r.text
    assert r.text.count("BK-") == r.text.count(event_code)  # mã duy nhất: mã sự kiện
    assert "S06" not in [x["code"] for x in cal["resources"]]


async def test_public_calendar_today_past_and_far_future(anon):
    r = await web_calendar(anon, today() - timedelta(days=1))
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "E-WEB-2",
        "message": "Không đặt được ngày đã qua.",
    }
    far = await web_calendar(anon, today() + timedelta(days=200))  # không giới hạn ngày tới
    assert far.status_code == 200
    now_hour = datetime.now(settings.tz).hour
    cal = (await web_calendar(anon, today())).json()
    for row in cal["resources"]:
        for s in row["slots"]:
            if s["start_hour"] <= now_hour:
                assert s["state"] != "free"  # khung đã bắt đầu / đã qua -> không bán


# ------------------------------------------------------------------ tạo lượt thanh toán (AC10–AC13)


async def test_create_checkout_groups_ranges_and_prices(anon, admin, staff):
    a, b = await new_court(admin), await new_court(admin)
    day = tomorrow()
    phone = random_phone()
    r = await checkout(
        anon,
        [(b["code"], 8), (a["code"], 20), (a["code"], 19), (a["code"], 19)],
        phone=f"+84 {phone[1:4]}.{phone[4:]}",
        name="  Phạm   Quang Minh ",
        note="cần mượn vợt",
    )
    assert r.status_code == 201, r.text
    co = r.json()
    assert len(co["token"]) == 43 and re.fullmatch(r"[A-Za-z0-9_-]+", co["token"])
    assert co["status"] == "pending" and co["paid_amount"] == 0 and co["paid_at"] is None
    items = co["items"]
    assert [(i["resource_code"], i["start_time"], i["end_time"], i["hours"]) for i in items] == [
        (a["code"], "19:00", "21:00", 2),
        (b["code"], "08:00", "09:00", 1),
    ]
    codes = [i["code"] for i in items]
    # Một mã đơn cho cả lượt, khối mang mã con -01, -02 theo sân rồi giờ (T-019)
    assert re.fullmatch(rf"BK-{day:%Y%m%d}-\d{{3}}", co["order_code"])
    assert codes == [f"{co['order_code']}-01", f"{co['order_code']}-02"]
    assert co["pay_ref"] == co["order_code"].replace("-", "")
    assert co["amount"] == sum(i["amount"] for i in items)
    quote = await staff.post(
        f"{BK}/quote",
        json={
            "resource_code": a["code"],
            "date": day.isoformat(),
            "start_hour": 19,
            "end_hour": 21,
        },
    )
    assert items[0]["amount"] == quote.json()["total_amount"]
    assert co["customer"] == {"full_name": "Phạm Quang Minh", "phone_masked": mask(phone)}
    bank = co["bank"]
    assert bank["account_number"] == "0123456789" and bank["bank_name"] == "Vietcombank"
    assert f"amount={co['amount']}" in bank["qr_url"] and f"des={co['pay_ref']}" in bank["qr_url"]
    expires = datetime.fromisoformat(co["expires_at"])
    now = datetime.fromisoformat(co["server_now"])
    assert timedelta(minutes=4, seconds=50) < expires - now <= timedelta(minutes=5)
    assert phone not in r.text

    # Lịch khách: ô đã giữ -> Đỏ; lịch quầy: khối giữ chỗ (viền đứt) không tên
    cal = (await web_calendar(anon, day)).json()
    row = next(x for x in cal["resources"] if x["code"] == a["code"])
    assert {s["start_hour"]: s["state"] for s in row["slots"]}[19] == "booked"
    admin_cal = await calendar(staff, day)
    holds = [x for x in admin_cal["blocks"] if a["code"] in x["resource_codes"]]
    assert [(h["type"], h["start_hour"], h["end_hour"]) for h in holds] == [("hold", 19, 21)]

    # DB chỉ có hash của token
    async with SessionLocal() as s:
        row = await s.scalar(select(Checkout).where(Checkout.pay_ref == co["pay_ref"]))
    assert row.token_hash == hashlib.sha256(co["token"].encode()).digest()
    assert row.customer_kind == "temp" and row.note == "cần mượn vợt"


def mask(phone: str) -> str:
    return f"{phone[:4]} xxx {phone[-3:]}"


async def test_checkout_member_snapshot(anon, admin):
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 10)], phone="0934 567 019", name="Tên Khác")
    assert r.status_code == 201, r.text
    assert r.json()["customer"]["full_name"] == "Phạm Văn Nam"  # hồ sơ hội viên HV0031
    async with SessionLocal() as s:
        row = await s.scalar(select(Checkout).where(Checkout.pay_ref == r.json()["pay_ref"]))
    assert (row.customer_kind, row.member_code) == ("member", "HV0031")


async def test_checkout_validation(anon, admin, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)  # nhiều lần gửi trong một test
    court = await new_court(admin, open_time="06:00", close_time="22:00")
    code = court["code"]
    cases = [
        (dict(slots=[]), "E-WEB-1", "Chọn ít nhất 1 khung giờ."),
        (dict(slots=[(code, h) for h in range(6, 22)] + [("S01", 6)]), "E-WEB-1",
         "Mỗi lần đặt tối đa 16 khung giờ."),
        (dict(slots=[(code, 10)], name="   "), "E-WEB-1", "Vui lòng nhập họ tên."),
        (dict(slots=[(code, 10)], phone="12345"), "E-WEB-1",
         "Số điện thoại không hợp lệ — cần đủ 10 số."),
        (dict(slots=[(code, 10)], note="x" * 201), "E-WEB-1", "Ghi chú tối đa 200 ký tự."),
        (dict(slots=[(code, 5)]), "E-WEB-2", None),  # ngoài giờ mở cửa
        (dict(slots=[("S06", 10)]), "E-WEB-2", None),  # sân ngừng
        (dict(slots=[("ZZ9", 10)]), "E-WEB-2", None),  # sân không có
        (dict(slots=[(code, 10)], day=today() - timedelta(days=1)), "E-WEB-2", None),
    ]  # fmt: skip
    for kwargs, err, message in cases:
        r = await checkout(anon, **kwargs)
        assert r.status_code == 422, (kwargs, r.text)
        assert r.json()["detail"]["code"] == err
        if message:
            assert r.json()["detail"]["message"] == message
    r = await checkout(anon, [(code, 10)], day=today(), phone=random_phone())
    if datetime.now(settings.tz).hour >= 10:
        assert r.json()["detail"]["code"] == "E-WEB-2"  # khung đã bắt đầu
    # Trường do server quyết -> 422
    for extra in ({"amount": 1}, {"price": 1}, {"token": "x"}):
        r = await checkout(anon, [(code, 15)], **extra)
        assert r.status_code == 422


async def test_checkout_requires_origin_and_idempotency(anon, admin):
    court = await new_court(admin)
    body = {
        "date": tomorrow().isoformat(),
        "slots": [{"resource_code": court["code"], "start_hour": 9}],
        "full_name": "A",
        "phone": random_phone(),
    }
    body["phone_token"] = await phone_token(anon, body["phone"])
    anon.headers.pop("Origin")
    r = await anon.post(f"{WEB}/checkouts", json=body, headers=idem())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-SEC-1"
    headers = {**idem(), "Origin": "http://testserver"}
    r = await anon.post(f"{WEB}/checkouts", json=body)
    assert r.status_code in (400, 403)
    r1 = await anon.post(f"{WEB}/checkouts", json=body, headers=headers)
    r2 = await anon.post(f"{WEB}/checkouts", json=body, headers=headers)
    assert r1.status_code == r2.status_code == 201
    assert r2.json() == r1.json() and r2.headers.get("idempotent-replayed") == "true"


async def test_checkout_conflict_and_pending_phone(anon, admin):
    court = await new_court(admin)
    code = court["code"]
    assert (await checkout(anon, [(code, 9), (code, 10)])).status_code == 201
    r = await checkout(anon, [(code, 8), (code, 10), (code, 11)])
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-WEB-3",
        "message": "Khung giờ vừa có người đặt. Vui lòng chọn khung khác.",
        "conflicts": [{"resource_code": code, "start_hour": 10}],
    }
    phone = random_phone()
    assert (await checkout(anon, [(code, 14)], phone=phone)).status_code == 201
    r = await checkout(anon, [(code, 15)], phone=phone)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-WEB-4"


async def test_checkout_race_one_wins(anon, admin):
    court = await new_court(admin)
    results = await asyncio.gather(*(checkout(anon, [(court["code"], 18)]) for _ in range(2)))
    assert sorted(r.status_code for r in results) == [201, 409]


async def test_checkout_counter_booking_blocks_today(anon, admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    if hour >= 23:
        return
    assert (await book(staff, court["code"], hour + 1)).status_code == 201
    r = await checkout(anon, [(court["code"], hour + 1)], day=today())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-WEB-3"


async def test_online_disabled(anon, admin, monkeypatch):
    court = await new_court(admin)
    monkeypatch.setattr(settings, "SEPAY_WEBHOOK_SECRET", "")
    cal = (await web_calendar(anon)).json()
    assert cal["online_enabled"] is False
    r = await checkout(anon, [(court["code"], 9)])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "E-WEB-5"


async def test_checkout_rate_limit(anon, admin):
    court = await new_court(admin)
    for h in range(8, 14):
        assert (await checkout(anon, [(court["code"], h)])).status_code == 201
    r = await checkout(anon, [(court["code"], 15)])
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"


# ------------------------------------------------------------------ xem trạng thái (AC15–AC18)


async def test_get_checkout_by_token(anon, admin):
    court = await new_court(admin)
    co = (await checkout(anon, [(court["code"], 9)])).json()
    r = await anon.get(f"{WEB}/checkouts/{co['token']}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    view = r.json()
    assert "token" not in view
    assert view["pay_ref"] == co["pay_ref"] and view["bank"]["qr_url"] == co["bank"]["qr_url"]
    for bad in ("x" * 43, "abc", co["token"][:-1] + ("A" if co["token"][-1] != "A" else "B")):
        r = await anon.get(f"{WEB}/checkouts/{bad}")
        assert r.status_code == 404 and r.json()["detail"] == {
            "code": "E-WEB-6",
            "message": "Không tìm thấy lượt thanh toán.",
        }
    assert (await anon.get(f"{API}/web/booking/checkouts/" + "y" * 101)).status_code in (404, 422)

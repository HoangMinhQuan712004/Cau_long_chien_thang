# ruff: noqa: E501, F811
"""QA T-023: bấm ô lưới hội viên, mua vé sự kiện online QR (khách + hội viên), tra cứu vé. AC1–AC15, AC17–AC22.

Viết từ spec `T-023-o-lich-hoi-vien-mua-ve-online.md` (+ sửa đổi 02/11 b), độc lập với `test_ticket_online.py` của BACKEND.
Giao diện (AC1 màu ô, AC2 popup, AC3 toast, AC15, AC17, AC18, AC20 trang) kiểm riêng bằng trình duyệt.
Tiền về: `POST /payments/dev/simulate` (giả lập như T-008). Mỗi test một sân/sự kiện riêng; hội viên có tài khoản = đăng ký OTP 2 bước (T-021).
"""

import asyncio
import re
import uuid

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.modules.booking_engine.api import expire_holds
from tests.conftest import API, idem
from tests.helpers_booking import BK, new_court, random_phone, safe_hour, today
from tests.helpers_web import WEB, checkout, phone_token, simulate, tomorrow
from tests.qa_tickets import (  # noqa: F401
    FD,
    LOOKUP,
    buy,
    code_of,
    info,
    mk_event,
    q,
    tickets_of,
    today_event,
)
from tests.test_online_payments import drain_outbox, shift_expiry

# ============================================================ AC5 / AC7 / AC17: chi tiết sự kiện công khai, can_buy + reason


async def test_ac5_public_event_info_has_no_buyer_data_and_no_my_tickets_for_guests(anon, admin):
    ev = await mk_event(admin, capacity=12, price=70_000, name="QA Giao lưu cuối tuần")
    r = await info(anon, ev["code"])
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    d = r.json()
    assert (d["code"], d["name"], d["ticket_price"], d["capacity"], d["taken"]) == (
        ev["code"],
        "QA Giao lưu cuối tuần",
        70_000,
        12,
        0,
    )
    assert d["play_date"] == tomorrow().isoformat() and (d["start_time"], d["end_time"]) == (
        "09:00",
        "11:00",
    )
    assert (
        d["resource_names"] == [ev["court"]["name"]]
        and d["can_buy"] is True
        and d["reason"] is None
    )
    assert d["max_seats"] == 10 and d["my_tickets"] is None and d["hold_minutes"] == 5
    phone = random_phone()
    assert (
        await buy(anon, ev["code"], 2, phone=phone, name="Người Mua Kín Tên")
    ).status_code == 201
    r2 = await info(anon, ev["code"])
    assert r2.json()["taken"] == 2, "ghế đang giữ online tính vào taken"
    assert "Người Mua" not in r2.text and phone not in r2.text and phone[1:] not in r2.text
    assert (await info(anon, "BK-20000101-999")).status_code == 404 and code_of(
        await info(anon, "BK-20000101-999")
    ) == "E-NOT-FOUND"
    assert (await info(anon, "x" * 80)).status_code in (404, 422)


async def test_ac7_max_seats_is_min_remaining_and_10(admin, anon):
    ev = await mk_event(admin, capacity=3)
    assert (await info(anon, ev["code"])).json()["max_seats"] == 3
    assert (await buy(anon, ev["code"], 2)).status_code == 201
    d = (await info(anon, ev["code"])).json()
    assert d["max_seats"] == 1 and d["can_buy"] is True
    assert (await buy(anon, ev["code"], 1)).status_code == 201
    d = (await info(anon, ev["code"])).json()
    assert d["can_buy"] is False and d["reason"] == "full" and d["max_seats"] == 0


async def test_ac17_cannot_buy_reasons_free_started_deleted(admin, anon):
    free = await mk_event(admin, price=0)
    d = (await info(anon, free["code"])).json()
    assert d["can_buy"] is False and d["reason"] == "free" and d["max_seats"] == 0
    r = await buy(anon, free["code"], 1)
    assert (
        r.status_code == 409
        and code_of(r) == "E-WEB-11"
        and "tại quầy" in r.json()["detail"]["message"]
    )
    # đã bắt đầu: sự kiện ở khung giờ đang diễn ra hôm nay
    h = await safe_hour()
    started = await mk_event(admin, day=today(), hours=(h, min(h + 1, 24)) if h < 24 else (23, 24))
    d = (await info(anon, started["code"])).json()
    assert d["can_buy"] is False and d["reason"] == "started"
    r = await buy(anon, started["code"], 1)
    assert (
        r.status_code == 409
        and code_of(r) == "E-WEB-9"
        and "đã bắt đầu" in r.json()["detail"]["message"]
    )
    # đã hủy
    gone = await mk_event(admin)
    assert (
        await admin.request(
            "DELETE",
            f"{BK}/sessions/{gone['code']}",
            json={"version": gone["version"]},
            headers=idem(),
        )
    ).status_code == 200
    r = await buy(anon, gone["code"], 1)
    assert (
        r.status_code == 409
        and code_of(r) == "E-WEB-9"
        and r.json()["detail"]["message"] == "Sự kiện đã bị hủy."
    )
    assert (await info(anon, gone["code"])).json()["reason"] == "deleted"


async def test_ac7_seat_count_validation(admin, anon):
    ev = await mk_event(admin, capacity=20)
    for bad in (0, 11):
        r = await buy(anon, ev["code"], bad)
        assert r.status_code == 422 and code_of(r) == "E-WEB-1", bad
    for bad in (1.5, None):
        phone = random_phone()
        body = {
            "event_code": ev["code"],
            "seats": bad,
            "full_name": "Khách",
            "phone": phone,
            "phone_token": await phone_token(anon, phone),
        }
        assert (
            await anon.post(f"{WEB}/event-checkouts", json=body, headers=idem())
        ).status_code == 422, bad
    assert (await buy(anon, ev["code"], 10)).status_code == 201, "10 vé là tối đa hợp lệ"
    assert (await info(anon, ev["code"])).json()["taken"] == 10


async def test_ac7_negative_seats_empty_fields_and_unknown_fields_are_rejected(admin, anon):
    ev = await mk_event(admin, capacity=20)
    r = await buy(anon, ev["code"], -1)
    assert r.status_code == 422 and code_of(r) == "E-WEB-1"
    for field in ("full_name", "phone"):
        phone = random_phone()
        body = {
            "event_code": ev["code"],
            "seats": 1,
            "full_name": "Khách",
            "phone": phone,
            "phone_token": await phone_token(anon, phone),
            field: "",
        }
        r = await anon.post(f"{WEB}/event-checkouts", json=body, headers=idem())
        assert r.status_code == 422 and code_of(r) == "E-WEB-1", field
    extra = {
        "event_code": ev["code"],
        "seats": 1,
        "full_name": "K",
        "phone": random_phone(),
        "price": 1,
    }
    assert (
        await anon.post(f"{WEB}/event-checkouts", json=extra, headers=idem())
    ).status_code == 422, "trường lạ không được nhận (không đặt được giá)"
    assert (await info(anon, ev["code"])).json()["taken"] == 0


# ============================================================ AC8 tạo lượt mua


async def test_ac8_checkout_for_tickets_amount_code_expiry_and_no_court_data(admin, anon):
    ev = await mk_event(admin, capacity=5, price=60_000)
    phone = random_phone()
    r = await buy(anon, ev["code"], 3, phone=phone, name="Lê Văn Vé")
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["kind"] == "ticket" and co["status"] == "pending" and co["amount"] == 180_000, (
        "3 × 60.000, chốt lúc giữ chỗ"
    )
    assert re.fullmatch(rf"BK-{tomorrow():%Y%m%d}-\d{{3}}", co["order_code"]), (
        "mã đơn theo ngày diễn ra sự kiện"
    )
    assert co["pay_ref"] == co["order_code"].replace("-", "")
    assert co["items"] == [] and co["event"]["seats"] == 3 and co["event"]["ticket_codes"] == []
    assert co["event"]["name"] == ev["name"] and co["event"]["ticket_price"] == 60_000
    assert phone not in r.text, "không trả SĐT đầy đủ"
    # đổi giá sự kiện (nếu có) không ảnh hưởng: số tiền đã chốt trong lượt
    got = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert got["kind"] == "ticket" and got["amount"] == 180_000 and got["event"]["seats"] == 3
    exp = (
        await q(
            "SELECT extract(epoch FROM (expires_at - created_at)) AS s FROM booking.checkout WHERE pay_ref=:p",
            p=co["pay_ref"],
        )
    )[0]["s"]
    assert 300 <= exp <= 360, f"giữ 5 phút (+≤60 s ân hạn), thực tế {exp}"
    # mã đơn không dùng lại, cùng dãy với booking/sự kiện
    r2 = await buy(anon, ev["code"], 1)
    assert r2.json()["order_code"] != co["order_code"]
    codes = {
        x["code"]
        for x in await q(
            "SELECT code FROM booking.session WHERE code LIKE :d", d=f"BK-{tomorrow():%Y%m%d}-%"
        )
    }
    assert co["order_code"] not in codes and r2.json()["order_code"] not in codes, (
        "không trùng mã sự kiện / booking"
    )


async def test_ac8_idempotent_replay_and_required_headers(admin, anon):
    ev = await mk_event(admin)
    phone = random_phone()
    body = {
        "event_code": ev["code"],
        "seats": 1,
        "full_name": "Khách Lặp",
        "phone": phone,
        "phone_token": await phone_token(anon, phone),
        "as_member": False,
    }
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r1 = await anon.post(f"{WEB}/event-checkouts", json=body, headers=key)
    r2 = await anon.post(f"{WEB}/event-checkouts", json=body, headers=key)
    assert (
        r1.status_code == r2.status_code == 201
        and r2.json() == r1.json()
        and r2.headers.get("idempotent-replayed") == "true"
    )
    assert (await info(anon, ev["code"])).json()["taken"] == 1, (
        "gửi lại cùng key không giữ thêm ghế"
    )
    r3 = await anon.post(f"{WEB}/event-checkouts", json={**body, "phone": random_phone()})
    assert r3.status_code == 400 and code_of(r3) == "E-SEC-2", "thiếu Idempotency-Key"
    r4 = await anon.post(
        f"{WEB}/event-checkouts", json=body, headers={**idem(), "Origin": "https://evil.example"}
    )
    assert r4.status_code == 403 and code_of(r4) == "E-SEC-1", "sai Origin"


# ============================================================ AC9 đồng thời chỗ cuối, quầy không vượt


async def test_ac9_concurrent_buyers_for_the_last_seat_only_one_wins(admin, anon):
    ev = await mk_event(admin, capacity=3)
    assert (await buy(anon, ev["code"], 2)).status_code == 201  # còn đúng 1 chỗ
    phones = [random_phone() for _ in range(4)]
    tokens = [await phone_token(anon, p) for p in phones]
    res = await asyncio.gather(
        *[
            anon.post(
                f"{WEB}/event-checkouts",
                json={
                    "event_code": ev["code"],
                    "seats": 1,
                    "full_name": f"Tranh {i}",
                    "phone": p,
                    "phone_token": t,
                    "as_member": False,
                },
                headers=idem(),
            )
            for i, (p, t) in enumerate(zip(phones, tokens, strict=True))
        ]
    )
    codes = sorted(r.status_code for r in res)
    assert codes == [201, 409, 409, 409], codes
    assert all(
        code_of(r) == "E-WEB-10" and r.json()["detail"]["message"] == "Sự kiện đã hết chỗ."
        for r in res
        if r.status_code == 409
    )
    d = (await info(anon, ev["code"])).json()
    assert d["taken"] == 3 == d["capacity"] and d["can_buy"] is False


async def test_ac9_not_enough_seats_message_and_remaining(admin, anon):
    ev = await mk_event(admin, capacity=4)
    assert (await buy(anon, ev["code"], 3)).status_code == 201
    r = await buy(anon, ev["code"], 2)
    assert r.status_code == 409 and code_of(r) == "E-WEB-10"
    assert (
        r.json()["detail"]["remaining"] == 1
        and "chỉ còn 1" in r.json()["detail"]["message"].lower()
    )


async def test_ac9_front_desk_cannot_register_into_seats_held_online(admin, staff, anon):
    ev = await today_event(admin, capacity=2, price=40_000)
    assert (await buy(anon, ev["code"], 2)).status_code == 201, "giữ cả 2 ghế online"
    r = await staff.post(
        f"{FD}/sessions/{ev['code']}/tickets",
        json={"customer": {"temp": {"full_name": "Khách Quầy", "phone": random_phone()}}},
        headers=idem(),
    )
    assert r.status_code == 409, r.text
    assert (
        await q("SELECT count(*) AS n FROM booking.ticket WHERE code LIKE :c", c=f"{ev['code']}-V%")
    )[0]["n"] == 0, "quầy không lấy được ghế đang giữ"


async def test_ac9_expired_hold_releases_seats(admin, anon):
    ev = await mk_event(admin, capacity=1)
    co = (await buy(anon, ev["code"], 1)).json()
    r = await buy(anon, ev["code"], 1)
    assert r.status_code == 409 and code_of(r) == "E-WEB-10"
    await shift_expiry(co["pay_ref"], 120)
    r = await buy(anon, ev["code"], 1)
    assert r.status_code == 201, "hết hạn → nhả ghế → mua lại được"


# ============================================================ AC10 tiền về → vé; AC12 một lượt chờ / SĐT; AC21 tra cứu


async def test_ac10_ac21_guest_flow_otp_buy_pay_then_lookup_tickets(admin, anon):
    ev = await mk_event(admin, capacity=6, price=55_000, name="QA Sự kiện khách")
    phone = random_phone()
    # OTP → phone_token
    rq = await anon.post(f"{WEB}/phone/request", json={"phone": phone})
    assert rq.status_code == 202 and rq.json().get("test_otp")
    tok = (
        await anon.post(f"{WEB}/phone/verify", json={"phone": phone, "otp": rq.json()["test_otp"]})
    ).json()["phone_token"]
    r = await buy(anon, ev["code"], 2, phone=phone, name="Khách Ẩn Danh", phone_token=tok)
    assert r.status_code == 201, r.text
    co = r.json()
    # AC12: cùng SĐT chưa thanh toán xong → lượt thứ hai bị chặn (cả mua vé lẫn đặt sân)
    r2 = await buy(anon, ev["code"], 1, phone=phone, phone_token=tok)
    assert r2.status_code == 409 and code_of(r2) == "E-WEB-4"
    court = await new_court(admin)
    r3 = await checkout(anon, [(court["code"], 12)], phone=phone, phone_token=tok)
    assert r3.status_code == 409 and code_of(r3) == "E-WEB-4", (
        "ràng buộc chờ thanh toán chung đặt sân + mua vé"
    )
    # Chưa trả: tra cứu theo mã đơn thấy pending, chưa có mã vé
    pend = await anon.post(LOOKUP, json={"code": co["order_code"], "phone": phone})
    assert (
        pend.status_code == 200
        and pend.json()["kind"] == "ticket"
        and pend.json()["status"] == "pending"
    )
    # Tiền về đủ
    assert await simulate(admin, co["pay_ref"], co["amount"]), "giả lập tiền về trả kết quả xử lý"
    done = (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()
    assert done["status"] == "paid" and done["kind"] == "ticket"
    codes = done["event"]["ticket_codes"]
    assert codes == [f"{ev['code']}-V01", f"{ev['code']}-V02"], codes
    rows = await tickets_of(ev["code"])
    assert [(t["code"], t["source"], t["st"], t["amount"]) for t in rows] == [
        (f"{ev['code']}-V01", "online", "paid", 55_000),
        (f"{ev['code']}-V02", "online", "paid", 55_000),
    ]
    # Tra cứu: theo mã đơn vé, mã đơn viết liền, theo mã vé
    for key in (co["order_code"], co["order_code"].replace("-", ""), codes[0], codes[1].lower()):
        r = await anon.post(LOOKUP, json={"code": key, "phone": phone})
        assert r.status_code == 200, (key, r.text)
        d = r.json()
        assert (
            d["kind"] == "ticket"
            and d["status"] == "paid"
            and d["amount"] == 110_000
            and d["order_code"] == co["order_code"]
        )
        assert (
            d["event"]["name"] == "QA Sự kiện khách"
            and d["event"]["seats"] == 2
            and d["event"]["ticket_price"] == 55_000
        )
        assert [t["code"] for t in d["event"]["tickets"]] == codes and all(
            t["pay_status"] == "paid" for t in d["event"]["tickets"]
        )
        assert (
            d["paid_at"]
            and d["phone_masked"]
            and phone not in r.text
            and d["items"] == []
            and d["hours"] == 0
        )
    # Sai SĐT / sai mã → 404 E-WEB-7, giống hệt nhau (không dò được)
    bad = []
    for payload in (
        {"code": co["order_code"], "phone": random_phone()},
        {"code": codes[0], "phone": random_phone()},
        {"code": f"{ev['code']}-V09", "phone": phone},
        {"code": "BK-20000101-001", "phone": phone},
    ):
        r = await anon.post(LOOKUP, json=payload)
        assert r.status_code == 404 and code_of(r) == "E-WEB-7", payload
        bad.append(r.json())
    assert all(b == bad[0] for b in bad)
    # Đã thanh toán xong → được mua tiếp (hết lượt chờ)
    assert (await buy(anon, ev["code"], 1, phone=phone, phone_token=tok)).status_code == 201


async def test_ac21_court_lookup_keeps_old_shape(admin, anon):
    court = await new_court(admin)
    phone = random_phone()
    co = (await checkout(anon, [(court["code"], 14)], phone=phone)).json()
    assert await simulate(admin, co["pay_ref"], co["amount"])
    r = await anon.post(LOOKUP, json={"code": co["order_code"], "phone": phone})
    assert r.status_code == 200
    d = r.json()
    assert d.get("kind", "court") == "court" and d["items"] and d.get("event") in (None, {}), d


async def test_ac21_counter_registered_ticket_found_by_ticket_code(admin, staff, anon):
    ev = await today_event(admin, capacity=5, price=30_000)
    phone = random_phone()
    r = await staff.post(
        f"{FD}/sessions/{ev['code']}/tickets",
        json={"customer": {"temp": {"full_name": "Khách Vé Quầy", "phone": phone}}},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    tcode = r.json()["code"]
    r = await anon.post(LOOKUP, json={"code": tcode, "phone": phone})
    assert (
        r.status_code == 200
        and r.json()["kind"] == "ticket"
        and r.json()["event"]["seats"] == 1
        and [t["code"] for t in r.json()["event"]["tickets"]] == [tcode]
    )
    assert (
        await anon.post(LOOKUP, json={"code": tcode, "phone": random_phone()})
    ).status_code == 404


# ============================================================ AC10 chi tiết số vé liên tục, webhook lặp, AC11 thiếu/thừa/trễ/hết hạn


async def test_ac10_ticket_numbers_continue_after_counter_tickets_and_replay_does_not_duplicate(
    admin, staff, anon
):
    ev = await today_event(admin, capacity=10, price=20_000)
    for i in range(2):
        r = await staff.post(
            f"{FD}/sessions/{ev['code']}/tickets",
            json={"customer": {"temp": {"full_name": f"Quầy {i}", "phone": random_phone()}}},
            headers=idem(),
        )
        assert r.status_code == 201, r.text
    co = (await buy(anon, ev["code"], 3)).json()
    await simulate(admin, co["pay_ref"], co["amount"])
    again = await admin.post(
        f"{API}/payments/dev/simulate",
        json={"pay_ref": co["pay_ref"], "amount": co["amount"]},
        headers=idem(),
    )
    assert again.status_code == 200, "gửi lại giao dịch không lỗi hệ thống"
    rows = await tickets_of(ev["code"])
    assert [t["code"] for t in rows] == [f"{ev['code']}-V0{i}" for i in range(1, 6)], (
        "vé online nối tiếp số vé quầy, không trùng"
    )
    assert [t["source"] for t in rows] == ["counter", "counter", "online", "online", "online"]
    assert len(rows) == 5, "gửi tiền về hai lần không sinh vé hai lần"


async def test_ac11_underpaid_does_not_create_tickets_then_enough_does(admin, anon):
    ev = await mk_event(admin, capacity=5, price=50_000)
    co = (await buy(anon, ev["code"], 2)).json()
    await simulate(admin, co["pay_ref"], co["amount"] - 1)
    assert await tickets_of(ev["code"]) == []
    assert (await anon.get(f"{WEB}/checkouts/{co['token']}")).json()["status"] == "pending"
    first = await q(
        "SELECT outcome, amount FROM payments.bank_transaction WHERE pay_ref=:p ORDER BY id",
        p=co["pay_ref"],
    )
    assert [(r["outcome"], r["amount"]) for r in first] == [("partial", co["amount"] - 1)], (
        "giao dịch thiếu luôn được ghi (partial)"
    )
    await simulate(admin, co["pay_ref"], 1)
    assert len(await tickets_of(ev["code"])) == 2, "thiếu rồi đủ → sinh vé"


async def test_ac11_overpaid_creates_tickets_and_late_payment_after_expiry_creates_none(
    admin, anon
):
    ev = await mk_event(admin, capacity=5, price=50_000)
    co = (await buy(anon, ev["code"], 1)).json()
    out = await simulate(admin, co["pay_ref"], co["amount"] + 10_000)
    assert len(await tickets_of(ev["code"])) == 1, f"thừa tiền vẫn sinh vé ({out})"
    ev2 = await mk_event(admin, capacity=5, price=50_000)
    co2 = (await buy(anon, ev2["code"], 1)).json()
    await shift_expiry(co2["pay_ref"], 3600)
    await simulate(admin, co2["pay_ref"], co2["amount"])
    assert await tickets_of(ev2["code"]) == [], "tiền về sau hạn → không sinh vé"
    rows = await q(
        "SELECT outcome FROM payments.bank_transaction WHERE pay_ref=:p", p=co2["pay_ref"]
    )
    assert [r["outcome"] for r in rows] == ["refund_needed"], (
        "giao dịch trễ vẫn được ghi, chờ hoàn tiền"
    )
    async with SessionLocal() as db:  # worker nhả giữ chỗ quá hạn (mỗi 30 giây)
        assert await expire_holds(db) >= 1
        await db.commit()
    assert (await info(anon, ev2["code"])).json()["taken"] == 0, "hết hạn → nhả ghế"


async def test_ac11_same_outcome_as_court_checkout_for_underpay(admin, anon):
    court = await new_court(admin)
    c = (await checkout(anon, [(court["code"], 10)])).json()
    ev = await mk_event(admin, price=c["amount"], capacity=3)
    t = (await buy(anon, ev["code"], 1)).json()
    assert t["amount"] == c["amount"]
    o_court = await simulate(admin, c["pay_ref"], c["amount"] - 1)
    o_ticket = await simulate(admin, t["pay_ref"], t["amount"] - 1)
    assert o_court == o_ticket, "tiền thiếu: cùng kết quả cho checkout sân và checkout vé"
    o_court = await simulate(admin, c["pay_ref"], c["amount"])
    o_ticket = await simulate(admin, t["pay_ref"], t["amount"])
    assert o_court == o_ticket


# ============================================================ AC19 gắn khách; AC22 phone_token


async def test_ac22_phone_token_of_another_phone_is_rejected_and_nothing_is_held(admin, anon):
    ev = await mk_event(admin)
    a, b = random_phone(), random_phone()
    tok_a = await phone_token(anon, a)
    r = await buy(anon, ev["code"], 1, phone=b, phone_token=tok_a)
    assert (
        r.status_code == 403
        and code_of(r) == "E-WEB-8"
        and r.json()["detail"]["message"] == "Vui lòng xác minh số điện thoại trước khi thanh toán."
    )
    r = await buy(anon, ev["code"], 1, phone=b, token=False)
    assert r.status_code == 403 and code_of(r) == "E-WEB-8", "thiếu phone_token"
    r = await buy(anon, ev["code"], 1, phone=b, phone_token="x" * 30)
    assert r.status_code == 403 and code_of(r) == "E-WEB-8", "token giả"
    assert (await info(anon, ev["code"])).json()["taken"] == 0
    assert (await buy(anon, ev["code"], 1, phone=a, phone_token=tok_a)).status_code == 201


async def test_ac22_rate_limit_is_shared_with_court_checkout(admin, anon):
    ev = await mk_event(admin, capacity=50)
    court = await new_court(admin)
    statuses = []
    for i in range(8):
        if i % 2:
            r = await buy(anon, ev["code"], 1)
        else:
            r = await checkout(anon, [(court["code"], 5 + i)])
        statuses.append((r.status_code, code_of(r) if r.status_code >= 400 else None))
    assert statuses[:6] == [(201, None)] * 6 and all(s == (429, "E-SEC-5") for s in statuses[6:]), (
        statuses
    )


@pytest.fixture
async def phones_to_clean():
    phones: list[str] = []
    yield phones
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM customer WHERE phone = ANY(:p)"), {"p": phones})
        await conn.execute(text("DELETE FROM users WHERE phone = ANY(:p)"), {"p": phones})


async def test_ac19_guest_phone_of_a_member_attaches_to_that_member_and_new_phone_makes_a_temp_profile(
    admin, anon, phones_to_clean
):
    ev = await mk_event(admin, capacity=8, price=10_000)
    # SĐT thuộc hội viên do quầy tạo (đã có hồ sơ hội viên) → vé gắn vào hội viên đó
    mphone = random_phone()
    phones_to_clean.append(mphone)
    m = (
        await admin.post(
            f"{API}/members", json={"full_name": "QA HV Có Sẵn", "phone": mphone}, headers=idem()
        )
    ).json()
    co = (await buy(anon, ev["code"], 1, phone=mphone, name="Tên Gõ Khác")).json()
    await simulate(admin, co["pay_ref"], co["amount"])
    await drain_outbox()
    row = await q(
        "SELECT member_code, customer_kind FROM booking.ticket WHERE code LIKE :c",
        c=f"{ev['code']}-V%",
    )
    assert (
        len(row) == 1
        and row[0]["member_code"] == m["member_code"]
        and row[0]["customer_kind"] == "member"
    )
    members_before = (await q("SELECT count(*) AS n FROM customer WHERE kind='member'"))[0]["n"]
    # SĐT lạ → hồ sơ tạm, không tạo hội viên mới
    nphone = random_phone()
    phones_to_clean.append(nphone)
    co2 = (await buy(anon, ev["code"], 1, phone=nphone, name="QA Khách Lạ")).json()
    await simulate(admin, co2["pay_ref"], co2["amount"])
    await drain_outbox()
    cust = await q("SELECT kind::text AS kind, member_code FROM customer WHERE phone=:p", p=nphone)
    assert len(cust) == 1 and cust[0]["kind"] == "temp" and cust[0]["member_code"] is None
    assert (await q("SELECT count(*) AS n FROM customer WHERE kind='member'"))[0][
        "n"
    ] == members_before, "không tạo hội viên mới"
    tk = await q(
        "SELECT member_code, customer_kind FROM booking.ticket WHERE code LIKE :c ORDER BY seq DESC LIMIT 1",
        c=f"{ev['code']}-V%",
    )
    assert tk[0]["member_code"] is None and tk[0]["customer_kind"] != "member"

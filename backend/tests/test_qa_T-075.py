# ruff: noqa: E501
"""QA T-075 (API, AC1–AC4, AC14): lịch khách / hội viên hiện ô ``held`` kèm ``expires_at``.

Góc nhìn độc lập với ``test_public_held_slot.py`` của BACKEND: nhiều khung liền nhau của một lượt giữ và nhiều lượt khác nhau có
``expires_at`` riêng, quá hạn là trống ngay (người dùng 13/11 bỏ "Sắp mở lại" trong ân hạn) KHÔNG cần chạy tác vụ dọn, lượt đã thanh toán → ``booked``,
sự kiện thắng giữ chỗ, ô đóng cửa vẫn ``closed``, tập khóa ô đúng ở mọi trạng thái, không lộ tên / SĐT / mã đơn / mã con / ``pay_ref`` /
token ở BẤT KỲ chỗ nào của phản hồi, lịch hội viên (``mine = false``, ``order_code = null``), lịch admin không đổi, hồi quy luồng đặt
(E-WEB-4 cùng SĐT, hai khách tranh một ô, tiền về đúng số).
"""

import asyncio
from datetime import datetime, timedelta

from app.core.config import settings
from tests import test_play_rooms as base
from tests.conftest import idem
from tests.helpers_booking import BK, new_court, random_phone
from tests.helpers_web import checkout, simulate, tomorrow, web_calendar
from tests.test_online_payments import shift_expiry

people = base.people
SLOT_KEYS = {
    "start_hour",
    "state",
    "expires_at",
    "price",
    "band",
    "taken",
    "capacity",
    "event_code",
}
MA = "/api/v1/member-area"


async def slots(client, court_code: str, day=None) -> dict[int, dict]:
    cal = (await web_calendar(client, day)).json()
    row = next(x for x in cal["resources"] if x["code"] == court_code)
    return {s["start_hour"]: s for s in row["slots"]}


async def hold(anon, court_code: str, hours, name="QA Người Giữ", phone=None, day=None) -> dict:
    r = await checkout(
        anon,
        [(court_code, h) for h in hours],
        day=day,
        phone=phone or random_phone(),
        name=name,
    )
    assert r.status_code == 201, r.text
    return r.json()


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------- AC1, AC3: held + tập khóa + không lộ


async def test_ac1_ac3_held_slots_keys_expiry_and_no_identity_leak(anon, admin):
    court = await new_court(admin)
    code = court["code"]
    a = await hold(anon, code, (10, 11, 12), name="QA Họ Tên Bí Mật")
    b = await hold(anon, code, (15,), name="QA Người Thứ Hai")
    s = await slots(anon, code)
    for h in (10, 11, 12):
        assert set(s[h]) == SLOT_KEYS and s[h]["state"] == "held", h
        assert parse(s[h]["expires_at"]) == parse(a["expires_at"]), "cùng một lượt → cùng hạn"
    assert s[15]["state"] == "held" and parse(s[15]["expires_at"]) == parse(b["expires_at"])
    assert parse(s[10]["expires_at"]) < parse(s[15]["expires_at"]), (
        "hạn riêng từng lượt (lượt tạo sau thì hết hạn sau)"
    )
    for h in (10, 11, 12, 15):
        assert (
            s[h]["price"],
            s[h]["band"],
            s[h]["taken"],
            s[h]["capacity"],
            s[h]["event_code"],
        ) == (None,) * 5
    assert s[13]["state"] == "free" and s[13]["expires_at"] is None
    assert set(s[13]) == SLOT_KEYS and set(s[9]) == SLOT_KEYS
    # Không lộ gì ở BẤT KỲ chỗ nào của phản hồi lịch công khai
    raw = (await web_calendar(anon)).text
    for secret in (
        a["order_code"],
        a["pay_ref"],
        b["order_code"],
        b["pay_ref"],
        "QA Họ Tên Bí Mật",
        "QA Người Thứ Hai",
        a["token"],
    ):
        assert secret not in raw, secret
    for item in a["items"]:
        assert item["code"] not in raw, "mã con không được lộ"
    # hạn thanh toán ≈ 5 phút sau lúc tạo (không cộng ân hạn)
    assert (
        timedelta(minutes=4)
        < parse(a["expires_at"]) - datetime.now().astimezone()
        <= timedelta(minutes=5, seconds=5)
    )


async def test_held_is_shown_to_the_holder_too_and_to_members(anon, admin, people):
    court = await new_court(admin)
    code = court["code"]
    co = await hold(anon, code, (9,))
    hv = await people("QA Hội Viên Xem")
    r = await hv.client.get(f"{MA}/booking-calendar", params={"date": tomorrow().isoformat()})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["resources"] if x["code"] == code)
    slot = next(x for x in row["slots"] if x["start_hour"] == 9)
    assert slot["state"] == "held" and slot["expires_at"], slot
    assert slot.get("mine") is False and slot.get("order_code") is None
    assert co["order_code"] not in r.text and co["pay_ref"] not in r.text
    # Hội viên: các ô khác vẫn có đủ khóa như cũ (mine / order_code có mặt)
    free = next(x for x in row["slots"] if x["start_hour"] == 13)
    assert free["state"] == "free" and "mine" in free


# ---------------------------------------------------------------- AC2: hết hạn là mở lại ngay


async def test_ac2_free_right_at_expiry_without_any_cleanup_job(anon, admin):
    """Người dùng 13/11: bỏ 60 giây "Sắp mở lại" – quá hạn là trống trên lịch và đặt được ngay;
    ân hạn chỉ còn cho tiền báo trễ khi khung chưa bị lấy."""
    court = await new_court(admin)
    code = court["code"]
    co = await hold(anon, code, (14, 15))
    await shift_expiry(co["pay_ref"], 5)  # quá hạn 5 giây (trong ân hạn nhận tiền, không chạy dọn)
    s = await slots(anon, code)
    assert (s[14]["state"], s[14]["expires_at"], s[15]["state"]) == ("free", None, "free")
    again = await checkout(anon, [(code, 14)], phone=random_phone(), name="QA Đặt Lại")
    assert again.status_code == 201, again.text
    # Khung đã bị lấy ⇒ tiền báo trễ của lượt cũ không tạo booking (cần hoàn)
    assert await simulate(admin, co["pay_ref"], co["amount"]) != "applied"


async def test_paid_hold_becomes_booked_and_event_beats_held(anon, admin):
    court = await new_court(admin)
    code = court["code"]
    co = await hold(anon, code, (16,))
    assert (await slots(anon, code))[16]["state"] == "held"
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    s = await slots(anon, code)
    assert (s[16]["state"], s[16]["expires_at"]) == ("booked", None)
    # Sự kiện hiện như cũ (event) với taken / capacity; ô đóng cửa vẫn closed
    court2 = await new_court(admin, open_time="08:00", close_time="20:00")
    ev = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court2["code"]],
            "date": tomorrow().isoformat(),
            "start_hour": 10,
            "end_hour": 12,
            "name": "QA sự kiện",
            "capacity": 6,
            "ticket_price": 40000,
        },
        headers=idem(),
    )
    assert ev.status_code == 201, ev.text
    s2 = await slots(anon, court2["code"])
    assert (
        s2[10]["state"] == s2[11]["state"] == "event"
        and s2[10]["capacity"] == 6
        and s2[10]["event_code"] == ev.json()["code"]
    )
    assert s2[10]["expires_at"] is None
    assert (
        s2[6]["state"] == "closed" and s2[6]["expires_at"] is None and s2[21]["state"] == "closed"
    )


# ---------------------------------------------------------------- AC4, AC14: không đổi


async def test_ac4_admin_calendar_unchanged_and_ac14_booking_flow_regressions(anon, admin, staff):
    court = await new_court(admin)
    code = court["code"]
    phone = random_phone()
    co = await hold(anon, code, (11,), phone=phone)
    # Lịch admin: khối hold có expires_at, như cũ
    cal = (await staff.get(f"{BK}/calendar", params={"date": tomorrow().isoformat()})).json()
    holds = [
        b for b in cal["blocks"] if b["type"] == "hold" and code in b.get("resource_codes", [])
    ]
    assert holds and holds[0].get("expires_at"), "lịch admin vẫn có khối hold + hạn"
    assert all(b["type"] != "held" for b in cal["blocks"])
    # E-WEB-4: cùng SĐT đang giữ chưa thanh toán → 409
    dup = await checkout(anon, [(code, 12)], phone=phone, name="QA Cùng SĐT")
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "E-WEB-4", dup.text
    # Hai khách tranh một ô: chỉ một thắng
    court2 = await new_court(admin)
    rs = await asyncio.gather(
        *[
            checkout(anon, [(court2["code"], 9)], phone=random_phone(), name=f"QA Tranh {i}")
            for i in range(4)
        ]
    )
    assert sorted(r.status_code for r in rs).count(201) == 1, [r.status_code for r in rs]
    s = await slots(anon, court2["code"])
    assert s[9]["state"] == "held"
    # Tiền về đúng số vẫn tạo booking (hồi quy T-008)
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    assert (await slots(anon, code))[11]["state"] == "booked"


async def test_today_slots_and_date_edges_keep_working(anon, admin):
    court = await new_court(admin)
    code = court["code"]
    now = datetime.now(settings.tz)
    if now.hour < 21:  # hôm nay: ô còn ở tương lai giữ được và hiện held
        h = now.hour + 2
        co = await hold(anon, code, (h,), day=now.date())
        today_cal = (await web_calendar(anon, now.date())).json()
        row = next(x for x in today_cal["resources"] if x["code"] == code)
        slot = next(x for x in row["slots"] if x["start_hour"] == h)
        assert slot["state"] == "held" and slot["expires_at"], slot
        assert co["order_code"] not in str(today_cal)
    # Ngày không có giữ chỗ: không có khóa expires_at khác null ở bất kỳ ô nào
    far = (await web_calendar(anon, tomorrow() + timedelta(days=60))).json()
    assert all(s["expires_at"] is None for r in far["resources"] for s in r["slots"])

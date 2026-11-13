"""T-075: lịch khách / hội viên hiện ô ``held`` (đang có người giữ chỗ) kèm ``expires_at``.

- Cả trong 60 giây ân hạn; hết ân hạn -> trống lại; đã thanh toán -> ``booked``.
- Không có tên / SĐT / mã đơn / token; lịch hội viên ``mine = false`` cho ô đang giữ.
"""

from datetime import datetime

from tests import test_play_rooms as base
from tests.helpers_web import simulate, tomorrow, web_calendar
from tests.test_online_payments import new_checkout, shift_expiry

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)
MA = "/api/v1/member-area"
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


async def slots_of(anon, court_code: str) -> dict[int, dict]:
    cal = (await web_calendar(anon, tomorrow())).json()
    row = next(x for x in cal["resources"] if x["code"] == court_code)
    return {s["start_hour"]: s for s in row["slots"]}


async def test_held_slot_in_grace_then_free_or_booked(anon, admin):
    """AC1–AC3: ô giữ -> held + hạn; quá hạn mà còn trong ân hạn -> vẫn held; hết ân hạn -> trống;
    lượt đã thanh toán -> booked."""
    co = await new_checkout(anon, admin, hours=(15, 16), name="Người Đang Giữ")
    code = co["court"]["code"]
    slots = await slots_of(anon, code)
    for h in (15, 16):
        assert set(slots[h]) == SLOT_KEYS
        assert slots[h]["state"] == "held" and slots[h]["price"] is None
        assert datetime.fromisoformat(slots[h]["expires_at"]) == datetime.fromisoformat(
            co["expires_at"]
        )
    assert slots[17]["state"] == "free" and slots[17]["expires_at"] is None
    raw = str(slots)
    assert co["order_code"] not in raw and co["pay_ref"] not in raw and "Người Đang Giữ" not in raw

    await shift_expiry(co["pay_ref"], 30)  # quá hạn 30 giây: đang trong 60 giây ân hạn
    slots = await slots_of(anon, code)
    assert slots[15]["state"] == "held"
    assert datetime.fromisoformat(slots[15]["expires_at"]) < datetime.now().astimezone()

    await shift_expiry(co["pay_ref"], 70)  # hết ân hạn: khung trống lại
    slots = await slots_of(anon, code)
    assert (slots[15]["state"], slots[15]["expires_at"]) == ("free", None)

    paid = await new_checkout(anon, admin, hours=(18,))
    assert (await slots_of(anon, paid["court"]["code"]))[18]["state"] == "held"
    await simulate(admin, paid["pay_ref"], paid["amount"])
    slot = (await slots_of(anon, paid["court"]["code"]))[18]
    assert (slot["state"], slot["expires_at"]) == ("booked", None)


async def test_member_calendar_held_is_never_mine(anon, admin, people):
    """Lịch hội viên kế thừa ô held, luôn ``mine = false`` (server không biết lượt nào của ai)."""
    hv = await people("Hội Viên Xem Lịch")
    co = await new_checkout(anon, admin, hours=(14,))
    r = await hv.client.get(f"{MA}/booking-calendar", params={"date": tomorrow().isoformat()})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["resources"] if x["code"] == co["court"]["code"])
    slot = {s["start_hour"]: s for s in row["slots"]}[14]
    assert (slot["state"], slot["mine"], slot["order_code"]) == ("held", False, None)
    assert slot["expires_at"] is not None

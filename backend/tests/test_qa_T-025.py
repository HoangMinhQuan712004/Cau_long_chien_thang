# ruff: noqa: E501
"""QA T-025 (BE): lịch admin có giá từng ô `hour_prices` (AC9), cùng cách tính với lịch khách; quyền; không lộ ra lịch công khai."""

from datetime import timedelta

from tests.conftest import idem
from tests.helpers_booking import (
    BK,
    book,
    calendar,
    new_court,
    random_phone,
    safe_hour,
    temp,
    today,
)
from tests.helpers_web import tomorrow, web_calendar


def next_weekday(day, weekday: int):
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def prices_of(cal: dict, court_code: str) -> dict[int, int]:
    row = next(r for r in cal["resources"] if r["code"] == court_code)
    return {int(h): p for h, p in row["hour_prices"].items()}


async def test_ac9_prices_equal_the_public_calendar_on_weekday_and_weekend(anon, admin, staff):
    court = await new_court(
        admin, open_time="05:00", close_time="23:00", peak_bands=[["17:00", "21:00"]]
    )
    for day in (
        next_weekday(tomorrow(), 2),
        next_weekday(tomorrow(), 5),
        next_weekday(tomorrow(), 6),
    ):  # thứ 4, thứ 7, chủ nhật
        for who in (admin, staff):
            prices = prices_of(await calendar(who, day), court["code"])
            public = (await web_calendar(anon, day)).json()
            slots = next(r for r in public["resources"] if r["code"] == court["code"])["slots"]
            free = {s["start_hour"]: s["price"] for s in slots if s["state"] == "free"}
            assert free and {h: prices[h] for h in free} == free, (day, who)
            assert set(prices) == set(range(5, 23)) and all(
                isinstance(p, int) and p > 0 for p in prices.values()
            )
    wed = prices_of(await calendar(admin, next_weekday(tomorrow(), 2)), court["code"])
    assert wed[19] > wed[8], "cao điểm đắt hơn thấp điểm"


async def test_ac9_no_price_outside_opening_hours_and_prices_present_for_past_hours(admin):
    court = await new_court(admin, open_time="06:00", close_time="22:00", peak_bands=[])
    prices = prices_of(await calendar(admin, today()), court["code"])
    assert set(prices) == set(range(6, 22)), "chỉ các giờ mở cửa"
    assert 6 in prices and 21 in prices and 5 not in prices and 22 not in prices
    empty = await new_court(admin, open_time="00:00", close_time="24:00", peak_bands=[])
    all_day = prices_of(await calendar(admin, today()), empty["code"])
    assert set(all_day) == set(range(24)), "kể cả ô đã qua của hôm nay"


async def test_ac9_booked_slot_keeps_its_price_and_equals_the_amount_charged(admin):
    court = await new_court(admin, peak_bands=[])
    h = await safe_hour()
    r = await book(admin, court["code"], h, h + 1, temp("QA Khách Giá", random_phone()))
    assert r.status_code == 201, r.text
    blk = r.json()["bookings"][0] if "bookings" in r.json() else r.json()
    prices = prices_of(await calendar(admin, today()), court["code"])
    assert h in prices, "ô đã đặt vẫn có giá"
    item = (await admin.get(f"{BK}/items/{blk['code']}")).json()
    assert item["payment"]["amount"] == prices[h], "giá xem trước = giá engine chốt khi đặt"


async def test_ac9_access_and_public_calendar_does_not_get_hour_prices(
    admin, anon, customer, staff
):
    court = await new_court(admin)
    day = tomorrow().isoformat()
    assert (await anon.get(f"{BK}/calendar", params={"date": day})).status_code in (401, 403)
    assert (await customer.get(f"{BK}/calendar", params={"date": day})).status_code == 403
    assert (await staff.get(f"{BK}/calendar", params={"date": day})).status_code == 200
    pub = (await web_calendar(anon)).json()
    row = next(r for r in pub["resources"] if r["code"] == court["code"])
    assert "hour_prices" not in row and "hour_prices" not in str(pub)


async def test_ac9_stopped_court_has_no_prices(admin):
    court = await new_court(admin)
    r = await admin.patch(
        f"{BK}/resources/{court['code']}",
        json={"status": "inactive", "version": court["version"]},
        headers=idem(),
    )
    if r.status_code != 200:  # tên trường trạng thái khác: thử is_active
        r = await admin.patch(
            f"{BK}/resources/{court['code']}",
            json={"is_active": False, "version": court["version"]},
            headers=idem(),
        )
    assert r.status_code == 200, r.text
    cal = await calendar(admin, tomorrow())
    rows = [x for x in cal["resources"] if x["code"] == court["code"]]
    assert not rows or not rows[0].get("hour_prices"), "sân ngừng hoạt động không có giá"

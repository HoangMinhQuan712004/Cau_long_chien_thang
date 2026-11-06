"""T-025 AC9: lịch admin có giá từng ô (cùng cách tính với lịch khách)."""

from tests.helpers_booking import calendar, new_court, set_legacy_schedule
from tests.helpers_web import tomorrow, web_calendar


async def test_admin_calendar_hour_prices_match_public(anon, admin, staff):
    court = await new_court(
        admin, open_time="06:00", close_time="22:00", peak_bands=[["17:00", "21:00"]]
    )
    # Lịch cũ có :30 vẫn tính "một phần cao điểm" (API mới chỉ nhận tròn giờ)
    await set_legacy_schedule(court["code"], peak_bands=[["17:30", "21:00"]])
    day = tomorrow()
    cal = await calendar(staff, day)  # NV cũng thấy giá (không quyền mới)
    row = next(r for r in cal["resources"] if r["code"] == court["code"])
    prices = {int(h): p for h, p in row["hour_prices"].items()}

    public = (await web_calendar(anon, day)).json()
    slots = next(r for r in public["resources"] if r["code"] == court["code"])["slots"]
    free = {s["start_hour"]: s for s in slots if s["state"] == "free"}
    assert free and {h: prices[h] for h in free} == {h: s["price"] for h, s in free.items()}

    # Ngoài giờ mở cửa: không có giá; giá thấp / cao / một phần cao điểm khác nhau
    assert set(prices) == set(range(6, 22))
    assert set(prices) & set(row["off_hours"]) == set()
    assert prices[16] < prices[17] < prices[18]  # 17h = nửa cao điểm (partial)
    assert prices[18] == prices[20]

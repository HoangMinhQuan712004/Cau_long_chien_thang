"""T-025 AC9: lịch admin có giá từng ô (cùng cách tính với lịch khách)."""

from tests.conftest import idem
from tests.helpers_booking import BK, calendar, new_court, set_legacy_schedule
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


async def test_inactive_court_shows_grey_on_admin_calendar_only(anon, admin, staff):
    """Người dùng chốt 2026-11-09: sân ngừng vẫn có hàng (xám) ở lịch quản trị, khách không thấy."""
    court = await new_court(admin)
    deleted = await new_court(admin)
    r = await admin.patch(
        f"{BK}/resources/{court['code']}",
        json={"version": court["version"], "is_active": False},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (
        await admin.delete(f"{BK}/resources/{deleted['code']}", headers=idem())
    ).status_code == 204
    day = tomorrow()

    cal = await calendar(staff, day)
    codes = [r["code"] for r in cal["resources"]]
    row = next(r for r in cal["resources"] if r["code"] == court["code"])
    assert row["is_active"] is False and row["hour_prices"] == {}
    assert set(row["off_hours"]) == set(cal["columns"]), "mọi giờ không bán"
    assert deleted["code"] not in codes, "sân đã xóa không hiện"
    # Sân hoạt động trước, sân ngừng xuống cuối; trong mỗi nhóm giữ thứ tự danh mục
    listing = (await admin.get(f"{BK}/resources")).json()["items"]
    active = [i["code"] for i in listing if i["is_active"]]
    inactive = [i["code"] for i in listing if not i["is_active"]]
    assert codes == active + inactive

    public = (await web_calendar(anon, day)).json()
    shown = [r["code"] for r in public["resources"]]
    assert court["code"] not in shown and deleted["code"] not in shown

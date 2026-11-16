"""Báo cáo & phân tích (SRS-CAULONG-BCPT): kỳ, 3 chỉ số, doanh thu ngày / sân, heatmap, quyền.

Số liệu tính qua service với tenant riêng của từng test (``helpers_reports.Venue``) và ``now``
cố định (hôm nay của Phụ lục C: T3 13/10/2026 10:32).
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.modules.booking_engine.report_revenue import code_key, split_by_hours
from app.modules.members.models import Customer
from app.modules.reports import service
from app.modules.reports.schemas import MetricOut
from tests.conftest import API
from tests.helpers_booking import today
from tests.helpers_reports import Venue, add_customer, at

URL = f"{API}/admin/reports/overview"
TODAY = date(2026, 10, 13)
NOW = at(TODAY, 10 + 32 / 60)
WEEK = (date(2026, 10, 7), TODAY)
# Phụ lục C: doanh thu từng ngày 07/10 → 13/10
DAILY = [12_750_000, 13_050_000, 14_600_000, 16_950_000, 17_400_000, 13_230_000, 11_870_000]


def d(day: int, month: int = 10) -> date:
    return date(2026, month, day)


@pytest.fixture
async def phones():
    """Hồ sơ khách do test tạo – xóa sau test (hồ sơ không tách theo tenant)."""
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.commit()


# ------------------------------------------------------------------ kỳ, 3 chỉ số, NFR-002


async def test_sample_week_matches_appendix_c():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        for code in ("S01", "S02", "S03"):
            await v.court(code)
        for i, amount in enumerate(DAILY):
            day = WEEK[0] + timedelta(days=i)
            if i == 3:  # 10/10: một sự kiện 2 sân, tiền nằm ở vé
                await v.event(["S02", "S01"], day, 8, [amount - 950_000, 950_000])
            else:  # 13/10 20h: chưa tới giờ chơi nhưng đã trả trước ⇒ vẫn tính
                await v.booking(f"S0{i % 3 + 1}", day, 20 if i == 6 else 9, amount)
        await v.booking("S01", d(8), 15, 1_000_000, status="unpaid")
        await v.booking("S02", d(9), 15, 2_000_000, status="uncollectible")
        await v.booking("S03", d(30, 9), 8, 97_250_000)
        # So cùng mốc: 06/10 11h bắt đầu sau 10:32 ⇒ không vào kỳ trước
        await v.booking("S03", d(6), 11, 5_000_000)
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    assert (r.period.date_from, r.period.date_to, r.period.days) == (*WEEK, 7)
    assert (r.previous.date_from, r.previous.date_to) == (d(30, 9), d(6))
    assert r.previous.until == at(d(6), 10 + 32 / 60)
    assert r.revenue == MetricOut(current=99_850_000, previous=97_250_000)
    assert [x.date for x in r.daily] == [WEEK[0] + timedelta(days=i) for i in range(7)]
    assert [x.revenue for x in r.daily] == DAILY
    # NFR-002: thẻ = tổng biểu đồ ngày = tổng biểu đồ sân
    assert sum(x.revenue for x in r.daily) == sum(c.revenue for c in r.courts) == 99_850_000
    assert (r.bookings.current, r.bookings.tickets, r.bookings.previous) == (8, 2, 1)
    assert r.active_courts == 3


async def test_past_period_compares_whole_days():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01")
        await v.booking("S01", d(6), 21, 300_000)
        await v.booking("S01", d(30, 9), 21, 200_000)
        await s.commit()
        r = await service.overview(s, d(1), d(6), now=NOW, tenant_id=v.tid)

    assert (r.previous.date_from, r.previous.date_to, r.previous.until) == (
        d(25, 9),
        d(30, 9),
        None,
    )
    assert r.revenue == MetricOut(current=300_000, previous=200_000)


async def test_previous_cutoff_applies_to_tickets():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01")
        await v.event(["S01"], d(6), 10, [70_000])  # 10:00 < 10:32 ⇒ tính
        await v.event(["S01"], d(6), 12, [80_000])  # 12:00 ⇒ không tính
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    assert r.revenue.previous == 70_000
    assert r.bookings.previous == 1


async def test_empty_period_is_all_zero():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01")
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    assert r.revenue == MetricOut(current=0, previous=0)
    assert [x.revenue for x in r.daily] == [0] * 7
    assert [(c.code, c.revenue) for c in r.courts] == [("S01", 0)]


async def test_new_members_by_created_at_with_same_cutoff(phones):
    # Ngày năm 2019 chỉ test này dùng (hồ sơ khách không tách theo tenant)
    now = at(date(2019, 3, 13), 10 + 32 / 60)
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await add_customer(s, at(date(2019, 3, 7), 0), phones)
        await add_customer(s, at(date(2019, 3, 13), 20), phones)
        await add_customer(s, at(date(2019, 3, 8), 9), phones, member=False)  # hồ sơ tạm
        await add_customer(s, at(date(2019, 2, 28), 0), phones)
        await add_customer(s, at(date(2019, 3, 6), 9), phones)
        await add_customer(s, at(date(2019, 3, 6), 11), phones)  # sau mốc 10:32 của kỳ trước
        await s.commit()
        r = await service.overview(s, date(2019, 3, 7), date(2019, 3, 13), now=now, tenant_id=v.tid)

    assert r.new_members == MetricOut(current=2, previous=2)


# ------------------------------------------------------------------ theo sân (BR-015, OQ-6/7)


def test_split_by_hours_gives_remainder_to_smallest_code():
    assert split_by_hours(100_001, {"S02": 120, "S01": 120, "S03": 120}) == {
        "S01": 33_335,
        "S02": 33_333,
        "S03": 33_333,
    }
    assert split_by_hours(1_000, {"S02": 120, "S01": 60}) == {"S01": 334, "S02": 666}
    assert split_by_hours(0, {"S01": 60}) == {}
    assert sorted(["S10", "S100", "S02"], key=code_key) == ["S02", "S10", "S100"]


async def test_courts_split_tickets_and_show_inactive_with_revenue():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        for code in ("S01", "S02", "S03", "S06"):
            await v.court(code)
        await v.court("S04", active=False)
        await v.court("S05", active=False)
        await v.event(["S03", "S01", "S02"], d(8), 18, [50_000, 50_001])
        await v.booking("S04", d(7), 9, 100_000)  # ghi trước khi sân ngừng
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    assert [(c.code, c.revenue, c.is_active) for c in r.courts] == [
        ("S01", 33_335, True),
        ("S02", 33_333, True),
        ("S03", 33_333, True),
        ("S04", 100_000, False),
        ("S06", 0, True),
    ]
    assert sum(c.revenue for c in r.courts) == r.revenue.current == 200_001
    assert r.active_courts == 4


# ------------------------------------------------------------------ heatmap (BR-016, BR-017)


async def test_heatmap_by_day_uses_schedule_of_each_day():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01")
        await v.court("S02", 6.5)
        await v.hours("S02", 8, 22, since=d(9))  # từ 09/10 mở 08:00
        await v.court("S03", active=False)
        await v.booking("S01", d(7), 17, 0, hours=2, status="uncollectible")
        await v.booking("S03", d(7), 17, 100_000)  # sân ngừng: không vào tử / mẫu
        await v.booking("S02", d(7), 6, 50_000)  # 06h–07h, sân mở 06:30 ⇒ 0,5
        await v.event(["S01", "S02"], d(8), 18, [])  # sự kiện chưa có vé vẫn là đã đặt
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    h = r.heatmap
    assert h.mode == "day"
    assert h.hours == list(range(5, 22))
    assert [(c.date, c.weekday, c.is_today) for c in h.columns] == [
        (WEEK[0] + timedelta(days=i), (WEEK[0] + timedelta(days=i)).weekday(), i == 6)
        for i in range(7)
    ]

    def cell(hour: int, day: int) -> tuple[float, float]:
        c = h.cells[h.hours.index(hour)][(d(day) - WEEK[0]).days]
        return c.booked_hours, c.open_hours

    assert cell(5, 7) == (0, 1)
    assert cell(6, 7) == (0.5, 1.5)
    assert cell(17, 7) == cell(18, 7) == (1, 2)
    assert cell(18, 8) == cell(19, 8) == (2, 2)
    assert cell(6, 9) == cell(7, 9) == (0, 1)
    assert cell(8, 9) == (0, 2)


async def test_heatmap_hour_without_open_court_has_zero_open_hours():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01", 5, 8)
        await v.court("S02", 10, 12)
        await s.commit()
        r = await service.overview(s, *WEEK, now=NOW, tenant_id=v.tid)

    h = r.heatmap
    assert h.hours == list(range(5, 12))
    for hour in (8, 9):  # ô "–"
        assert all(c.open_hours == 0 for c in h.cells[h.hours.index(hour)])
    assert all(c.open_hours == 1 for c in h.cells[h.hours.index(10)])


async def test_heatmap_longer_than_week_groups_by_weekday():
    async with SessionLocal() as s:
        v = await Venue.create(s)
        await v.court("S01")
        await v.booking("S01", d(30, 9), 17, 100_000)  # T4
        await v.booking("S01", d(7), 17, 100_000)  # T4
        await s.commit()
        r = await service.overview(s, d(30, 9), TODAY, now=NOW, tenant_id=v.tid)

    h = r.heatmap
    assert h.mode == "weekday"
    assert [(c.date, c.weekday, c.is_today) for c in h.columns] == [
        (None, w, False) for w in range(7)
    ]
    wednesday = d(7).weekday()
    row = h.cells[h.hours.index(17)]
    assert (row[wednesday].booked_hours, row[wednesday].open_hours) == (2, 2)
    assert all(c.booked_hours == 0 for i, c in enumerate(row) if i != wednesday)


# ------------------------------------------------------------------ API, kiểm ngày, quyền


async def test_default_period_is_week_to_today(admin):
    r = await admin.get(URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == {
        "from": (today() - timedelta(days=6)).isoformat(),
        "to": today().isoformat(),
        "days": 7,
    }
    assert body["previous"]["to"] == (today() - timedelta(days=7)).isoformat()
    assert body["previous"]["until"] is not None
    assert len(body["daily"]) == 7
    assert sum(x["revenue"] for x in body["daily"]) == body["revenue"]["current"]
    assert sum(c["revenue"] for c in body["courts"]) == body["revenue"]["current"]


@pytest.mark.parametrize(
    ("offsets", "code"),
    [
        ((0, -1), "E-REPORT-1"),
        ((-90, 0), "E-REPORT-2"),
        ((0, 1), "E-REPORT-3"),
    ],
)
async def test_invalid_range(admin, offsets, code):
    start, end = (today() + timedelta(days=n) for n in offsets)
    r = await admin.get(URL, params={"from": start.isoformat(), "to": end.isoformat()})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == code


async def test_ninety_days_is_allowed(admin):
    start = today() - timedelta(days=89)
    r = await admin.get(URL, params={"from": start.isoformat(), "to": today().isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["heatmap"]["mode"] == "weekday"


async def test_staff_forbidden(staff):
    r = await staff.get(URL)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "E-AUTH-2"


async def test_requires_sign_in(anon):
    assert (await anon.get(URL)).status_code == 401

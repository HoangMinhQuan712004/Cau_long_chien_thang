"""T-030 giai đoạn A: Bảng xếp hạng tốc độ cú đập, kỷ lục cá nhân, seed dev."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records import seed_demo
from app.modules.records.models import SpeedRecord
from app.modules.records.service import period_bounds
from tests import test_play_rooms as base
from tests.test_play_rooms import MA

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

RANKING = f"{MA}/speed-ranking"
TAG = f"test:{uuid.uuid4().hex[:8]}:"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.like(f"{TAG}%")))
        await s.commit()


def vn(y: int, m: int, d: int, h: int = 10) -> datetime:
    return datetime(y, m, d, h, tzinfo=settings.tz)


async def record(cid: int, kmh: int, at: datetime) -> None:
    async with SessionLocal() as s:
        s.add(
            SpeedRecord(
                customer_id=cid, speed_kmh=kmh, measured_at=at, source_ref=f"{TAG}{uuid.uuid4()}"
            )
        )
        await s.commit()


async def set_profile(cid: int, **values) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Customer).where(Customer.id == cid).values(**values))
        await s.commit()


async def ranking(client, period: str, day: str) -> dict:
    r = await client.get(RANKING, params={"period": period, "date": day})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


async def test_ranking_order_ties_privacy_gap_and_inactive(people):
    hv = [await people(f"Tay Vợt {i:02d}") for i in range(12)]
    for p in hv:
        await set_profile(p.customer_id, show_on_records=True)
    anon_hv, me, stopped = hv[1], hv[10], hv[11]
    await set_profile(anon_hv.customer_id, show_on_records=False)

    await record(hv[0].customer_id, 300, vn(2031, 3, 2))
    await record(hv[0].customer_id, 250, vn(2031, 3, 3))  # thấp hơn -> không tính
    await record(anon_hv.customer_id, 300, vn(2031, 3, 1))  # bằng nhưng đạt trước -> hạng 1
    for i in range(2, 10):
        await record(hv[i].customer_id, 300 - i * 10, vn(2031, 3, 5))  # 280 … 210
    await record(me.customer_id, 200, vn(2031, 3, 6))
    await record(stopped.customer_id, 500, vn(2031, 3, 7))
    await set_profile(stopped.customer_id, is_active=False)  # Ngừng -> không vào bảng
    # 01/04 00:30 giờ VN (31/03 17:30 UTC) -> thuộc tháng 4
    await record(hv[0].customer_id, 400, datetime(2031, 3, 31, 17, 30, tzinfo=UTC))

    d = await ranking(me.client, "month", "2031-03-15")
    assert (d["period"], d["start"], d["end"]) == ("month", "2031-03-01", "2031-03-31")
    assert d["total_members"] == 11 and d["bar_floor_kmh"] == 200
    top = d["top"]
    assert [r["rank"] for r in top] == list(range(1, 11))
    assert [r["speed_kmh"] for r in top] == [300, 300, 280, 270, 260, 250, 240, 230, 220, 210]
    assert top[0] == {
        "rank": 1,
        "display_name": "Hội viên ẩn danh",
        "avatar_url": None,
        "speed_kmh": 300,
        "is_me": False,
    }
    assert top[1]["display_name"] == "Tay Vợt 00"
    assert not any(r["is_me"] for r in top)
    assert d["me"]["rank"] == 11 and d["me"]["speed_kmh"] == 200
    assert d["me"]["gap_to_top10"] == 10  # 210 − 200
    assert "customer_id" not in str(d) and "Tay Vợt 01" not in str(d) and "Tay Vợt 11" not in str(d)

    # Người ẩn danh luôn thấy tên mình; đã trong top 10 -> không có khoảng cách
    d = await ranking(anon_hv.client, "month", "2031-03-31")
    assert top[0]["speed_kmh"] == d["top"][0]["speed_kmh"]
    assert d["top"][0]["display_name"] == "Tay Vợt 01" and d["top"][0]["is_me"]
    assert d["me"] == {
        "rank": 1,
        "speed_kmh": 300,
        "measured_at": d["me"]["measured_at"],
        "gap_to_top10": None,
    }

    # Tháng 4 (giờ VN): chỉ số đo 400 của Tay Vợt 00
    d = await ranking(me.client, "month", "2031-04-01")
    assert [(r["display_name"], r["speed_kmh"]) for r in d["top"]] == [("Tay Vợt 00", 400)]
    assert d["me"] is None
    # Năm: lấy số cao nhất cả năm
    d = await ranking(me.client, "year", "2031-07-01")
    assert (d["start"], d["end"], d["top"][0]["speed_kmh"]) == ("2031-01-01", "2031-12-31", 400)

    # Kỷ lục mọi thời gian ở Hồ sơ
    r = await hv[0].client.get(f"{MA}/me")
    assert r.status_code == 200 and r.json()["record_kmh"] == 400
    r = await me.client.get(f"{MA}/me")
    assert r.json()["record_kmh"] == 200


async def test_week_bounds_empty_period_and_errors(anon, customer, people):
    hv = await people("Tuần Này")
    # 2031-03-09 là Chủ nhật, 2031-03-10 là Thứ 2
    assert date(2031, 3, 9).weekday() == 6
    await record(hv.customer_id, 210, vn(2031, 3, 9, 23))
    await record(hv.customer_id, 220, vn(2031, 3, 10, 0))

    d = await ranking(hv.client, "week", "2031-03-12")
    assert (d["start"], d["end"]) == ("2031-03-10", "2031-03-16")
    assert d["me"]["speed_kmh"] == 220
    d = await ranking(hv.client, "week", "2031-03-09")
    assert (d["start"], d["end"], d["me"]["speed_kmh"]) == ("2031-03-03", "2031-03-09", 210)
    assert period_bounds("week", date(2031, 3, 10)) == (date(2031, 3, 10), date(2031, 3, 16))

    d = await ranking(hv.client, "year", "2040-01-01")
    assert (d["total_members"], d["top"], d["me"]) == (0, [], None)
    assert (await hv.client.get(RANKING)).status_code == 200  # mặc định tháng này

    for params in ({"period": "day"}, {"date": "2031-02-30"}, {"date": "abc"}):
        assert (await hv.client.get(RANKING, params=params)).status_code == 422, params
    assert (await anon.get(RANKING)).status_code == 401
    r = await customer.get(RANKING)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"


async def test_speed_range_and_unique_source_ref(people):
    hv = await people()
    for kmh in (49, 501):
        with pytest.raises(IntegrityError):
            await record(hv.customer_id, kmh, vn(2031, 5, 1))
    ref = f"{TAG}dup"
    async with SessionLocal() as s:
        s.add(
            SpeedRecord(
                customer_id=hv.customer_id,
                speed_kmh=100,
                measured_at=vn(2031, 5, 1),
                source_ref=ref,
            )
        )
        await s.commit()
    with pytest.raises(IntegrityError):
        async with SessionLocal() as s:
            s.add(
                SpeedRecord(
                    customer_id=hv.customer_id,
                    speed_kmh=120,
                    measured_at=vn(2031, 5, 2),
                    source_ref=ref,
                )
            )
            await s.commit()


async def test_seed_demo_refuses_production(monkeypatch, capsys):
    monkeypatch.setattr(settings, "ENV", "production")
    assert seed_demo.main([]) == 2
    assert "production" in capsys.readouterr().err


async def test_seed_demo_seeds_and_clears(people):
    hv = await people()
    assert await seed_demo.seed(per_member=2) >= 2
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(SpeedRecord)
            .where(SpeedRecord.customer_id == hv.customer_id, SpeedRecord.device_id == "demo")
        )
    assert n == 2
    assert await seed_demo.seed(per_member=2) >= 2  # chạy lại không trùng
    assert await seed_demo.clear() >= 2

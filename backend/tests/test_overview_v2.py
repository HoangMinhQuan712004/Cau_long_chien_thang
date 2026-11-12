"""T-036: Tổng quan v2 – số liệu tháng, kỷ lục, hạng tháng, phòng đang trống, kỷ lục mới của cụm."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.play_rooms import api as rooms_api
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.helpers_booking import new_court
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, fill, post, room_for
from tests.test_room_tiers import set_range, set_tier

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

OVERVIEW = f"{MA}/overview"
TAG = f"t036:{uuid.uuid4().hex[:8]}:"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.startswith(TAG)))
        await s.commit()


async def record(cid: int, kmh: int, at: datetime, court_code: str | None = None) -> None:
    async with SessionLocal() as s:
        s.add(
            SpeedRecord(
                customer_id=cid,
                speed_kmh=kmh,
                measured_at=at,
                court_code=court_code,
                source_ref=f"{TAG}{uuid.uuid4()}",
            )
        )
        await s.commit()


async def set_profile(cid: int, **values) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Customer).where(Customer.id == cid).values(**values))
        await s.commit()


async def overview(client) -> dict:
    r = await client.get(OVERVIEW)
    assert r.status_code == 200, r.text
    return r.json()


async def test_month_stats_records_ranking_and_etag(staff, admin, people):
    host = await people("Tổng Quan Một")
    room = (await room_for(staff, admin, host.code))["room"]
    await add_match(room.id, 1, [host.customer_id], [-1], win="a")
    now = datetime.now(UTC)
    await record(host.customer_id, 210, now - timedelta(minutes=5))
    await record(host.customer_id, 260, now - timedelta(days=400))  # kỷ lục cũ, ngoài tháng

    r = await host.client.get(OVERVIEW)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache, private" and r.headers["etag"]
    d = r.json()
    local = now.astimezone(settings.tz)
    assert d["month"] == f"{local.year:04d}-{local.month:02d}"
    assert d["month_stats"] == {"sessions": 1, "matches": 1, "wins": 1}
    assert (d["month_record_kmh"], d["record_kmh"]) == (210, 260)
    me = d["ranking"]["me"]
    assert me["speed_kmh"] == 210 and me["rank"] >= 1
    assert d["ranking"]["total_records"] >= 1
    assert len(d["ranking"]["top3"]) <= 3 and d["ranking"]["total_members"] >= 1
    assert all("customer_id" not in row for row in d["ranking"]["top3"])
    # Trường T-018 vẫn còn
    for key in ("greeting_name", "today", "today_count", "upcoming", "unread_count"):
        assert key in d

    again = await host.client.get(OVERVIEW, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


async def test_open_rooms_skip_full_and_mine_keep_tier_block(staff, admin, people):
    viewer = await people("Người Tìm Phòng")
    await set_tier(viewer.customer_id, "Yếu")
    full_host, my_host, free_host = await people(), await people(), await people()
    full = (await room_for(staff, admin, full_host.code))["room"]
    await fill(full.id, 8)  # đủ 8 người -> không hiện
    mine = (await room_for(staff, admin, my_host.code))["room"]
    r = await post(viewer.client, f"/{mine.id}/join-requests", {"version": mine.version})
    assert r.status_code == 200
    d = (await my_host.client.get(f"{MA}/rooms/{mine.id}")).json()
    rid = d["join_requests"][0]["id"]
    r = await post(
        my_host.client, f"/{mine.id}/join-requests/{rid}/approve", {"version": d["version"]}
    )
    assert r.status_code == 200  # viewer đã ở trong -> không hiện
    free = (await room_for(staff, admin, free_host.code))["room"]
    await set_range(free.id, "Khá", None)  # còn chỗ nhưng viewer ngoài khoảng -> vẫn hiện, nút mờ

    async with SessionLocal() as s:
        cards = await rooms_api.open_rooms_today(s, 0, viewer.customer_id, limit=100)
    ids = [c.id for c in cards]
    assert free.id in ids and full.id not in ids and mine.id not in ids
    card = next(c for c in cards if c.id == free.id)
    assert card.my_join_block == "out_of_range" and card.tier_range.min == "Khá"
    assert [c.start_at for c in cards] == sorted(c.start_at for c in cards)

    d = await overview(viewer.client)
    assert len(d["open_rooms"]) <= 3
    assert full.id not in [c["id"] for c in d["open_rooms"]]
    assert mine.id not in [c["id"] for c in d["open_rooms"]]


async def test_recent_club_record_breaks_with_privacy(admin, people):
    p1 = await people("Phá Kỷ Lục Một")
    p2 = await people("Phá Kỷ Lục Hai")
    p3 = await people("Phá Kỷ Lục Ba")
    await set_profile(p1.customer_id, show_on_records=True, racket="Yonex Astrox 88D")
    await set_profile(p2.customer_id, show_on_records=True, racket="Lining")
    await set_profile(p3.customer_id, show_on_records=False, racket="Victor Bí Mật")
    court = await new_court(admin)
    t0 = datetime(2035, 6, 1, 8, tzinfo=UTC)  # sau mọi số đo khác trong DB test

    await record(p1.customer_id, 480, t0)
    await record(p2.customer_id, 470, t0 + timedelta(minutes=1))  # không phá
    await record(p2.customer_id, 490, t0 + timedelta(minutes=2))  # phá +10
    await record(p3.customer_id, 490, t0 + timedelta(minutes=3))  # bằng -> không phá
    await record(p1.customer_id, 495, t0 + timedelta(minutes=4), court["code"])  # phá +5
    await record(p3.customer_id, 500, t0 + timedelta(minutes=5))  # phá +5 (ẩn danh)

    recent = (await overview(p1.client))["recent_records"]
    assert [(r["speed_kmh"], r["delta_kmh"], r["is_current"]) for r in recent] == [
        (500, 5, True),
        (495, 5, False),
        (490, 10, False),
    ]
    hidden, mine, other = recent
    assert hidden["display_name"] == "Hội viên ẩn danh"
    assert hidden["avatar_url"] is None and hidden["racket"] is None
    assert mine["display_name"] == "Phá Kỷ Lục Một" and mine["racket"] == "Yonex Astrox 88D"
    assert mine["resource_name"] == court["name"]
    assert other["display_name"] == "Phá Kỷ Lục Hai" and other["resource_name"] is None
    assert "Victor Bí Mật" not in str(recent) and "customer_id" not in str(recent)

    # Người ẩn danh tự xem: thấy tên + vợt của mình
    recent = (await overview(p3.client))["recent_records"]
    assert recent[0]["display_name"] == "Phá Kỷ Lục Ba" and recent[0]["racket"] == "Victor Bí Mật"


async def test_open_rooms_overview_skip_ongoing(staff, admin, people):
    """Tổng quan: phòng người khác đang diễn ra không vào "Phòng đang trống" (chỉ phòng sắp tới)."""
    viewer = await people("Người Xem Tổng Quan")
    host = await people()
    ongoing = (await room_for(staff, admin, host.code))["room"]  # đặt giờ đang diễn ra
    async with SessionLocal() as s:
        cards = await rooms_api.open_rooms_today(s, 0, viewer.customer_id, limit=100)
        upcoming = await rooms_api.open_rooms_today(
            s, 0, viewer.customer_id, limit=100, upcoming_only=True
        )
    assert ongoing.id in [c.id for c in cards]
    assert ongoing.id not in [c.id for c in upcoming]
    assert all(c.phase == "upcoming" for c in upcoming)
    assert ongoing.id not in [c["id"] for c in (await overview(viewer.client))["open_rooms"]]

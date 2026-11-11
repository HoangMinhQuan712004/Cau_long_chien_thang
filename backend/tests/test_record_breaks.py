"""T-048: dòng thời gian phá kỷ lục (chuỗi + kỳ, ranh giới giờ VN, số ngày giữ, mốc đầu, ẩn danh)
và ngày dán link video (mọi đường ghi ``video_url``)."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records import api as records
from app.modules.records import service
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.test_play_rooms import MA

people = base.people

ADMIN = f"{API}/admin/speed-records"
BREAKS = f"{MA}/record-breaks"
SUBMIT = f"{MA}/speed-records"
TAG = f"t048:{uuid.uuid4().hex[:8]}:"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT2 = "https://youtu.be/9bZkp7q19f0"
MP4 = "https://cdn.example.com/clip.mp4"


def vn(*args: int) -> datetime:
    return datetime(*args, tzinfo=settings.tz)


@pytest.fixture(autouse=True)
async def clean_chain():
    """Chuỗi tính trên cả bảng: bắt đầu và kết thúc với bảng trống (DB test riêng)."""
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()


async def record(
    cid: int,
    kmh: int,
    at: datetime,
    url: str | None = None,
    set_at: datetime | None = None,
    status: str = "approved",
    court: str | None = None,
) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid,
            speed_kmh=kmh,
            measured_at=at,
            court_code=court,
            status=status,
            reject_reason="Không rõ" if status == "rejected" else None,
            source_ref=f"{TAG}{uuid.uuid4()}",
        )
        r.set_video(url, set_at or at)
        s.add(r)
        await s.commit()
        return r.id


async def profile(cid: int, **values) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Customer).where(Customer.id == cid).values(**values))
        await s.commit()


async def breaks(viewer: int, period: str, today: date):
    async with SessionLocal() as s:
        return await service.record_breaks(s, viewer, period, today)


async def stored(record_id: int) -> SpeedRecord:
    async with SessionLocal() as s:
        return await s.scalar(select(SpeedRecord).where(SpeedRecord.id == record_id))


async def set_at_of(record_id: int) -> datetime | None:
    return (await stored(record_id)).video_set_at


async def backdate(record_id: int, at: datetime) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(SpeedRecord).where(SpeedRecord.id == record_id).values(video_set_at=at)
        )
        await s.commit()


async def item_of(client, record_id: int) -> dict:
    r = await client.get(BREAKS)
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["id"] == record_id)


async def test_chain_delta_previous_held_days_and_baseline(people):
    a, b = await people("Người A"), await people("Người B")
    first = await record(a.customer_id, 200, vn(2026, 3, 1, 10))
    await record(b.customer_id, 190, vn(2026, 3, 3, 10))  # thấp hơn -> không phải lần phá
    await record(b.customer_id, 200, vn(2026, 3, 4, 10))  # bằng -> không phải lần phá
    second = await record(b.customer_id, 210, vn(2026, 3, 5, 0))
    third = await record(a.customer_id, 230, vn(2026, 3, 5, 23, 59))

    got = await breaks(a.customer_id, "all", date(2026, 3, 10))
    assert (got.period, got.start, got.end) == ("all", None, None)
    assert [i.id for i in got.items] == [third, second, first]  # mới nhất trước
    assert [i.speed_kmh for i in got.items] == [230, 210, 200]
    assert [i.delta_kmh for i in got.items] == [20, 10, None]
    assert [i.previous_kmh for i in got.items] == [210, 200, None]
    assert [i.is_current for i in got.items] == [True, False, False]
    assert [i.is_baseline for i in got.items] == [False, False, True]
    # Theo ngày giờ VN: cùng ngày (cách nhau gần 24 giờ) -> 0; đang giữ tính tới hôm nay
    assert [i.held_days for i in got.items] == [5, 0, 4]
    assert [i.is_me for i in got.items] == [True, False, True]


async def test_chain_matches_overview_breaks(people):
    """Dùng chung một cách tính với "Kỷ lục mới" (T-036)."""
    a = await people("Người A")
    for kmh, day in ((200, 1), (190, 2), (220, 3), (220, 4), (240, 5)):
        await record(a.customer_id, kmh, vn(2026, 3, day, 12))
    got = await breaks(a.customer_id, "all", date(2026, 3, 10))
    async with SessionLocal() as s:
        overview = await records.club_record_breaks(s, a.customer_id, 3)
    assert [i.speed_kmh for i in got.items] == [240, 220, 200]
    assert [(b.speed_kmh, b.delta_kmh, b.is_current) for b in overview] == [
        (i.speed_kmh, i.delta_kmh, i.is_current) for i in got.items
    ]


async def test_period_filters_on_vn_day_and_keeps_whole_chain_values(people):
    a = await people("Người A")
    baseline = await record(a.customer_id, 200, vn(2026, 3, 8, 23, 59, 59))  # CN tuần trước
    monday = await record(a.customer_id, 210, vn(2026, 3, 9))  # 00:00 T2 -> vào tuần
    sunday = await record(a.customer_id, 220, vn(2026, 3, 15, 23, 59, 59))
    next_week = await record(a.customer_id, 230, vn(2026, 3, 16))

    week = await breaks(a.customer_id, "week", date(2026, 3, 15))
    assert (week.start, week.end) == (date(2026, 3, 9), date(2026, 3, 15))
    assert [i.id for i in week.items] == [sunday, monday]
    # Kỷ lục trước nằm ngoài kỳ vẫn được tính; lần đầu trong kỳ không thành mốc đầu
    assert (week.items[1].delta_kmh, week.items[1].previous_kmh) == (10, 200)
    assert not any(i.is_baseline or i.is_current for i in week.items)
    assert week.items[0].held_days == 1  # giữ tới lần phá ngoài kỳ, không tới cuối kỳ

    month = await breaks(a.customer_id, "month", date(2026, 3, 15))
    assert (month.start, month.end) == (date(2026, 3, 1), date(2026, 3, 31))
    assert [i.id for i in month.items] == [next_week, sunday, monday]  # không có mốc đầu
    assert month.items[0].is_current and month.items[0].held_days == 0  # đo sau hôm nay -> không âm

    year = await breaks(a.customer_id, "year", date(2026, 3, 15))
    assert (year.start, year.end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert baseline not in [i.id for i in year.items]

    everything = await breaks(a.customer_id, "all", date(2026, 3, 15))
    assert everything.items[-1].id == baseline and everything.items[-1].is_baseline


async def test_period_with_only_baseline_or_no_break_is_empty(people):
    a = await people("Người A")
    await record(a.customer_id, 200, vn(2026, 3, 8, 12))
    assert (await breaks(a.customer_id, "week", date(2026, 3, 8))).items == []
    assert (await breaks(a.customer_id, "week", date(2026, 4, 8))).items == []
    only = (await breaks(a.customer_id, "all", date(2026, 3, 8))).items
    assert len(only) == 1 and only[0].is_baseline and only[0].is_current


async def test_card_fields_and_anonymity(admin, people):
    court = await base.new_court(admin)
    shown, hidden = await people("Hiện Tên"), await people("Ẩn Tên")
    await profile(
        shown.customer_id, show_on_records=True, nickname="Sấm Sét", tier="Khá", racket="Yonex 99"
    )
    await profile(
        hidden.customer_id, show_on_records=False, nickname="Bí Mật", tier="Yếu", racket="Lining"
    )
    at = datetime.now(UTC) - timedelta(days=2)
    low = await record(shown.customer_id, 200, at, court=court["code"])
    high = await record(hidden.customer_id, 250, at + timedelta(hours=1), url=YT)

    # Người khác xem: lần của người ẩn danh chỉ còn số đo + video
    other = await people("Người Xem")
    r = await other.client.get(BREAKS)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert d["period"] == "all" and d["start"] is None and d["end"] is None
    anon, open_card = d["items"]
    assert anon["id"] == high and open_card["id"] == low
    assert anon["display_name"] == "Hội viên ẩn danh"
    for key in ("nickname", "tier", "avatar_url", "racket"):
        assert anon[key] is None, key
    assert anon["video"]["kind"] == "youtube" and anon["video"]["embed_url"]
    assert "Bí Mật" not in r.text and "Lining" not in r.text and "Ẩn Tên" not in r.text
    assert "customer_id" not in anon and "public_id" not in anon
    assert open_card["display_name"] == "Hiện Tên"
    assert open_card["nickname"] == "Sấm Sét" and open_card["tier"] == "Khá"
    assert open_card["racket"] == "Yonex 99" and open_card["resource_name"] == court["name"]
    assert open_card["video"] is None and open_card["is_me"] is False
    # Không thuộc phòng chơi nào / ẩn danh -> không có thắng thua
    assert open_card["play_stats"] is None and anon["play_stats"] is None

    # Mình luôn thấy thẻ của mình dù đang ẩn
    mine = await item_of(hidden.client, high)
    assert mine["is_me"] and mine["display_name"] == "Ẩn Tên"
    assert (mine["nickname"], mine["tier"], mine["racket"]) == ("Bí Mật", "Yếu", "Lining")


async def test_full_name_only_on_this_api_and_only_when_shown(people):
    """Người dùng chốt 06/11: màn này hiện họ tên + biệt danh; API khác vẫn là biệt danh."""
    named, plain, hidden = (
        await people("Họ Tên Thật"),
        await people("Không Biệt Danh"),
        await people("Tên Bị Ẩn"),
    )
    await profile(named.customer_id, show_on_records=True, nickname="Sấm Sét")
    await profile(plain.customer_id, show_on_records=True, nickname=None)
    await profile(hidden.customer_id, show_on_records=False, nickname="Bí Mật")
    now = datetime.now(UTC) - timedelta(minutes=10)
    await record(plain.customer_id, 200, now)
    await record(hidden.customer_id, 210, now + timedelta(minutes=1))
    await record(named.customer_id, 220, now + timedelta(minutes=2), url=YT)

    viewer = await people("Người Xem")
    r = await viewer.client.get(BREAKS)
    assert [(i["display_name"], i["nickname"]) for i in r.json()["items"]] == [
        ("Họ Tên Thật", "Sấm Sét"),
        ("Hội viên ẩn danh", None),
        ("Không Biệt Danh", None),
    ]
    assert "Tên Bị Ẩn" not in r.text and "Bí Mật" not in r.text

    # Chính mình dù đang ẩn: họ tên + biệt danh
    r = await hidden.client.get(BREAKS)
    assert (r.json()["items"][1]["display_name"], r.json()["items"][1]["nickname"]) == (
        "Tên Bị Ẩn",
        "Bí Mật",
    )

    # Các API khác giữ "biệt danh, không có mới đến họ tên"
    async with SessionLocal() as s:
        overview = await records.club_record_breaks(s, viewer.customer_id, 3)
    assert overview[0].display_name == "Sấm Sét"
    r = await viewer.client.get(f"{MA}/record-videos", params={"period": "all"})
    assert r.json()["items"][0]["display_name"] == "Sấm Sét"
    day = now.astimezone(settings.tz).date().isoformat()
    r = await viewer.client.get(f"{MA}/speed-ranking", params={"period": "month", "date": day})
    assert r.json()["top"][0]["display_name"] == "Sấm Sét"
    assert "Họ Tên Thật" not in r.text


async def test_only_approved_and_eligible_members_enter_the_chain(admin, people):
    a, b = await people("Người A"), await people("Người B")
    at = datetime.now(UTC) - timedelta(days=5)
    base_id = await record(a.customer_id, 200, at)
    await record(a.customer_id, 480, at + timedelta(hours=1), status="pending")
    await record(a.customer_id, 490, at + timedelta(hours=2), status="rejected")
    theirs = await record(b.customer_id, 300, at + timedelta(hours=3))
    r = await a.client.get(BREAKS)
    assert [i["speed_kmh"] for i in r.json()["items"]] == [300, 200]

    # Hội viên Ngừng ra khỏi chuỗi (cùng điều kiện Bảng xếp hạng)
    await profile(b.customer_id, is_active=False)
    r = await a.client.get(BREAKS)
    items = r.json()["items"]
    assert [i["id"] for i in items] == [base_id] and theirs not in [i["id"] for i in items]
    assert items[0]["is_current"] is True


async def test_label_date_follows_latest_paste(admin, people):
    hv = await people("Người Dán")
    measured = vn(2026, 1, 5, 10)
    rid = await record(hv.customer_id, 300, measured)
    item = await item_of(hv.client, rid)
    assert item["video"] is None and item["label_date"] == "2026-01-05"  # chưa có video: ngày đo

    # Gắn link: ngày dán là hôm nay
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": YT}, headers=idem())
    assert r.status_code == 200, r.text
    today = datetime.now(settings.tz).date().isoformat()
    assert (await item_of(hv.client, rid))["label_date"] == today

    # Dán lại đúng link cũ: không đổi ngày. Ranh giới: 17:00 UTC đã là hôm sau giờ VN
    old = datetime(2026, 2, 1, 17, tzinfo=UTC)
    await backdate(rid, old)
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": f"  {YT} "}, headers=idem())
    assert r.status_code == 200, r.text
    assert await set_at_of(rid) == old
    assert (await item_of(hv.client, rid))["label_date"] == "2026-02-02"

    # Sửa link: theo lần dán mới nhất
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": YT2}, headers=idem())
    assert r.status_code == 200, r.text
    assert (await item_of(hv.client, rid))["label_date"] == today

    # Gỡ link: xóa ngày, nhãn về ngày đo
    r = await admin.delete(f"{ADMIN}/{rid}/video", headers=idem())
    assert r.status_code == 200, r.text
    assert await set_at_of(rid) is None
    item = await item_of(hv.client, rid)
    assert item["video"] is None and item["label_date"] == "2026-01-05"


async def test_admin_manual_paths_write_paste_date(admin, people):
    hv = await people("Admin Nhập")
    at = datetime.now(UTC) - timedelta(days=3)
    body = {
        "member_code": hv.code,
        "wins": 1,
        "losses": 0,
        "speed_kmh": 300,
        "measured_at": at.isoformat(),
    }

    # Admin thêm số đo có / không có video
    r = await admin.post(ADMIN, json={**body, "video_url": f" {YT} "}, headers=idem())
    assert r.status_code == 201, r.text
    with_video = r.json()
    assert await set_at_of(with_video["id"]) is not None
    r = await admin.post(ADMIN, json={**body, "speed_kmh": 200}, headers=idem())
    assert r.status_code == 201, r.text
    no_video = r.json()
    assert await set_at_of(no_video["id"]) is None

    # PATCH thêm link
    r = await admin.patch(
        f"{ADMIN}/{no_video['id']}", json={"version": 1, "video_url": MP4}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert await set_at_of(no_video["id"]) is not None

    # PATCH giữ nguyên link (dù đổi ô khác): không đổi ngày
    old = datetime(2026, 2, 1, tzinfo=UTC)
    await backdate(with_video["id"], old)
    r = await admin.patch(
        f"{ADMIN}/{with_video['id']}",
        json={"version": with_video["version"], "speed_kmh": 310, "video_url": f" {YT} "},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["speed_kmh"] == 310, r.text
    assert await set_at_of(with_video["id"]) == old

    # PATCH đổi link: ngày mới. PATCH null: gỡ
    r = await admin.patch(
        f"{ADMIN}/{with_video['id']}",
        json={"version": r.json()["version"], "video_url": YT2},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert await set_at_of(with_video["id"]) > old
    r = await admin.patch(
        f"{ADMIN}/{with_video['id']}",
        json={"version": r.json()["version"], "video_url": None},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["video"] is None, r.text
    assert await set_at_of(with_video["id"]) is None


async def test_member_submit_keeps_paste_date_after_approval(admin, people):
    hv = await people("Hội Viên Gửi")
    at = datetime.now(UTC) - timedelta(days=3)
    r = await hv.client.post(
        SUBMIT,
        json={
            "wins": 1,
            "losses": 0,
            "speed_kmh": 300,
            "measured_at": at.isoformat(),
            "video_url": YT,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (await hv.client.get(BREAKS)).json()["items"] == []  # chờ duyệt: chưa vào chuỗi

    old = datetime(2026, 2, 1, 17, tzinfo=UTC)
    await backdate(rid, old)
    r = await admin.post(f"{ADMIN}/{rid}/approve", headers=idem())
    assert r.status_code == 200, r.text
    assert await set_at_of(rid) == old
    assert (await item_of(hv.client, rid))["label_date"] == "2026-02-02"


async def test_member_submit_play_result_shows_on_card(admin, people):
    """Thắng / thua bắt buộc khi gửi, lên thẻ kỷ lục (ưu tiên); thiếu / tổng 0 / quá 99 -> 422."""
    hv = await people("Gửi Thắng Thua")
    await profile(hv.customer_id, show_on_records=False)
    at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    for bad in (
        {},
        {"wins": 3},
        {"losses": 1},
        {"wins": 0, "losses": 0},
        {"wins": 100, "losses": 1},
    ):
        r = await hv.client.post(
            SUBMIT, json={"speed_kmh": 310, "measured_at": at, **bad}, headers=idem()
        )
        assert r.status_code == 422, bad
    r = await hv.client.post(
        SUBMIT, json={"speed_kmh": 310, "measured_at": at, "wins": 3, "losses": 1}, headers=idem()
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (await admin.post(f"{ADMIN}/{rid}/approve", headers=idem())).status_code == 200
    stats = (await item_of(hv.client, rid))["play_stats"]
    assert stats == {"start_at": None, "end_at": None, "matches": 4, "wins": 3, "losses": 1}
    # Người khác xem lần của người ẩn danh: không lộ thắng / thua
    other = await people("Người Xem Thắng Thua")
    assert (await item_of(other.client, rid))["play_stats"] is None


async def test_constraint_rejects_link_without_date_and_date_without_link(people):
    hv = await people("Ràng Buộc")
    at = datetime.now(UTC)
    for values in ({"video_url": YT}, {"video_set_at": at}):
        with pytest.raises(IntegrityError, match="speed_video_set_at"):
            async with SessionLocal() as s:
                s.add(
                    SpeedRecord(
                        customer_id=hv.customer_id,
                        speed_kmh=200,
                        measured_at=at,
                        source_ref=f"{TAG}{uuid.uuid4()}",
                        **values,
                    )
                )
                await s.commit()


async def test_demo_breaks_paste_video_a_day_after_measuring(people):
    hv = await people("Mẫu")
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        await records.seed_demo_breaks(s, [hv.customer_id, hv.customer_id], now, [YT])
        await s.commit()
        rows = list(await s.scalars(select(SpeedRecord).order_by(SpeedRecord.speed_kmh)))
    assert rows[0].video_set_at == rows[0].measured_at + timedelta(days=1)
    assert rows[0].video_set_at <= now
    assert rows[1].video_url is None and rows[1].video_set_at is None


async def test_access_and_bad_period(anon, staff, people):
    assert (await anon.get(BREAKS)).status_code == 401
    assert (await staff.get(BREAKS)).status_code in (401, 403)
    hv = await people("Người Xem")
    assert (await hv.client.get(BREAKS, params={"period": "day"})).status_code == 422
    empty = await hv.client.get(BREAKS, params={"period": "week"})
    assert empty.status_code == 200 and empty.json()["items"] == []
    assert empty.json()["start"] is not None and empty.json()["end"] is not None

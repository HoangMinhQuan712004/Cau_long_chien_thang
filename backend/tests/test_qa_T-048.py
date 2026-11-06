# ruff: noqa: E501
"""QA T-048 (API: AC10, AC11 + hồi quy T-036 / T-046 / T-047): dòng thời gian phá kỷ lục `record-breaks`.

Bổ sung cho ``test_record_breaks.py`` của BACKEND: đi qua HTTP thật (đồng hồ thật), chuỗi tối đa 451 dòng,
kỳ theo ranh giới giờ VN qua API, xóa/sửa giữa chuỗi, duyệt/từ chối, rò rỉ dữ liệu, quyền, tham số sai.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import delete, insert, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.test_play_rooms import MA

people = base.people
ADMIN = f"{API}/admin/speed-records"
BREAKS = f"{MA}/record-breaks"
SUBMIT = f"{MA}/speed-records"
TAG = f"qa048:{uuid.uuid4().hex[:8]}:"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT2 = "https://youtu.be/9bZkp7q19f0"


@pytest.fixture(autouse=True)
async def clean_chain():
    """Chuỗi tính trên cả bảng -> bắt đầu và kết thúc với bảng trống (DB test riêng)."""
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()


def vn(day: date, hh: int = 12, mm: int = 0, ss: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm, ss), settings.tz)


def today_vn() -> date:
    return datetime.now(settings.tz).date()


async def put(cid: int, kmh: int, at: datetime, url: str | None = None, **kw) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid,
            speed_kmh=kmh,
            measured_at=at,
            source_ref=f"{TAG}{uuid.uuid4()}",
            status=kw.pop("status", "approved"),
            **kw,
        )
        r.set_video(url, at)
        s.add(r)
        await s.commit()
        return r.id


async def get_breaks(client, period: str | None = None) -> dict:
    r = await client.get(BREAKS, params={"period": period} if period else None)
    assert r.status_code == 200, r.text
    return r.json()


def body(hv, kmh: int, at: datetime, **kw) -> dict:
    return {
        "member_code": hv.code,
        "speed_kmh": kmh,
        "measured_at": at.astimezone(UTC).isoformat(),
        **kw,
    }


# ---------------------------------------------------------------- quyền / tham số


async def test_access_and_period_parameter(anon, admin, staff, people):
    hv = await people("QA Quyền T48")
    assert (await anon.get(BREAKS)).status_code == 401
    for who in (admin, staff):  # tài khoản quản trị không phải hội viên
        assert (await who.get(BREAKS)).status_code in (401, 403)
    for ok in ("week", "month", "year", "all"):
        r = await hv.client.get(BREAKS, params={"period": ok})
        assert r.status_code == 200 and r.json()["period"] == ok
    assert (await hv.client.get(BREAKS)).json()["period"] == "all"
    for bad in ("day", "WEEK", "", "all;", "weeks", "0", "week,month"):
        assert (await hv.client.get(BREAKS, params={"period": bad})).status_code == 422, bad
    # Chỉ GET: ghi bị chặn
    r = await hv.client.post(BREAKS, headers=idem())
    assert r.status_code in (404, 405)
    assert (await hv.client.get(BREAKS)).headers["cache-control"] == "no-store"


async def test_empty_chain_returns_empty_items(people):
    hv = await people("QA Chuỗi Rỗng")
    for p in ("week", "month", "year", "all"):
        d = await get_breaks(hv.client, p)
        assert d["items"] == [], p
    d = await get_breaks(hv.client, "week")
    assert d["start"] is not None and d["end"] is not None
    assert (date.fromisoformat(d["end"]) - date.fromisoformat(d["start"])).days == 6
    assert date.fromisoformat(d["start"]).weekday() == 0, "tuần bắt đầu thứ Hai"


# ---------------------------------------------------------------- kỳ theo ranh giới giờ VN (đồng hồ thật)


async def test_ac_period_boundaries_with_real_clock(people):
    hv = await people("QA Ranh Giới T48")
    today = today_vn()
    wk = today - timedelta(days=today.weekday())
    mo = today.replace(day=1)
    yr = date(today.year, 1, 1)
    pts = [
        (200, vn(yr - timedelta(days=1), 23, 59, 59)),  # 31/12 năm trước 23:59:59
        (210, vn(yr, 0, 0, 0)),  # 00:00 01/01
        (220, vn(mo - timedelta(days=1), 23, 59, 59)) if mo > yr else None,
        (230, vn(mo, 0, 0, 0)) if mo > yr else None,
        (240, vn(wk - timedelta(days=1), 23, 59, 59)) if wk > mo else None,
        (250, vn(wk, 0, 0, 0)) if wk > mo else None,
    ]
    ids = {}
    for kmh, at in (p for p in pts if p):
        ids[kmh] = await put(hv.customer_id, kmh, at)
    # lần phá hôm nay (trước bây giờ để không bị coi là tương lai)
    ids[300] = await put(hv.customer_id, 300, datetime.now(settings.tz) - timedelta(minutes=1))

    allp = await get_breaks(hv.client, "all")
    assert [i["speed_kmh"] for i in allp["items"]] == sorted(ids, reverse=True)
    assert allp["items"][-1]["is_baseline"] and sum(i["is_baseline"] for i in allp["items"]) == 1
    assert allp["items"][0]["is_current"] and sum(i["is_current"] for i in allp["items"]) == 1

    def speeds(d):
        return [i["speed_kmh"] for i in d["items"]]

    year = await get_breaks(hv.client, "year")
    assert 200 not in speeds(year) and 210 in speeds(year), (
        "01/01 00:00 thuộc năm mới, 31/12 23:59:59 thì không"
    )
    assert not any(i["is_baseline"] for i in year["items"]), "mốc đầu chỉ ở 'Mọi thời gian'"
    month = await get_breaks(hv.client, "month")
    assert 300 in speeds(month) and 200 not in speeds(month)
    if mo > yr:
        assert 230 in speeds(month) and 220 not in speeds(month) and 210 not in speeds(month)
    week = await get_breaks(hv.client, "week")
    assert 300 in speeds(week)
    if wk > mo:
        assert 250 in speeds(week) and 240 not in speeds(week)
    # Giá trị tính trên toàn chuỗi dù kỳ hẹp hơn
    top = week["items"][0]
    assert top["speed_kmh"] == 300 and top["previous_kmh"] == max(k for k in ids if k < 300)
    assert top["delta_kmh"] == 300 - top["previous_kmh"] and top["is_current"] is True
    for d in (year, month, week, allp):
        assert all(i["held_days"] >= 0 for i in d["items"])
        assert all(i["is_baseline"] is False or i["delta_kmh"] is None for i in d["items"])


async def test_full_chain_of_451_rows_has_no_pagination_and_stays_ordered(people):
    hv = await people("QA Chuỗi Dài")
    base_t = datetime.now(UTC) - timedelta(days=300)
    async with SessionLocal() as s:
        await s.execute(
            insert(SpeedRecord),
            [
                {
                    "customer_id": hv.customer_id,
                    "speed_kmh": kmh,
                    "measured_at": base_t + timedelta(minutes=kmh),
                    "source_ref": f"{TAG}{kmh}",
                }
                for kmh in range(50, 501)
            ],
        )
        await s.commit()
    d = await get_breaks(hv.client, "all")
    assert len(d["items"]) == 451
    assert [i["speed_kmh"] for i in d["items"]] == list(range(500, 49, -1))
    assert d["items"][-1]["is_baseline"] and d["items"][-1]["delta_kmh"] is None
    assert all(i["delta_kmh"] == 1 for i in d["items"][:-1])
    assert sum(i["is_current"] for i in d["items"]) == 1 and d["items"][0]["is_current"]
    # kỳ: 300 ngày trước → nằm rải rác, nhưng tổng các kỳ không vượt chuỗi
    year = await get_breaks(hv.client, "year")
    assert len(year["items"]) <= 450 and all(i["delta_kmh"] == 1 for i in year["items"])


# ---------------------------------------------------------------- AC10: ngày dán link qua HTTP thật


async def test_ac10_label_date_end_to_end_through_admin_and_member_api(admin, people):
    hv = await people("QA Ngày Dán")
    viewer = await people("QA Người Xem Dán")
    at = datetime.now(UTC) - timedelta(days=3)
    created = await admin.post(ADMIN, json=body(hv, 200, at, video_url=YT), headers=idem())
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    item = (await get_breaks(viewer.client))["items"][0]
    assert item["id"] == rid and item["label_date"] == today_vn().isoformat(), (
        "ngày dán = hôm nay, không phải ngày đo"
    )
    assert abs(datetime.fromisoformat(item["measured_at"]) - at) < timedelta(seconds=1)

    # Lùi ngày dán (như dòng cũ) để thấy sửa link / dán lại có hiệu lực
    old = datetime.now(UTC) - timedelta(days=10)
    async with SessionLocal() as s:
        await s.execute(update(SpeedRecord).where(SpeedRecord.id == rid).values(video_set_at=old))
        await s.commit()
    old_day = old.astimezone(settings.tz).date().isoformat()
    ver = created.json()["version"]
    # Dán lại đúng link cũ (có khoảng trắng thừa): không đổi ngày, không tăng version
    r = await admin.patch(
        f"{ADMIN}/{rid}", json={"version": ver, "video_url": f"  {YT}  "}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (await get_breaks(viewer.client))["items"][0]["label_date"] == old_day
    # Đổi sang link khác: ngày dán = hôm nay
    r = await admin.patch(
        f"{ADMIN}/{rid}", json={"version": r.json()["version"], "video_url": YT2}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (await get_breaks(viewer.client))["items"][0]["label_date"] == today_vn().isoformat()
    # Gỡ link: về ngày đo, video null
    r = await admin.patch(
        f"{ADMIN}/{rid}", json={"version": r.json()["version"], "video_url": None}, headers=idem()
    )
    assert r.status_code == 200, r.text
    got = (await get_breaks(viewer.client))["items"][0]
    assert (
        got["video"] is None and got["label_date"] == at.astimezone(settings.tz).date().isoformat()
    )
    # PUT video lại (T-046) -> hôm nay; DELETE -> về ngày đo
    assert (
        await admin.put(f"{ADMIN}/{rid}/video", json={"url": YT}, headers=idem())
    ).status_code == 200
    assert (await get_breaks(viewer.client))["items"][0]["label_date"] == today_vn().isoformat()
    assert (await admin.delete(f"{ADMIN}/{rid}/video", headers=idem())).status_code in (200, 204)
    assert (await get_breaks(viewer.client))["items"][0]["video"] is None


async def test_ac10_member_submission_with_video_keeps_paste_date_after_approval(admin, people):
    hv = await people("QA Gửi Có Video")
    viewer = await people("QA Xem Duyệt")
    at = datetime.now(UTC) - timedelta(days=2)
    r = await hv.client.post(
        SUBMIT,
        json={"speed_kmh": 260, "measured_at": at.isoformat(), "video_url": YT},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert (await get_breaks(viewer.client))["items"] == [], "pending chưa vào chuỗi"
    # Giả lập duyệt muộn: lùi ngày dán 5 ngày, rồi duyệt hôm nay
    old = datetime.now(UTC) - timedelta(days=5)
    async with SessionLocal() as s:
        await s.execute(update(SpeedRecord).where(SpeedRecord.id == rid).values(video_set_at=old))
        await s.commit()
    assert (await admin.post(f"{ADMIN}/{rid}/approve", headers=idem())).status_code == 200
    item = (await get_breaks(viewer.client))["items"][0]
    assert (
        item["id"] == rid and item["label_date"] == old.astimezone(settings.tz).date().isoformat()
    )
    assert item["video"]["url"] == YT


async def test_ac11_pending_and_rejected_never_enter_chain_and_decisions_recompute_it(
    admin, people
):
    a, b = await people("QA Chuỗi A"), await people("QA Chuỗi B")
    now = datetime.now(UTC)
    first = await put(a.customer_id, 200, now - timedelta(days=5))
    pend = await b.client.post(
        SUBMIT,
        json={"speed_kmh": 300, "measured_at": (now - timedelta(days=1)).isoformat()},
        headers=idem(),
    )
    assert pend.status_code == 201
    rej = await b.client.post(
        SUBMIT,
        json={"speed_kmh": 310, "measured_at": (now - timedelta(days=1)).isoformat()},
        headers=idem(),
    )
    assert (
        await admin.post(
            f"{ADMIN}/{rej.json()['id']}/reject", json={"reason": "mờ"}, headers=idem()
        )
    ).status_code == 200
    d = await get_breaks(a.client)
    assert [i["id"] for i in d["items"]] == [first] and d["items"][0]["is_current"]
    approved = await admin.post(f"{ADMIN}/{pend.json()['id']}/approve", headers=idem())
    assert approved.status_code == 200
    d = await get_breaks(a.client)
    assert [i["speed_kmh"] for i in d["items"]] == [300, 200]
    assert d["items"][0]["delta_kmh"] == 100 and d["items"][0]["previous_kmh"] == 200
    assert [i["is_current"] for i in d["items"]] == [True, False]
    # Admin xóa lần phá giữa chuỗi: chuỗi tính lại
    mid = await admin.post(ADMIN, json=body(a, 250, now - timedelta(days=3)), headers=idem())
    assert mid.status_code == 201
    # 250 đo trước 300 nhưng sau 200: chuỗi 200 -> 250 -> 300
    d = await get_breaks(a.client)
    assert [(i["speed_kmh"], i["delta_kmh"]) for i in d["items"]] == [
        (300, 50),
        (250, 50),
        (200, None),
    ]
    assert (await admin.delete(f"{ADMIN}/{mid.json()['id']}", headers=idem())).status_code == 204
    d = await get_breaks(a.client)
    assert [(i["speed_kmh"], i["delta_kmh"]) for i in d["items"]] == [(300, 100), (200, None)]
    # Sửa tốc độ bản mới nhất xuống dưới kỷ lục cũ: không còn là lần phá
    r = await admin.patch(
        f"{ADMIN}/{pend.json()['id']}",
        json={"version": approved.json()["version"], "speed_kmh": 150},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    d = await get_breaks(a.client)
    assert [i["speed_kmh"] for i in d["items"]] == [200]
    assert d["items"][0]["is_current"] and d["items"][0]["is_baseline"]


# ---------------------------------------------------------------- AC11: riêng tư / họ tên


async def test_ac11_privacy_toggle_and_no_identifier_leak(admin, people):
    shown, hidden, viewer = (
        await people("QA Họ Tên Hiện"),
        await people("QA Họ Tên Ẩn"),
        await people("QA Người Xem Riêng"),
    )
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == shown.customer_id)
            .values(
                show_on_records=True, nickname="Biệt Danh Hiện", tier="Khá", racket="Racket Hiện"
            )
        )
        await s.execute(
            update(Customer)
            .where(Customer.id == hidden.customer_id)
            .values(show_on_records=False, nickname="Biệt Danh Ẩn", tier="Yếu", racket="Racket Ẩn")
        )
        await s.commit()
    now = datetime.now(UTC)
    await put(shown.customer_id, 200, now - timedelta(days=2))
    await put(hidden.customer_id, 220, now - timedelta(days=1), url=YT)
    r = await viewer.client.get(BREAKS)
    text = r.text
    assert "QA Họ Tên Ẩn" not in text and "Biệt Danh Ẩn" not in text and "Racket Ẩn" not in text
    for secret in (
        viewer.phone,
        shown.phone,
        hidden.phone,
        hidden.code,
        "customer_id",
        "public_id",
        "email",
        "phone",
    ):
        assert secret not in text, secret
    items = r.json()["items"]
    assert (items[0]["display_name"], items[0]["nickname"]) == ("Hội viên ẩn danh", None)
    assert items[0]["video"] is not None, "ẩn danh vẫn phát video"
    assert (
        items[1]["display_name"],
        items[1]["nickname"],
        items[1]["tier"],
        items[1]["racket"],
    ) == (
        "QA Họ Tên Hiện",
        "Biệt Danh Hiện",
        "Khá",
        "Racket Hiện",
    )
    # Người ẩn bật hiện -> lộ họ tên; tắt lại -> ẩn ngay
    for flag, expected in ((True, "QA Họ Tên Ẩn"), (False, "Hội viên ẩn danh")):
        async with SessionLocal() as s:
            await s.execute(
                update(Customer)
                .where(Customer.id == hidden.customer_id)
                .values(show_on_records=flag)
            )
            await s.commit()
        got = (await get_breaks(viewer.client))["items"][0]
        assert got["display_name"] == expected, flag
        assert (got["nickname"] is not None) == flag
    # Hội viên Ngừng không vào chuỗi
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hidden.customer_id).values(is_active=False)
        )
        await s.commit()
    items = (await get_breaks(viewer.client))["items"]
    assert [i["speed_kmh"] for i in items] == [200]


async def test_ac11_other_screens_keep_nickname_only(admin, people):
    """Tổng quan, Bảng xếp hạng, Video & kỷ lục cũ vẫn chỉ hiện biệt danh (không họ tên)."""
    named, viewer = await people("QA Họ Tên Thật Khác"), await people("QA Người Xem Khác")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == named.customer_id)
            .values(show_on_records=True, nickname="Biệt Danh Thôi")
        )
        await s.commit()
    now = datetime.now(UTC) - timedelta(minutes=30)
    await put(named.customer_id, 280, now, url=YT)
    assert (await get_breaks(viewer.client))["items"][0]["display_name"] == "QA Họ Tên Thật Khác"
    ov = (await viewer.client.get(f"{MA}/overview")).json()
    rank = (
        await viewer.client.get(
            f"{MA}/speed-ranking", params={"period": "month", "date": today_vn().isoformat()}
        )
    ).text
    vids = (await viewer.client.get(f"{MA}/record-videos", params={"period": "all"})).text
    assert "Biệt Danh Thôi" in str(ov["recent_records"])
    for text in (str(ov), rank, vids):
        assert "QA Họ Tên Thật Khác" not in text
    assert "Biệt Danh Thôi" in rank and "Biệt Danh Thôi" in vids

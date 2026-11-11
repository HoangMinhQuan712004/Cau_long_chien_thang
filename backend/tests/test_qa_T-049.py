# ruff: noqa: E501
"""QA T-049 (API: AC6, AC7 + hồi quy T-030 / T-036): Bảng xếp hạng trả ``measured_at`` + ``video`` của đúng số đo xếp hạng.

Bổ sung cho ``test_speed_ranking.py`` của BACKEND: qua HTTP thật với nhiều kỳ, khối "Hạng của tôi" (trong và ngoài top 10),
Admin gắn / gỡ / sửa qua API, mp4, Tổng quan top3, rò rỉ danh tính của người ẩn danh.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, _rate_limit_backend, idem
from tests.test_play_rooms import MA

people = base.people
RANKING = f"{MA}/speed-ranking"
ADMIN = f"{API}/admin/speed-records"
TAG = f"qa049:{uuid.uuid4().hex[:8]}:"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT2 = "https://youtu.be/9bZkp7q19f0"
MP4 = "https://cdn.example.com/clips/shot.mp4"
_made: list[int] = []


async def person(people, name: str):
    hv = await people(name)
    _made.append(hv.customer_id)
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hv.customer_id).values(show_on_records=True)
        )
        await s.commit()
    return hv


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.customer_id.in_(_made)))
        await s.commit()
    _made.clear()


def vn(y: int, m: int, d: int, h: int = 10) -> datetime:
    return datetime(y, m, d, h, tzinfo=settings.tz)


async def rec(
    cid: int, kmh: int, at: datetime, url: str | None = None, status: str = "approved"
) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid,
            speed_kmh=kmh,
            measured_at=at,
            source_ref=f"{TAG}{uuid.uuid4()}",
            status=status,
            reject_reason="x" if status == "rejected" else None,
        )
        r.set_video(url, at)
        s.add(r)
        await s.commit()
        return r.id


async def rank(client, period: str, day: str) -> dict:
    r = await client.get(RANKING, params={"period": period, "date": day})
    assert r.status_code == 200, r.text
    return r.json()


def row_of(data: dict, name: str) -> dict:
    return next(r for r in data["top"] if r["display_name"] == name)


# ---------------------------------------------------------------- AC6: video theo kỳ


async def test_ac6_video_follows_the_ranked_record_of_each_period(people):
    a = await person(people, "QA Đổi Kỳ")
    viewer = await person(people, "QA Xem Đổi Kỳ")
    # tuần 07–13/03/2033: 210 (có video) rồi 260 (không video); tháng còn có 300 (video khác) ở tuần sau
    await rec(a.customer_id, 210, vn(2033, 3, 9), YT)
    await rec(a.customer_id, 260, vn(2033, 3, 11))
    await rec(a.customer_id, 300, vn(2033, 3, 22), YT2)
    wk = await rank(viewer.client, "week", "2033-03-12")
    mo = await rank(viewer.client, "month", "2033-03-12")
    yr = await rank(viewer.client, "year", "2033-03-12")
    w, m, y = (row_of(d, "QA Đổi Kỳ") for d in (wk, mo, yr))
    assert (w["speed_kmh"], w["video"]) == (260, None), (
        "số đo xếp hạng của tuần không có video -> null, không lấy video của số đo 210"
    )
    assert (m["speed_kmh"], m["video"]["url"]) == (300, YT2)
    assert (y["speed_kmh"], y["video"]["url"]) == (300, YT2)
    assert datetime.fromisoformat(w["measured_at"]) == vn(2033, 3, 11)
    assert datetime.fromisoformat(m["measured_at"]) == vn(2033, 3, 22)
    # Tuần khác (22/03) -> chỉ có số đo 300
    wk2 = await rank(viewer.client, "week", "2033-03-22")
    assert row_of(wk2, "QA Đổi Kỳ")["video"]["url"] == YT2
    # Kỳ không có số đo -> bảng rỗng
    assert (await rank(viewer.client, "week", "2033-06-01"))["top"] == []


async def test_ac6_video_kinds_youtube_and_file_and_fields(people):
    yt, mp = await person(people, "QA Video YouTube"), await person(people, "QA Video Mp4")
    viewer = await person(people, "QA Xem Loại Video")
    await rec(yt.customer_id, 280, vn(2033, 4, 5), YT)
    await rec(mp.customer_id, 270, vn(2033, 4, 6), MP4)
    d = await rank(viewer.client, "month", "2033-04-10")
    a, b = row_of(d, "QA Video YouTube"), row_of(d, "QA Video Mp4")
    assert (
        a["video"]["kind"] == "youtube" and a["video"]["embed_url"] and a["video"]["thumbnail_url"]
    )
    assert "youtube-nocookie.com/embed/" in a["video"]["embed_url"]
    assert b["video"]["kind"] == "file" and b["video"]["url"] == MP4
    assert b["video"]["embed_url"] is None and b["video"]["thumbnail_url"] is None
    for key in ("rank", "display_name", "avatar_url", "speed_kmh", "is_me", "measured_at", "video"):
        assert key in a, key
    assert "id" not in a and "customer_id" not in a and "public_id" not in a


async def test_ac6_admin_attach_edit_detach_flow_is_reflected_in_ranking(admin, people):
    a = await person(people, "QA Admin Gắn")
    viewer = await person(people, "QA Xem Admin Gắn")
    at = datetime.now(UTC) - timedelta(hours=3)
    day = datetime.now(settings.tz).date().isoformat()
    created = await admin.post(
        ADMIN,
        json={
            "member_code": a.code,
            "wins": 1,
            "losses": 0,
            "speed_kmh": 400,
            "measured_at": at.isoformat(),
        },
        headers=idem(),
    )
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    async def mine():
        d = await rank(viewer.client, "month", day)
        return next((r for r in d["top"] if r["display_name"] == "QA Admin Gắn"), None)

    assert (await mine())["video"] is None
    assert (
        await admin.put(f"{ADMIN}/{rid}/video", json={"url": YT}, headers=idem())
    ).status_code == 200
    assert (await mine())["video"]["url"] == YT
    cur = next(
        i for i in (await admin.get(ADMIN, params={"size": 100})).json()["items"] if i["id"] == rid
    )
    r = await admin.patch(
        f"{ADMIN}/{rid}", json={"version": cur["version"], "video_url": YT2}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (await mine())["video"]["url"] == YT2
    assert (await admin.delete(f"{ADMIN}/{rid}/video", headers=idem())).status_code in (200, 204)
    assert (await mine())["video"] is None
    assert (await admin.delete(f"{ADMIN}/{rid}", headers=idem())).status_code == 204
    assert await mine() is None, "xóa số đo -> biến khỏi bảng"


# ---------------------------------------------------------------- khối "Hạng của tôi"


async def test_me_block_has_video_of_own_ranked_record_inside_and_outside_top10(people):
    crowd = []
    for i in range(11):
        _rate_limit_backend.clear()
        crowd.append(await person(people, f"QA Đông {i:02d}"))
    _rate_limit_backend.clear()
    me = await person(people, "QA Của Tôi Hạng")
    for i, p in enumerate(crowd):
        await rec(p.customer_id, 400 - i * 5, vn(2033, 5, 3), YT)
    low = await rec(me.customer_id, 100, vn(2033, 5, 4), YT2)  # ngoài top 10
    await rec(me.customer_id, 90, vn(2033, 5, 5), YT)  # thấp hơn, video khác -> không dùng
    d = await rank(me.client, "month", "2033-05-10")
    assert len(d["top"]) == 10 and d["me"]["rank"] == 12
    assert d["me"]["video"]["url"] == YT2 and d["me"]["gap_to_top10"] is not None
    assert datetime.fromisoformat(d["me"]["measured_at"]) == vn(2033, 5, 4)
    # Số đo xếp hạng không có video -> me.video null dù số đo thấp hơn có video
    async with SessionLocal() as s:
        await s.execute(
            update(SpeedRecord)
            .where(SpeedRecord.id == low)
            .values(video_url=None, video_set_at=None)
        )
        await s.commit()
    assert (await rank(me.client, "month", "2033-05-10"))["me"]["video"] is None
    # Trong top 10: hàng của mình có video và khối me trùng
    await rec(me.customer_id, 450, vn(2033, 5, 6), MP4)
    d = await rank(me.client, "month", "2033-05-10")
    mine = next(r for r in d["top"] if r["is_me"])
    assert mine["rank"] == 1 and mine["video"]["url"] == MP4 and d["me"]["video"]["url"] == MP4


# ---------------------------------------------------------------- AC7: ẩn danh, pending / rejected


async def test_ac7_anonymous_plays_without_identity_and_unapproved_never_appear(people):
    hidden, shown = await person(people, "QA Tên Thật Ẩn"), await person(people, "QA Tên Hiện Ra")
    viewer = await person(people, "QA Xem Ẩn Danh")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == hidden.customer_id)
            .values(show_on_records=False, nickname="Biệt Danh Ẩn Bí Mật")
        )
        await s.commit()
    await rec(hidden.customer_id, 330, vn(2033, 6, 3), YT)
    await rec(shown.customer_id, 320, vn(2033, 6, 4), YT2)
    await rec(shown.customer_id, 499, vn(2033, 6, 5), MP4, status="rejected")
    await rec(shown.customer_id, 498, vn(2033, 6, 6), MP4, status="pending")
    r = await viewer.client.get(RANKING, params={"period": "month", "date": "2033-06-10"})
    d = r.json()
    first, second = d["top"][0], d["top"][1]
    assert (first["display_name"], first["avatar_url"], first["video"]["url"]) == (
        "Hội viên ẩn danh",
        None,
        YT,
    )
    for leak in (
        "QA Tên Thật Ẩn",
        "Biệt Danh Ẩn Bí Mật",
        hidden.code,
        hidden.phone,
        "customer_id",
        "public_id",
        "email",
    ):
        assert leak not in r.text, leak
    assert second["display_name"] == "QA Tên Hiện Ra" and second["speed_kmh"] == 320, (
        "pending / rejected không vào bảng"
    )
    assert second["video"]["url"] == YT2 and MP4 not in r.text
    own = await rank(hidden.client, "month", "2033-06-10")
    assert own["me"]["video"]["url"] == YT, "người ẩn danh tự xem vẫn thấy video của mình"


async def test_overview_ranking_shares_the_new_fields_without_leaking(people):
    hidden = await person(people, "QA Tổng Quan Ẩn")
    other = await person(people, "QA Tổng Quan Hiện")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hidden.customer_id).values(show_on_records=False)
        )
        await s.commit()
    now = datetime.now(UTC) - timedelta(minutes=20)
    await rec(hidden.customer_id, 480, now, YT)
    await rec(other.customer_id, 470, now)
    ov = (await other.client.get(f"{MA}/overview")).json()
    block = ov["ranking"]
    rows = block.get("top3") or block.get("top") or []
    anon = [r for r in rows if r["display_name"] == "Hội viên ẩn danh"]
    assert anon and anon[0]["video"]["url"] == YT and anon[0]["avatar_url"] is None
    assert "QA Tổng Quan Ẩn" not in str(block)


async def test_access_unchanged(anon, people):
    hv = await person(people, "QA Quyền T49")
    url = RANKING
    assert (
        await anon.get(url, params={"period": "month", "date": "2033-05-10"})
    ).status_code == 401
    assert (await hv.client.get(url, params={"period": "decade"})).status_code == 422
    r = await hv.client.get(url, params={"period": "month", "date": "2033-05-10"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"

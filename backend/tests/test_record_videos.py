"""T-046: video kỷ lục gắn tay (link YouTube / .mp4 / .webm), màn Admin, hiện ở khu hội viên."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.modules.members.models import Customer
from app.modules.records import video
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.test_play_rooms import MA

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

ADMIN = f"{API}/admin/speed-records"
TAG = f"t046:{uuid.uuid4().hex[:8]}:"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.startswith(TAG)))
        await s.commit()


async def record(cid: int, kmh: int, at: datetime, url: str | None = None) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid,
            speed_kmh=kmh,
            measured_at=at,
            source_ref=f"{TAG}{uuid.uuid4()}",
        )
        r.set_video(url, datetime.now(UTC))
        s.add(r)
        await s.commit()
        return r.id


@pytest.mark.parametrize(
    ("url", "kind", "embed"),
    [
        (YT, "youtube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
        (
            "https://youtu.be/dQw4w9WgXcQ?t=5",
            "youtube",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        ),
        (
            "https://m.youtube.com/shorts/dQw4w9WgXcQ",
            "youtube",
            "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        ),
        ("https://cdn.example.com/clip/smash.MP4", "file", None),
        ("https://cdn.example.com/a.webm?x=1", "file", None),
    ],
)
def test_parse_valid_links(url, kind, embed):
    v = video.parse(url)
    assert v is not None and (v.kind, v.embed_url) == (kind, embed)
    assert video.clean(f"  {url} ") == url
    if kind == "youtube":
        assert v.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=dQw4w9WgXcQ",  # không https
        "https://www.youtube.com/watch?v=ngắn",  # id sai
        "https://www.youtube.com/playlist?list=PL123",
        "https://vimeo.com/123456",
        "https://cdn.example.com/a.mov",
        "javascript:alert(1)",
        "https://cdn.example.com/a b.mp4",
        "",
        "https://x.vn/" + "a" * 500 + ".mp4",
    ],
)
def test_reject_bad_links(url):
    with pytest.raises(AppError) as e:
        video.clean(url)
    assert e.value.code == "E-REC-1"


async def test_admin_sets_and_removes_video_with_audit(admin, staff, people):
    hv = await people("Người Có Video")
    rid = await record(hv.customer_id, 255, datetime(2036, 1, 5, 9, tzinfo=UTC))

    r = await admin.get(ADMIN, params={"has_video": "false", "page": 1})
    assert r.status_code == 200, r.text
    row = next(i for i in r.json()["items"] if i["id"] == rid)
    assert (row["video"], row["member_code"], row["member_name"]) == (
        None,
        hv.code,
        "Người Có Video",
    )

    key = idem()
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": f" {YT} "}, headers=key)
    assert r.status_code == 200, r.text
    assert r.json()["video"]["kind"] == "youtube" and r.json()["video"]["url"] == YT
    # Gửi lại cùng khóa phải đúng y nội dung cũ (khác nội dung -> E-SEC-4, ADR-004)
    again = await admin.put(f"{ADMIN}/{rid}/video", json={"url": f" {YT} "}, headers=key)
    assert again.json() == r.json()
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": "https://vimeo.com/1"}, headers=idem())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-REC-1"
    assert r.json()["detail"]["message"] == "Chỉ nhận link YouTube hoặc file .mp4 / .webm (https)."

    with_video = (await admin.get(ADMIN, params={"has_video": "true"})).json()["items"]
    assert rid in [i["id"] for i in with_video]

    r = await admin.delete(f"{ADMIN}/{rid}/video", headers=idem())
    assert r.status_code == 200 and r.json()["video"] is None
    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                # entity_code là id số: lọc thêm theo action để không lẫn bản ghi khác cùng số
                select(AuditLog)
                .where(AuditLog.entity_code == str(rid), AuditLog.action.like("record.%"))
                .order_by(AuditLog.id)
            )
        )
    assert [x.action for x in rows] == ["record.video_set", "record.video_removed"]
    assert rows[0].detail["speed_kmh"] == 255 and rows[0].detail["member_code"] == hv.code
    assert rows[0].detail["changes"][0]["after"] == YT

    assert (
        await admin.put(f"{ADMIN}/999999999/video", json={"url": YT}, headers=idem())
    ).status_code == 404
    assert (await staff.get(ADMIN)).status_code == 403  # chỉ Admin
    r = await staff.put(f"{ADMIN}/{rid}/video", json={"url": YT}, headers=idem())
    assert r.status_code == 403


async def test_member_video_list_overview_and_anonymity(people):
    hidden = await people("Ẩn Danh Có Video")
    viewer = await people("Người Xem Video")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hidden.customer_id).values(show_on_records=False)
        )
        await s.commit()
    clip = "https://cdn.example.com/smash.mp4"
    # Năm 2036: sau mọi số đo khác trong DB test -> là kỷ lục cụm hiện tại
    await record(hidden.customer_id, 499, datetime(2036, 3, 1, 9, tzinfo=UTC), clip)

    d = (await viewer.client.get(f"{MA}/record-videos", params={"period": "all"})).json()
    card = next(c for c in d["items"] if c["video"]["url"] == clip)
    assert (card["display_name"], card["avatar_url"], card["is_me"]) == (
        "Hội viên ẩn danh",
        None,
        False,
    )
    assert card["video"]["kind"] == "file" and card["speed_kmh"] == 499
    mine = (await hidden.client.get(f"{MA}/record-videos", params={"period": "all"})).json()
    me_card = next(c for c in mine["items"] if c["video"]["url"] == clip)
    assert me_card["display_name"] == "Ẩn Danh Có Video" and me_card["is_me"]
    # Kỳ không chứa số đo -> không có
    d = (
        await viewer.client.get(
            f"{MA}/record-videos", params={"period": "year", "date": "2035-06-01"}
        )
    ).json()
    assert clip not in str(d) and (d["start"], d["end"]) == ("2035-01-01", "2035-12-31")

    # Tổng quan: thẻ Kỷ lục mới có video (phát được cả khi ẩn danh)
    recent = (await viewer.client.get(f"{MA}/overview")).json()["recent_records"]
    assert recent[0]["is_current"] and recent[0]["speed_kmh"] == 499
    assert recent[0]["video"]["url"] == clip and recent[0]["display_name"] == "Hội viên ẩn danh"

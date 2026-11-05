"""T-047: số đo nhập tay (Admin, duyệt ngay) + hội viên gửi cú đập chờ Admin duyệt."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import new_court
from tests.test_play_rooms import MA, notifications

ADMIN = f"{API}/admin/speed-records"
MINE = f"{MA}/speed-records"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TAG = f"t047:{uuid.uuid4().hex[:8]}:"

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)
_made: list[int] = []  # id hồ sơ đã tạo – dọn số đo của họ sau mỗi test


async def person(people, name: str):
    hv = await people(name)
    _made.append(hv.customer_id)
    return hv


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(
            delete(SpeedRecord).where(
                SpeedRecord.customer_id.in_(_made) | SpeedRecord.source_ref.startswith(TAG)
            )
        )
        await s.commit()
    _made.clear()


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def code_of(r) -> str:
    return r.json()["detail"]["code"]


async def record_kmh(client) -> int | None:
    r = await client.get(f"{MA}/me")
    assert r.status_code == 200, r.text
    return r.json()["record_kmh"]


async def my_rank(client, at: datetime) -> dict | None:
    day = at.astimezone(settings.tz).date().isoformat()
    r = await client.get(f"{MA}/speed-ranking", params={"period": "month", "date": day})
    assert r.status_code == 200, r.text
    return r.json()["me"]


async def actions_of(record_id: int) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                # entity_code là id số: lọc thêm theo action để không lẫn bản ghi khác cùng số
                select(AuditLog)
                .where(AuditLog.entity_code == str(record_id), AuditLog.action.like("record.%"))
                .order_by(AuditLog.id)
            )
        )


async def device_record(customer_id: int, kmh: int, at: datetime) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=customer_id,
            speed_kmh=kmh,
            measured_at=at,
            source_ref=f"{TAG}{uuid.uuid4()}",
        )
        s.add(r)
        await s.commit()
        return r.id


async def test_admin_creates_edits_and_deletes_manual_records(admin, staff, people):
    hv = await person(people, "Nhập Tay")
    court = await new_court(admin)
    at = now() - timedelta(minutes=5)
    body = {
        "member_code": hv.code.lower(),
        "speed_kmh": 260,
        "measured_at": at.isoformat(),
        "resource_code": court["code"].lower(),
        "video_url": f" {YT} ",
    }
    r = await admin.post(ADMIN, json=body, headers=idem())
    assert r.status_code == 201, r.text
    row = r.json()
    rid = row["id"]
    assert (row["source"], row["status"], row["editable"], row["version"]) == (
        "admin",
        "approved",
        True,
        1,
    )
    assert (row["member_code"], row["resource_code"], row["resource_name"]) == (
        hv.code,
        court["code"],
        court["name"],
    )
    assert row["video"]["url"] == YT and row["reject_reason"] is None
    # Admin nhập = duyệt ngay -> tính kỷ lục / bảng xếp hạng
    assert await record_kmh(hv.client) == 260
    assert (await my_rank(hv.client, at))["speed_kmh"] == 260

    r = await admin.patch(f"{ADMIN}/{rid}", json={"version": 1, "speed_kmh": 270}, headers=idem())
    assert r.status_code == 200, r.text
    assert (r.json()["speed_kmh"], r.json()["version"]) == (270, 2)
    r = await admin.patch(f"{ADMIN}/{rid}", json={"version": 1, "speed_kmh": 280}, headers=idem())
    assert r.status_code == 409 and code_of(r) == "E-REC-3"
    r = await admin.patch(
        f"{ADMIN}/{rid}",
        json={"version": 2, "resource_code": None, "video_url": None},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    assert (r.json()["resource_code"], r.json()["video"], r.json()["version"]) == (None, None, 3)
    # Không đổi gì -> không tăng version, không ghi nhật ký
    r = await admin.patch(f"{ADMIN}/{rid}", json={"version": 3, "speed_kmh": 270}, headers=idem())
    assert r.status_code == 200 and r.json()["version"] == 3
    future = (now() + timedelta(hours=1)).isoformat()
    r = await admin.patch(
        f"{ADMIN}/{rid}", json={"version": 3, "measured_at": future}, headers=idem()
    )
    assert r.status_code == 422 and code_of(r) == "E-REC-5"
    assert await record_kmh(hv.client) == 270

    r = await admin.delete(f"{ADMIN}/{rid}", headers=idem())
    assert r.status_code == 204, r.text
    assert await record_kmh(hv.client) is None
    assert (await admin.delete(f"{ADMIN}/{rid}", headers=idem())).status_code == 404
    rows = await actions_of(rid)
    assert [x.action for x in rows] == [
        "record.create_manual",
        "record.update",
        "record.update",
        "record.delete",
    ]
    assert rows[0].detail["member_code"] == hv.code and rows[0].detail["source"] == "admin"
    assert rows[1].detail["changes"] == [{"field": "Tốc độ (km/h)", "before": 260, "after": 270}]
    # Xóa giữ giá trị trước khi xóa
    assert {"field": "Tốc độ (km/h)", "before": 270, "after": None} in rows[3].detail["changes"]

    # Chỉ Admin
    assert (await staff.post(ADMIN, json=body, headers=idem())).status_code == 403


async def test_device_records_cannot_be_edited_or_deleted(admin, people):
    hv = await person(people, "Máy Đo")
    rid = await device_record(hv.customer_id, 222, now())  # mới nhất -> nằm ở trang 1
    rows = (await admin.get(ADMIN, params={"source": "device"})).json()["items"]
    row = next(i for i in rows if i["id"] == rid)
    assert (row["source"], row["status"], row["editable"]) == ("device", "approved", False)

    r = await admin.patch(f"{ADMIN}/{rid}", json={"version": 1, "speed_kmh": 300}, headers=idem())
    assert r.status_code == 403 and code_of(r) == "E-REC-2"
    r = await admin.delete(f"{ADMIN}/{rid}", headers=idem())
    assert r.status_code == 403 and code_of(r) == "E-REC-2"
    async with SessionLocal() as s:
        assert (await s.get(SpeedRecord, rid)).speed_kmh == 222
    # Gắn video cho số đo máy (T-046) vẫn được; version tăng
    r = await admin.put(f"{ADMIN}/{rid}/video", json={"url": YT}, headers=idem())
    assert r.status_code == 200 and r.json()["version"] == 2


async def test_admin_create_validation(admin, people):
    hv = await person(people, "Kiểm Dữ Liệu")
    stopped = await person(people, "Đã Ngừng")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == stopped.customer_id).values(is_active=False)
        )
        await s.commit()
    ok = {"member_code": hv.code, "speed_kmh": 200, "measured_at": now().isoformat()}
    cases = [
        ({"member_code": "HV-KHONG-CO"}, 422, "E-REC-7"),
        ({"member_code": stopped.code}, 422, "E-REC-7"),
        ({"measured_at": (now() + timedelta(hours=1)).isoformat()}, 422, "E-REC-5"),
        ({"measured_at": (now() - timedelta(days=366)).isoformat()}, 422, "E-REC-5"),
        ({"resource_code": "KHONG-CO"}, 422, "E-REC-6"),
        ({"video_url": "https://vimeo.com/1"}, 422, "E-REC-1"),
    ]
    for change, status, code in cases:
        r = await admin.post(ADMIN, json={**ok, **change}, headers=idem())
        assert (r.status_code, code_of(r)) == (status, code), (change, r.text)
    for change in (
        {"speed_kmh": 49},
        {"speed_kmh": 501},
        {"measured_at": "2026-11-01T10:00:00"},  # thiếu múi giờ
    ):
        r = await admin.post(ADMIN, json={**ok, **change}, headers=idem())
        assert r.status_code == 422, change
    async with SessionLocal() as s:
        assert (
            await s.scalar(
                select(SpeedRecord.id).where(
                    SpeedRecord.customer_id.in_([hv.customer_id, stopped.customer_id])
                )
            )
            is None
        )


async def test_member_submission_review_flow(admin, people):
    hv = await person(people, "Gửi Cú Đập")
    other = await person(people, "Người Khác")
    court = await new_court(admin)
    at = now() - timedelta(minutes=2)

    r = await hv.client.post(
        MINE,
        json={
            "speed_kmh": 300,
            "measured_at": at.isoformat(),
            "resource_code": court["code"],
            # gửi hộ người khác không được: trường lạ bị bỏ qua, số đo luôn của chính mình
            "customer_id": other.customer_id,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    first = r.json()
    assert (first["status"], first["can_withdraw"], first["resource_name"]) == (
        "pending",
        True,
        court["name"],
    )
    # Chờ duyệt: chưa tính kỷ lục / bảng xếp hạng
    assert await record_kmh(hv.client) is None
    assert await my_rank(hv.client, at) is None

    # Không lộ bản chờ của người khác
    mine = (await other.client.get(f"{MINE}/mine")).json()
    assert mine["items"] == [] and mine["daily_limit"] == 5
    assert court["code"] in [c["code"] for c in mine["resources"]]
    assert (await other.client.delete(f"{MINE}/{first['id']}", headers=idem())).status_code == 404
    hv_mine = (await hv.client.get(f"{MINE}/mine")).json()["items"]
    assert [i["id"] for i in hv_mine] == [first["id"]]

    listed = (await admin.get(ADMIN, params={"status": "pending"})).json()
    assert first["id"] in [i["id"] for i in listed["items"]]
    assert all(i["status"] == "pending" for i in listed["items"])
    assert listed["pending_count"] >= 1
    row = next(i for i in listed["items"] if i["id"] == first["id"])
    assert (row["source"], row["member_code"]) == ("member", hv.code)

    r = await admin.post(f"{ADMIN}/{first['id']}/approve", headers=idem())
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert await record_kmh(hv.client) == 300
    assert (await my_rank(hv.client, at))["speed_kmh"] == 300
    r = await admin.post(f"{ADMIN}/{first['id']}/approve", headers=idem())
    assert r.status_code == 409 and code_of(r) == "E-REC-4"
    r = await hv.client.delete(f"{MINE}/{first['id']}", headers=idem())
    assert r.status_code == 409 and code_of(r) == "E-REC-4"

    # Bị từ chối: có lý do, không tính, không hiện ở Video & kỷ lục
    r = await hv.client.post(
        MINE,
        json={"speed_kmh": 310, "measured_at": at.isoformat(), "video_url": YT},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    second = r.json()
    r = await admin.post(f"{ADMIN}/{second['id']}/reject", json={"reason": "   "}, headers=idem())
    assert r.status_code == 422 and code_of(r) == "E-REC-8"
    r = await admin.post(
        f"{ADMIN}/{second['id']}/reject", json={"reason": "x" * 201}, headers=idem()
    )
    assert r.status_code == 422 and code_of(r) == "E-REC-8"
    r = await admin.post(
        f"{ADMIN}/{second['id']}/reject", json={"reason": " Video  không rõ "}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["reject_reason"]) == ("rejected", "Video không rõ")
    assert await record_kmh(hv.client) == 300
    videos = (await hv.client.get(f"{MA}/record-videos", params={"period": "all"})).json()
    assert not any(i["is_me"] and i["speed_kmh"] == 310 for i in videos["items"])
    hv_mine = (await hv.client.get(f"{MINE}/mine")).json()["items"]
    assert [(i["status"], i["reject_reason"], i["can_withdraw"]) for i in hv_mine] == [
        ("rejected", "Video không rõ", False),
        ("approved", None, False),
    ]

    # Thông báo cả hai trường hợp
    items = (await notifications(hv.client))["items"]
    kinds = {i["kind"]: i for i in items if i["kind"].startswith("record.")}
    assert kinds["record.approved"]["text"] == "Cú đập 300 km/h của bạn đã được duyệt."
    assert kinds["record.rejected"]["text"] == "Cú đập 310 km/h của bạn bị từ chối: Video không rõ"
    assert kinds["record.rejected"]["link"] == "/hoi-vien/video-ky-luc"

    # Rút lại bản chờ duyệt
    r = await hv.client.post(
        MINE, json={"speed_kmh": 320, "measured_at": at.isoformat()}, headers=idem()
    )
    assert r.status_code == 201, r.text
    third = r.json()["id"]
    assert (await hv.client.delete(f"{MINE}/{third}", headers=idem())).status_code == 204
    assert third not in [i["id"] for i in (await hv.client.get(f"{MINE}/mine")).json()["items"]]

    submits = await actions_of(first["id"])
    assert [x.action for x in submits] == ["record.submit", "record.approve"]
    assert submits[0].actor_type == "customer" and submits[1].actor_type == "admin"
    assert [x.action for x in await actions_of(third)] == ["record.submit", "record.delete"]


async def test_member_submit_limits_and_validation(anon, people):
    hv = await person(people, "Giới Hạn")
    at = now().isoformat()
    for change, status, code in (
        ({"measured_at": (now() + timedelta(hours=1)).isoformat()}, 422, "E-REC-5"),
        ({"resource_code": "KHONG-CO"}, 422, "E-REC-6"),
        ({"video_url": "http://youtu.be/dQw4w9WgXcQ"}, 422, "E-REC-1"),
    ):
        r = await hv.client.post(
            MINE, json={"speed_kmh": 200, "measured_at": at, **change}, headers=idem()
        )
        assert (r.status_code, code_of(r)) == (status, code), change
    # Lượt lỗi không tính vào giới hạn 5 / ngày
    for kmh in range(201, 206):
        r = await hv.client.post(MINE, json={"speed_kmh": kmh, "measured_at": at}, headers=idem())
        assert r.status_code == 201, r.text
    r = await hv.client.post(MINE, json={"speed_kmh": 206, "measured_at": at}, headers=idem())
    assert r.status_code == 429 and code_of(r) == "E-SEC-5"

    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == hv.customer_id).values(is_active=False)
        )
        await s.commit()
    r = await hv.client.post(MINE, json={"speed_kmh": 200, "measured_at": at}, headers=idem())
    assert r.status_code == 403 and code_of(r) == "E-REC-7"

    assert (await anon.get(f"{MINE}/mine")).status_code == 401
    r = await anon.post(MINE, json={"speed_kmh": 200, "measured_at": at}, headers=idem())
    assert r.status_code == 401

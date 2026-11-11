# ruff: noqa: E501
"""QA T-047: số đo nhập tay (Admin) + hội viên gửi cú đập chờ duyệt – kiểm theo tiêu chí AC1–AC7 (phần API).

Bổ sung cho ``test_record_manual.py`` của BACKEND: phân quyền, Idempotency-Key, biên dữ liệu, đồng thời,
bộ lọc danh sách, "không lộ pending", thông báo đúng người, hồi quy T-030/T-036/T-046.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import new_court
from tests.test_play_rooms import MA, notifications

ADMIN = f"{API}/admin/speed-records"
MINE = f"{MA}/speed-records"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TAG = f"qa047:{uuid.uuid4().hex[:8]}:"
people = base.people  # fixture: hội viên có tài khoản liên kết, đã đăng nhập
_made: list[int] = []


async def person(people, name: str):
    hv = await people(name)
    _made.append(hv.customer_id)
    return hv


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.customer_id.in_(_made)))
        await s.commit()
    _made.clear()


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def code_of(r) -> str:
    return r.json()["detail"]["code"]


def body(hv, kmh=200, **kw) -> dict:
    return {
        "member_code": hv.code,
        "wins": 1,
        "losses": 0,
        "speed_kmh": kmh,
        "measured_at": (now() - timedelta(minutes=3)).isoformat(),
        **kw,
    }


async def admin_add(admin, hv, kmh=200, **kw) -> dict:
    r = await admin.post(ADMIN, json=body(hv, kmh, **kw), headers=idem())
    assert r.status_code == 201, r.text
    return r.json()


async def submit(hv, kmh=200, **kw):
    return await hv.client.post(
        MINE,
        json={
            "wins": 1,
            "losses": 0,
            "speed_kmh": kmh,
            "measured_at": (now() - timedelta(minutes=2)).isoformat(),
            **kw,
        },
        headers=idem(),
    )


async def record_kmh(client) -> int | None:
    return (await client.get(f"{MA}/me")).json()["record_kmh"]


async def audit_rows(record_id: int) -> list[AuditLog]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(AuditLog)
                .where(AuditLog.entity_code == str(record_id), AuditLog.action.like("record.%"))
                .order_by(AuditLog.id)
            )
        )


# ================================================================ SEC: phân quyền / xác thực


async def test_sec_admin_endpoints_need_admin_staff_and_anonymous_are_rejected(
    admin, staff, anon, people
):
    hv = await person(people, "QA Quyền")
    row = await admin_add(admin, hv, 210)
    rid = row["id"]
    calls = [
        ("get", ADMIN, None),
        ("post", ADMIN, body(hv)),
        ("patch", f"{ADMIN}/{rid}", {"version": 1, "speed_kmh": 220}),
        ("delete", f"{ADMIN}/{rid}", None),
        ("post", f"{ADMIN}/{rid}/approve", None),
        ("post", f"{ADMIN}/{rid}/reject", {"reason": "x"}),
    ]
    for who, expected in ((anon, 401), (staff, 403), (hv.client, 403)):
        for method, url, payload in calls:
            kw = {"headers": idem()} if method != "get" else {}
            if payload is not None:
                kw["json"] = payload
            r = await getattr(who, method)(url, **kw)
            assert r.status_code == expected, (who, method, url, r.status_code, r.text)
    async with SessionLocal() as s:  # không có gì bị đổi
        got = await s.get(SpeedRecord, rid)
        assert (got.speed_kmh, got.version, got.status) == (210, 1, "approved")


async def test_sec_member_endpoints_need_login_and_only_own_withdrawal(anon, admin, people):
    a = await person(people, "QA Chủ Bản")
    b = await person(people, "QA Người Lạ")
    sub = (await submit(a, 250)).json()
    for method, url in (("get", f"{MINE}/mine"), ("delete", f"{MINE}/{sub['id']}")):
        kw = {} if method == "get" else {"headers": idem()}
        assert (await getattr(anon, method)(url, **kw)).status_code == 401
    assert (
        await anon.post(
            MINE,
            json={"wins": 1, "losses": 0, "speed_kmh": 200, "measured_at": now().isoformat()},
            headers=idem(),
        )
    ).status_code == 401
    # Người khác rút/lộ bản của mình: 404, không đổi gì
    assert (await b.client.delete(f"{MINE}/{sub['id']}", headers=idem())).status_code == 404
    assert (await a.client.get(f"{MINE}/mine")).json()["items"][0]["id"] == sub["id"]
    # Admin-entered / device record không rút lại được qua API hội viên
    adm = await admin_add(admin, a, 260)
    assert (await a.client.delete(f"{MINE}/{adm['id']}", headers=idem())).status_code == 404
    async with SessionLocal() as s:
        assert await s.get(SpeedRecord, adm["id"]) is not None


async def test_sec_member_cannot_submit_for_someone_else_or_force_status(admin, people):
    a = await person(people, "QA Gửi Hộ A")
    b = await person(people, "QA Gửi Hộ B")
    r = await a.client.post(
        MINE,
        json={
            "wins": 1,
            "losses": 0,
            "speed_kmh": 480,
            "measured_at": now().isoformat(),
            "customer_id": b.customer_id,
            "member_code": b.code,
            "status": "approved",
            "source": "admin",
            "reviewed_by": 1,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    async with SessionLocal() as s:
        rec = await s.get(SpeedRecord, r.json()["id"])
        assert (rec.customer_id, rec.status, rec.source, rec.reviewed_by) == (
            a.customer_id,
            "pending",
            "member",
            None,
        )
    assert await record_kmh(a.client) is None and await record_kmh(b.client) is None


async def test_sec_writes_require_idempotency_key_and_replay_does_not_duplicate(admin, people):
    hv = await person(people, "QA Idem")
    r = await admin.post(ADMIN, json=body(hv))
    assert r.status_code in (400, 422), (r.status_code, r.text)
    r = await hv.client.post(
        MINE, json={"wins": 1, "losses": 0, "speed_kmh": 200, "measured_at": now().isoformat()}
    )
    assert r.status_code in (400, 422), (r.status_code, r.text)
    # Dựng body một lần: now() làm tròn giây, dựng lại có thể khác nhau -> E-SEC-4 (test chập chờn)
    key, payload = idem(), body(hv, 230)
    r1 = await admin.post(ADMIN, json=payload, headers=key)
    r2 = await admin.post(ADMIN, json=payload, headers=key)
    assert r1.status_code == 201 and r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    key, mine = idem(), {"wins": 1, "losses": 0, "speed_kmh": 240, "measured_at": now().isoformat()}
    p1 = await hv.client.post(MINE, json=mine, headers=key)
    p2 = await hv.client.post(MINE, json=mine, headers=key)
    assert p1.status_code == 201 and p2.json()["id"] == p1.json()["id"]
    async with SessionLocal() as s:
        n = len(
            list(
                await s.scalars(
                    select(SpeedRecord.id).where(SpeedRecord.customer_id == hv.customer_id)
                )
            )
        )
    assert n == 2, "mỗi lần bấm 1 bản (replay cùng khóa không nhân đôi)"


async def test_sec_cross_origin_write_is_rejected(admin, people):
    hv = await person(people, "QA Origin")
    r = await admin.post(ADMIN, json=body(hv), headers={**idem(), "Origin": "https://evil.example"})
    assert r.status_code in (400, 403), (r.status_code, r.text)
    async with SessionLocal() as s:
        assert (
            await s.scalar(select(SpeedRecord.id).where(SpeedRecord.customer_id == hv.customer_id))
            is None
        )


# ================================================================ AC: biên dữ liệu


async def test_ac_speed_bounds_integer_and_types(admin, people):
    hv = await person(people, "QA Biên Tốc Độ")
    for kmh in (50, 500):
        assert (await admin.post(ADMIN, json=body(hv, kmh), headers=idem())).status_code == 201, kmh
    assert await record_kmh(hv.client) == 500
    for bad in (49, 501, 0, -1, 300.5, "abc", None, True):
        r = await admin.post(ADMIN, json=body(hv, bad), headers=idem())
        assert r.status_code == 422, (bad, r.status_code, r.text)
        r = await submit(hv, bad)
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert (
        await admin.post(ADMIN, json={**body(hv), "speed_kmh": None}, headers=idem())
    ).status_code == 422
    missing = body(hv)
    del missing["measured_at"]
    assert (await admin.post(ADMIN, json=missing, headers=idem())).status_code == 422


async def test_ac_time_window_boundaries(admin, people):
    hv = await person(people, "QA Biên Thời Gian")
    ok = [now() + timedelta(seconds=30), now() - timedelta(days=364, hours=23)]
    bad = [now() + timedelta(minutes=5), now() - timedelta(days=366)]
    for at in ok:
        r = await admin.post(ADMIN, json=body(hv, measured_at=at.isoformat()), headers=idem())
        assert r.status_code == 201, (at, r.text)
        r = await submit(hv, 150, measured_at=at.isoformat())
        assert r.status_code == 201, (at, r.text)
    for at in bad:
        r = await admin.post(ADMIN, json=body(hv, measured_at=at.isoformat()), headers=idem())
        assert (r.status_code, code_of(r)) == (422, "E-REC-5"), at
        r = await submit(hv, 150, measured_at=at.isoformat())
        assert (r.status_code, code_of(r)) == (422, "E-REC-5"), at
    # Múi giờ +07:00 hiểu đúng (cùng thời điểm với UTC)
    at = (now() - timedelta(hours=2)).astimezone(UTC)
    local = at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat()
    r = await admin.post(ADMIN, json=body(hv, 205, measured_at=local), headers=idem())
    assert r.status_code == 201 and datetime.fromisoformat(r.json()["measured_at"]) == at


async def test_ac_court_and_video_rules_apply_to_admin_member_and_patch(admin, people):
    hv = await person(people, "QA Sân Video")
    court = await new_court(admin)
    stopped = await new_court(admin)
    r = await admin.patch(
        f"{API}/booking/resources/{stopped['code']}",
        json={"version": stopped["version"], "is_active": False},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    row = await admin_add(admin, hv, 205, resource_code=court["code"], video_url=YT)
    assert row["resource_name"] == court["name"]
    r = await admin.post(ADMIN, json=body(hv, resource_code=stopped["code"]), headers=idem())
    assert (r.status_code, code_of(r)) == (422, "E-REC-6")
    # Sửa: sân không có -> E-REC-6; video sai -> E-REC-1; không đổi version khi lỗi
    r = await admin.patch(
        f"{ADMIN}/{row['id']}", json={"version": 1, "resource_code": "KHONG-CO"}, headers=idem()
    )
    assert (r.status_code, code_of(r)) == (422, "E-REC-6")
    for url in (
        "https://vimeo.com/1",
        "javascript:alert(1)",
        "http://youtu.be/dQw4w9WgXcQ",
        "https://evil.example/watch?v=dQw4w9WgXcQ",
    ):
        r = await admin.patch(
            f"{ADMIN}/{row['id']}", json={"version": 1, "video_url": url}, headers=idem()
        )
        assert (r.status_code, code_of(r)) == (422, "E-REC-1"), url
        r = await submit(hv, 150, video_url=url)
        assert (r.status_code, code_of(r)) == (422, "E-REC-1"), url
    got = next(
        i
        for i in (await admin.get(ADMIN, params={"source": "admin"})).json()["items"]
        if i["id"] == row["id"]
    )
    assert got["version"] == 1 and got["video"]["url"] == YT


async def test_ac_member_code_is_case_insensitive_and_inactive_member_blocked(admin, people):
    hv = await person(people, "QA Mã HV")
    r = await admin.post(
        ADMIN, json=body(hv, 211) | {"member_code": f" {hv.code.lower()} "}, headers=idem()
    )
    assert r.status_code == 201 and r.json()["member_code"] == hv.code, r.text
    for bad in ("", "   ", "HV-000000-NOPE", "'; DROP TABLE speed_record;--"):
        r = await admin.post(ADMIN, json=body(hv) | {"member_code": bad}, headers=idem())
        assert r.status_code == 422, (bad, r.status_code)
    r = await admin.post(
        ADMIN, json={k: v for k, v in body(hv).items() if k != "member_code"}, headers=idem()
    )
    assert r.status_code == 422


# ================================================================ AC2/AC4/AC6: duyệt, từ chối, trạng thái


async def test_ac4_pending_and_rejected_are_never_counted_anywhere(admin, people):
    hv = await person(people, "QA Không Tính")
    viewer = await person(people, "QA Người Xem")
    sub = (await submit(hv, 499, video_url=YT)).json()
    # pending: không tính Hạng, Kỷ lục, Video & kỷ lục, tổng quan của mình / người khác
    assert await record_kmh(hv.client) is None
    for who in (hv, viewer):
        videos = (
            await who.client.get(f"{MA}/record-videos", params={"period": "all", "size": 100})
        ).json()
        assert not any(i["speed_kmh"] == 499 and i["is_me"] for i in videos["items"]), who.code
        ov = (await who.client.get(f"{MA}/overview")).json()
        assert not any(
            r["speed_kmh"] == 499 and r["display_name"].startswith("QA Không")
            for r in ov["recent_records"]
        )
    ov = (await hv.client.get(f"{MA}/overview")).json()
    assert ov["record_kmh"] is None and not ov["month_record_kmh"]
    ranking = await hv.client.get(f"{MA}/speed-ranking", params={"period": "month"})
    assert ranking.json()["me"] is None
    # reject: vẫn không tính
    r = await admin.post(f"{ADMIN}/{sub['id']}/reject", json={"reason": "Video mờ"}, headers=idem())
    assert r.status_code == 200
    assert await record_kmh(hv.client) is None
    ov = (await hv.client.get(f"{MA}/overview")).json()
    assert ov["record_kmh"] is None and not ov["month_record_kmh"]
    # Từ chối rồi duyệt/từ chối lại: 409 E-REC-4; rút lại bản bị từ chối: 409
    for path, payload in (("approve", None), ("reject", {"reason": "lại"})):
        kw = {"json": payload} if payload else {}
        r = await admin.post(f"{ADMIN}/{sub['id']}/{path}", headers=idem(), **kw)
        assert (r.status_code, code_of(r)) == (409, "E-REC-4"), path
    assert (await hv.client.delete(f"{MINE}/{sub['id']}", headers=idem())).status_code == 409


async def test_ac2_admin_can_approve_and_reject_only_pending(admin, people):
    hv = await person(people, "QA Chỉ Chờ Duyệt")
    adm = await admin_add(admin, hv, 240)  # đã approved
    r = await admin.post(f"{ADMIN}/{adm['id']}/approve", headers=idem())
    assert (r.status_code, code_of(r)) == (409, "E-REC-4")
    r = await admin.post(f"{ADMIN}/{adm['id']}/reject", json={"reason": "không"}, headers=idem())
    assert (r.status_code, code_of(r)) == (409, "E-REC-4")
    assert (await admin.post(f"{ADMIN}/99999999/approve", headers=idem())).status_code == 404
    assert (
        await admin.post(f"{ADMIN}/99999999/reject", json={"reason": "x"}, headers=idem())
    ).status_code == 404
    assert await record_kmh(hv.client) == 240, "bản approved không bị từ chối nhầm"
    # Lý do đúng 200 ký tự được; thiếu field -> 422
    sub = (await submit(hv, 130)).json()
    assert (
        await admin.post(f"{ADMIN}/{sub['id']}/reject", json={}, headers=idem())
    ).status_code == 422
    r = await admin.post(f"{ADMIN}/{sub['id']}/reject", json={"reason": "ạ" * 200}, headers=idem())
    assert r.status_code == 200 and len(r.json()["reject_reason"]) == 200


async def test_ac5_notifications_go_only_to_the_submitter_and_reason_is_escaped_text(admin, people):
    a = await person(people, "QA Thông Báo A")
    b = await person(people, "QA Thông Báo B")
    s1 = (await submit(a, 280)).json()
    s2 = (await submit(a, 281)).json()
    assert (await admin.post(f"{ADMIN}/{s1['id']}/approve", headers=idem())).status_code == 200
    reason = '<script>alert(1)</script> "quá mờ"'
    assert (
        await admin.post(f"{ADMIN}/{s2['id']}/reject", json={"reason": reason}, headers=idem())
    ).status_code == 200
    mine = [i for i in (await notifications(a.client))["items"] if i["kind"].startswith("record.")]
    assert sorted(i["kind"] for i in mine) == ["record.approved", "record.rejected"]
    assert any(reason in i["text"] for i in mine), (
        "lý do nằm trong thông báo (FE phải hiển thị dạng text)"
    )
    assert not [
        i for i in (await notifications(b.client))["items"] if i["kind"].startswith("record.")
    ]


async def test_ac4_approved_admin_entry_counts_like_a_device_record_and_edits_recompute(
    admin, people
):
    hv = await person(people, "QA Tính Như Máy")
    row = await admin_add(admin, hv, 300)
    assert await record_kmh(hv.client) == 300
    ov = (await hv.client.get(f"{MA}/overview")).json()
    assert ov["month_record_kmh"] == 300
    r = await admin.patch(
        f"{ADMIN}/{row['id']}", json={"version": 1, "speed_kmh": 310}, headers=idem()
    )
    assert r.status_code == 200 and await record_kmh(hv.client) == 310
    # Chuyển sang thời điểm cách đây > 1 tháng: bảng tháng không còn, kỷ lục cá nhân vẫn còn
    old = (now() - timedelta(days=100)).isoformat()
    r = await admin.patch(
        f"{ADMIN}/{row['id']}", json={"version": 2, "measured_at": old}, headers=idem()
    )
    assert r.status_code == 200
    ov = (await hv.client.get(f"{MA}/overview")).json()
    assert ov["record_kmh"] == 310 and not ov["month_record_kmh"]
    assert (await admin.delete(f"{ADMIN}/{row['id']}", headers=idem())).status_code == 204
    assert await record_kmh(hv.client) is None


async def test_ac6_device_records_are_protected_in_every_write_path(admin, people):
    hv = await person(people, "QA Máy Đo")
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=hv.customer_id,
            speed_kmh=333,
            measured_at=now(),
            source_ref=f"{TAG}{uuid.uuid4()}",
        )
        s.add(r)
        await s.commit()
        rid = r.id
    r = await admin.patch(f"{ADMIN}/{rid}", json={"version": 1, "video_url": YT}, headers=idem())
    assert (r.status_code, code_of(r)) == (403, "E-REC-2"), (
        "PATCH video_url cũng bị chặn, dùng PUT /video"
    )
    assert (await admin.delete(f"{ADMIN}/{rid}", headers=idem())).status_code == 403
    assert (
        await admin.post(f"{ADMIN}/{rid}/reject", json={"reason": "x"}, headers=idem())
    ).status_code in (403, 409)
    assert (await hv.client.delete(f"{MINE}/{rid}", headers=idem())).status_code == 404
    async with SessionLocal() as s:
        got = await s.get(SpeedRecord, rid)
        assert (got.speed_kmh, got.status, got.source) == (333, "approved", "device")


async def test_ac_admin_can_edit_a_pending_member_record_without_approving_it(admin, people):
    hv = await person(people, "QA Sửa Chờ Duyệt")
    sub = (await submit(hv, 260)).json()
    r = await admin.patch(
        f"{ADMIN}/{sub['id']}", json={"version": 1, "speed_kmh": 261}, headers=idem()
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending" and r.json()["speed_kmh"] == 261
    assert await record_kmh(hv.client) is None, "sửa không đồng nghĩa duyệt"


# ================================================================ AC: danh sách / bộ lọc / hiển thị


async def test_ac1_list_filters_and_counts(admin, staff, people):
    hv = await person(people, "QA Bộ Lọc")
    adm = await admin_add(admin, hv, 220, video_url=YT)
    pend = (await submit(hv, 221)).json()
    rej = (await submit(hv, 222)).json()
    await admin.post(f"{ADMIN}/{rej['id']}/reject", json={"reason": "sai"}, headers=idem())

    async def ids(**q):
        r = await admin.get(ADMIN, params={"size": 100, **q})
        assert r.status_code == 200, (q, r.text)
        return {i["id"]: i for i in r.json()["items"]}, r.json()

    got, data = await ids(status="pending")
    assert pend["id"] in got and adm["id"] not in got and rej["id"] not in got
    assert data["pending_count"] >= 1
    got, data2 = await ids(status="rejected")
    assert rej["id"] in got and got[rej["id"]]["reject_reason"] == "sai"
    assert data2["pending_count"] == data["pending_count"], "pending_count không theo bộ lọc"
    got, _ = await ids(source="admin")
    assert adm["id"] in got and pend["id"] not in got
    got, _ = await ids(source="member", status="pending")
    assert pend["id"] in got and rej["id"] not in got
    got, _ = await ids(has_video="true")
    assert adm["id"] in got and pend["id"] not in got
    for bad in ({"status": "weird"}, {"source": "weird"}):
        assert (await admin.get(ADMIN, params=bad)).status_code == 422, bad
    for field in ("version", "editable", "source", "status", "resource_code"):
        assert field in got[adm["id"]], field
    assert got[adm["id"]]["editable"] is True
    assert hv.phone not in str(data), "danh sách không lộ SĐT đầy đủ"
    assert (await staff.get(ADMIN)).status_code == 403


async def test_ac3_mine_lists_only_my_own_submissions_with_status(admin, people):
    a = await person(people, "QA Của Tôi A")
    b = await person(people, "QA Của Tôi B")
    s1 = (await submit(a, 270)).json()
    await submit(b, 271)
    s3 = (await submit(a, 272)).json()
    await admin.post(f"{ADMIN}/{s3['id']}/reject", json={"reason": "thiếu video"}, headers=idem())
    await admin_add(admin, a, 273)  # Admin nhập hộ: không phải bản tôi đã gửi
    mine = (await a.client.get(f"{MINE}/mine")).json()
    assert [(i["id"], i["status"], i["can_withdraw"]) for i in mine["items"]] == [
        (s3["id"], "rejected", False),
        (s1["id"], "pending", True),
    ]
    assert mine["items"][0]["reject_reason"] == "thiếu video"
    assert mine["daily_limit"] == 5
    text = str((await a.client.get(f"{MINE}/mine")).json())
    assert "customer_id" not in text and "reviewed_by" not in text and "submitted_by" not in text


# ================================================================ SEC-5: giới hạn 5 lượt / ngày VN


async def test_sec5_limit_is_per_member_and_withdrawn_does_not_count(people):
    a = await person(people, "QA Giới Hạn A")
    b = await person(people, "QA Giới Hạn B")
    ids = []
    for kmh in range(201, 206):
        r = await submit(a, kmh)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = await submit(a, 206)
    assert r.status_code == 429 and code_of(r) == "E-SEC-5" and int(r.headers["Retry-After"]) > 0
    assert (await submit(b, 207)).status_code == 201, "giới hạn theo từng hội viên"
    # lượt lỗi (422) không tính; rút lại 1 bản -> gửi thêm được đúng 1 bản
    assert (await a.client.delete(f"{MINE}/{ids[0]}", headers=idem())).status_code == 204
    assert (await submit(a, 49)).status_code == 422
    assert (await submit(a, 208)).status_code == 201
    assert (await submit(a, 209)).status_code == 429


async def test_sec5_concurrent_submits_never_exceed_five(people):
    a = await person(people, "QA Đồng Thời")
    results = await asyncio.gather(*[submit(a, 200 + i) for i in range(10)])
    codes = sorted(r.status_code for r in results)
    assert codes == [201] * 5 + [429] * 5, codes
    async with SessionLocal() as s:
        n = len(
            list(
                await s.scalars(
                    select(SpeedRecord.id).where(SpeedRecord.customer_id == a.customer_id)
                )
            )
        )
    assert n == 5


async def test_sec5_admin_entries_and_approved_records_do_not_use_the_members_quota(admin, people):
    a = await person(people, "QA Hạn Mức Admin")
    for kmh in range(210, 215):
        await admin_add(admin, a, kmh)  # source=admin: không đếm vào lượt gửi của hội viên
    for kmh in range(201, 206):
        assert (await submit(a, kmh)).status_code == 201


# ================================================================ Đồng thời / chống ghi đè


async def test_conc_approve_vs_reject_vs_withdraw_exactly_one_wins(admin, people):
    hv = await person(people, "QA Tranh Chấp")
    for attempt in range(3):
        sub = (await submit(hv, 250 + attempt)).json()
        rid = sub["id"]
        res = await asyncio.gather(
            admin.post(f"{ADMIN}/{rid}/approve", headers=idem()),
            admin.post(f"{ADMIN}/{rid}/reject", json={"reason": "tranh chấp"}, headers=idem()),
            hv.client.delete(f"{MINE}/{rid}", headers=idem()),
        )
        wins = [r for r in res if r.status_code in (200, 204)]
        assert len(wins) == 1, [r.status_code for r in res]
        for r in res:
            if r not in wins:
                assert r.status_code in (404, 409), (r.status_code, r.text)
        # nhật ký nhất quán: đúng 1 hành động kết thúc sau submit
        acts = [x.action for x in await audit_rows(rid)]
        assert acts[0] == "record.submit" and len(acts) == 2, acts


async def test_conc_two_admins_patch_same_version_one_409(admin, people):
    hv = await person(people, "QA Ghi Đè")
    row = await admin_add(admin, hv, 200)
    res = await asyncio.gather(
        admin.patch(f"{ADMIN}/{row['id']}", json={"version": 1, "speed_kmh": 301}, headers=idem()),
        admin.patch(f"{ADMIN}/{row['id']}", json={"version": 1, "speed_kmh": 302}, headers=idem()),
    )
    assert sorted(r.status_code for r in res) == [200, 409], [r.text for r in res]
    loser = next(r for r in res if r.status_code == 409)
    assert code_of(loser) == "E-REC-3"
    async with SessionLocal() as s:
        got = await s.get(SpeedRecord, row["id"])
        assert got.version == 2 and got.speed_kmh in (301, 302)


async def test_patch_validation_and_not_found(admin, people):
    hv = await person(people, "QA Sửa Lỗi")
    row = await admin_add(admin, hv, 200)
    u = f"{ADMIN}/{row['id']}"
    assert (
        await admin.patch(u, json={"wins": 1, "losses": 0, "speed_kmh": 250}, headers=idem())
    ).status_code == 422, "thiếu version"
    for bad in (
        {"wins": 1, "losses": 0, "speed_kmh": 49},
        {"wins": 1, "losses": 0, "speed_kmh": 501},
        {"wins": 1, "losses": 0, "speed_kmh": "x"},
        {"measured_at": "2026-01-01T10:00:00"},
    ):
        r = await admin.patch(u, json={"version": 1, **bad}, headers=idem())
        assert r.status_code == 422, (bad, r.text)
    r = await admin.patch(
        u,
        json={"version": 1, "measured_at": (now() + timedelta(days=1)).isoformat()},
        headers=idem(),
    )
    assert (r.status_code, code_of(r)) == (422, "E-REC-5")
    assert (
        await admin.patch(
            f"{ADMIN}/99999999", json={"version": 1, "speed_kmh": 250}, headers=idem()
        )
    ).status_code == 404
    # Không được đổi chủ / nguồn / trạng thái qua PATCH (trường lạ bị bỏ qua)
    other = await person(people, "QA Chủ Khác")
    r = await admin.patch(
        u,
        json={
            "version": 1,
            "speed_kmh": 251,
            "customer_id": other.customer_id,
            "member_code": other.code,
            "wins": 1,
            "losses": 0,
            "status": "pending",
            "source": "member",
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        got = await s.get(SpeedRecord, row["id"])
        assert (got.customer_id, got.status, got.source) == (hv.customer_id, "approved", "admin")


# ================================================================ Audit


async def test_audit_rows_have_correct_actor_and_no_phone(admin, people):
    hv = await person(people, "QA Nhật Ký")
    sub = (await submit(hv, 290)).json()
    await admin.post(f"{ADMIN}/{sub['id']}/approve", headers=idem())
    row = await admin_add(admin, hv, 291)
    await admin.delete(f"{ADMIN}/{row['id']}", headers=idem())
    a1 = await audit_rows(sub["id"])
    assert [(x.action, x.actor_type) for x in a1] == [
        ("record.submit", "customer"),
        ("record.approve", "admin"),
    ]
    a2 = await audit_rows(row["id"])
    assert [x.action for x in a2] == ["record.create_manual", "record.delete"]
    assert all(
        hv.phone not in str(x.detail) and hv.phone not in (x.actor_label or "") for x in a1 + a2
    )
    cat = (await admin.get(f"{API}/admin/audit-log/catalog")).json()
    keys = {t["key"] for g in cat["groups"] for t in g["types"]}
    assert {
        "record.create_manual",
        "record.update",
        "record.delete",
        "record.submit",
        "record.approve",
        "record.reject",
    } <= keys
    log = await admin.get(f"{API}/admin/audit-log", params={"action": "record.submit", "size": 100})
    assert log.status_code == 200
    mine = [i for i in log.json()["items"] if i["target"]["code"] == hv.code]
    assert mine, [i["target"] for i in log.json()["items"][:3]]
    assert mine[0]["actor"] == "customer" and hv.phone not in log.text

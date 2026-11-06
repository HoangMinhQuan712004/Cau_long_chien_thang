"""Lịch sử thao tác: quyền, lọc, phân trang, nội dung dòng (SRS Lịch sử thao tác FR-001..003)."""

import asyncio
import datetime as dt
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import delete, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.members.models import Customer
from tests.conftest import API, STAFF_NAME, idem, vn_today
from tests.helpers_booking import new_court, random_phone
from tests.helpers_web import checkout, sepay_payload, webhook

LOG = f"{API}/admin/audit-log"
M = f"{API}/members"


@pytest.fixture
async def phones():
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.commit()


def today() -> dt.date:
    return dt.datetime.now(settings.tz).date()


async def entries(client, **params) -> list[dict]:
    r = await client.get(LOG, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def by_target(items: list[dict], code: str | None, name: str | None = None) -> dict:
    def matches(i: dict) -> bool:
        target = i["target"]
        return target["code"] == code and (name is None or target["name"] == name)

    return next(i for i in items if matches(i))


# ------------------------------------------------------------------ quyền (BR-001)


async def test_only_admin_can_view(anon, staff, admin):
    assert (await anon.get(LOG)).status_code == 401
    assert (await anon.get(f"{LOG}/catalog")).status_code == 401
    assert (await staff.get(LOG)).status_code == 403
    assert (await staff.get(f"{LOG}/catalog")).status_code == 403
    assert (await admin.get(LOG)).status_code == 200


async def test_catalog_lists_groups_actors_and_date_bounds(admin):
    body = (await admin.get(f"{LOG}/catalog")).json()
    assert [g["label"] for g in body["groups"]][0] == "Đăng nhập, đăng xuất"
    assert [a["label"] for a in body["actors"]] == ["Admin", "Nhân viên", "Hệ thống", "Hội viên"]
    assert body["max_date"] == today().isoformat()
    assert body["min_date"] == today().replace(year=today().year - 1).isoformat()


# ------------------------------------------------------------------ lọc (BR-012..015)


async def test_default_range_is_last_7_days(admin):
    body = (await admin.get(LOG)).json()
    assert body["date_to"] == today().isoformat()
    assert body["date_from"] == (today() - dt.timedelta(days=6)).isoformat()
    assert body["page_size"] == 50


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-10-10", "to": "2026-10-01"},  # đến trước từ
        {"to": (vn_today() + dt.timedelta(days=2)).isoformat()},  # sau hôm nay
        {"from": "2020-01-01"},  # ngoài 12 tháng
    ],
)
async def test_invalid_range_rejected(admin, params):
    r = await admin.get(LOG, params=params)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "E-AUDIT-1"


async def test_unknown_action_rejected(admin):
    r = await admin.get(LOG, params={"action": "member.view"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "E-AUDIT-2"


async def test_filters_by_actor_and_action_newest_first(staff, admin, phones):
    names = []
    for client in (admin, staff):
        phone, full_name = random_phone(), f"LS {uuid.uuid4().hex[:6]}"
        phones.append(phone)
        names.append((full_name, phone))
        r = await client.post(
            f"{M}/temp", json={"full_name": full_name, "phone": phone}, headers=idem()
        )
        assert r.status_code == 201, r.text

    items = await entries(admin, action="member.temp.create")
    assert all(i["action_label"] == "Tạo hồ sơ tạm" for i in items)
    admin_row = by_target(items, None, f"{names[0][0]} · {names[0][1]}")
    staff_row = by_target(items, None, f"{names[1][0]} · {names[1][1]}")
    assert items.index(staff_row) < items.index(admin_row), "mới nhất lên trước"
    assert (admin_row["actor"], admin_row["actor_label"]) == ("admin", "Admin")
    assert (staff_row["actor"], staff_row["actor_label"]) == ("staff", "Nhân viên")
    # Nhân viên: tên chụp lúc làm + mã NV (khóa link); Admin không có
    assert staff_row["actor_name"] == STAFF_NAME
    async with SessionLocal() as s:
        log = await s.get(AuditLog, staff_row["id"])
        user = await s.get(User, log.actor_id)
    assert staff_row["actor_code"] == user.staff_code and user.staff_code.startswith("NV")
    assert (admin_row["actor_name"], admin_row["actor_code"]) == (None, None)

    only_staff = await entries(admin, action="member.temp.create", actor="staff")
    assert all(i["actor"] == "staff" for i in only_staff)
    assert staff_row["id"] in {i["id"] for i in only_staff}
    assert admin_row["id"] not in {i["id"] for i in only_staff}


# ------------------------------------------------------------------ nội dung dòng (BR-004..008)


async def test_member_create_and_update_rows(admin, phones):
    phone = random_phone()
    phones.append(phone)
    full_name = f"LS HV {uuid.uuid4().hex[:6]}"
    r = await admin.post(
        M, json={"full_name": full_name, "phone": phone, "tier": "Khá"}, headers=idem()
    )
    assert r.status_code == 201, r.text
    code = r.json()["member_code"]

    created = by_target(await entries(admin, action="member.create"), code)
    assert created["target"]["name"] == full_name
    changes = {c["field"]: (c["before"], c["after"]) for c in created["changes"]}
    assert changes["Họ tên"] == (None, full_name), "tạo mới: trước là (trống)"
    assert changes["SĐT"] == (None, phone), "SĐT đầy đủ (BR-007)"
    assert changes["Trình độ"] == (None, "Khá")

    version = r.json()["version"]
    r = await admin.patch(f"{M}/{code}", json={"tier": "Bán chuyên", "version": version})
    assert r.status_code == 200, r.text
    updated = by_target(await entries(admin, action="member.update"), code)
    assert updated["changes"] == [{"field": "Trình độ", "before": "Khá", "after": "Bán chuyên"}], (
        "1 lần lưu = 1 dòng, chỉ ô đã đổi"
    )

    # Xem hồ sơ có ghi nhật ký nhưng không hiện ở màn này (BR-002)
    assert (await admin.get(f"{M}/{code}")).status_code == 200
    assert all(i["action"] != "member.view" for i in await entries(admin))


async def test_name_snapshot_kept_after_rename(admin, phones):
    phone = random_phone()
    phones.append(phone)
    old_name = f"LS Cu {uuid.uuid4().hex[:6]}"
    r = await admin.post(M, json={"full_name": old_name, "phone": phone}, headers=idem())
    code, version = r.json()["member_code"], r.json()["version"]
    new_name = f"LS Moi {uuid.uuid4().hex[:6]}"
    r = await admin.patch(f"{M}/{code}", json={"full_name": new_name, "version": version})
    assert r.status_code == 200

    created = by_target(await entries(admin, action="member.create"), code)
    assert created["target"]["name"] == old_name, "dòng cũ giữ tên lúc làm (BR-008)"


async def test_login_and_logout_rows_have_no_values(admin):
    items = await entries(admin, action="auth.login_success", actor="admin")
    assert items and items[0]["changes"] == [], "không đổi dữ liệu -> hiện —"
    assert items[0]["target"]["name"] == "Admin"


async def test_legacy_changes_shape_does_not_break_list(admin):
    """Dòng ghi trước khi chuẩn hóa (vd seed cũ của Lưu bảng giá) -> vẫn 200, hiện "—"."""
    code = f"v{uuid.uuid4().hex[:8]}"
    legacy = [{"from": 100000, "to": 120000, "band": "peak", "day_type": "weekday"}]
    async with SessionLocal() as s:
        s.add_all(
            AuditLog(
                actor_type="system",
                actor_label="Hệ thống",
                action="config.price.update",
                entity_type="price_table",
                entity_code=code,
                detail=detail,
            )
            for detail in ({"version": 2, "changes": legacy}, {"changes": {"name": {"to": "x"}}})
        )
        await s.commit()

    items = await entries(admin, action="config.price.update", actor="system")
    rows = [i for i in items if i["target"]["code"] == code]
    assert len(rows) == 2 and all(r["changes"] == [] for r in rows)


async def test_broken_changes_and_target_do_not_break_list(admin):
    """Phần tử thiếu before/after, giá trị sai kiểu, đối tượng hỏng -> bỏ phần hỏng, vẫn 200."""
    code = f"v{uuid.uuid4().hex[:8]}"
    good = {"field": "Giá", "before": "1 ₫", "after": "2 ₫"}
    changes = [{"field": "x"}, {"field": "y", "before": [1], "after": {"a": 1}}, good]
    async with SessionLocal() as s:
        s.add_all(
            AuditLog(
                actor_type="system",
                actor_label="Hệ thống",
                action="config.price.update",
                entity_type="price_table",
                entity_code=code,
                detail={"target": target, "changes": changes},
            )
            for target in ({"code": 1}, "Bảng giá")
        )
        await s.commit()

    items = await entries(admin, action="config.price.update", actor="system")
    rows = [i for i in items if i["target"]["code"] == code]
    assert len(rows) == 2
    assert all(r["target"]["name"] is None and r["changes"] == [good] for r in rows)


async def test_detail_not_an_object_does_not_break_list(admin):
    """T-22-1: ``detail`` là chuỗi / mảng JSON (dòng cũ, sửa tay) -> chỉ còn mã dòng, vẫn 200."""
    code = f"v{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as s:
        s.add_all(
            AuditLog(
                actor_type="system",
                actor_label="Hệ thống",
                action="config.price.update",
                entity_type="price_table",
                entity_code=code,
                detail=detail,
            )
            for detail in ("chuỗi", [1, 2, 3])
        )
        await s.commit()

    items = await entries(admin, action="config.price.update", actor="system")
    rows = [i for i in items if i["target"]["code"] == code]
    assert len(rows) == 2 and all(r["changes"] == [] for r in rows)


async def test_unknown_staff_keeps_name_without_code(admin):
    """NV không tra được (vd dòng mẫu actor_id 9001) -> có tên, không mã; Hệ thống -> null."""
    code = f"v{uuid.uuid4().hex[:8]}"
    rows = [
        ("staff", 2_000_000_000, "NV9001 · Trần Thị Mai"),
        ("system", None, "Hệ thống"),
    ]
    async with SessionLocal() as s:
        s.add_all(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                actor_label=label,
                action="config.price.update",
                entity_type="price_table",
                entity_code=code,
            )
            for actor_type, actor_id, label in rows
        )
        await s.commit()

    items = [
        i for i in await entries(admin, action="config.price.update") if i["target"]["code"] == code
    ]
    by_actor = {i["actor"]: i for i in items}
    assert (by_actor["staff"]["actor_name"], by_actor["staff"]["actor_code"]) == (
        "Trần Thị Mai",
        None,
    )
    assert (by_actor["system"]["actor_name"], by_actor["system"]["actor_code"]) == (None, None)


# ------------------------------------------------------------------ sắp xếp (lệch docs, đã duyệt)


async def test_sort_by_time(admin):
    now = dt.datetime.now(dt.UTC)
    async with SessionLocal() as s:
        s.add_all(
            AuditLog(
                actor_type="system",
                actor_label="Hệ thống",
                action="config.price.update",
                entity_type="price_table",
                entity_code=f"v{uuid.uuid4().hex[:8]}",
                at=now - dt.timedelta(minutes=minutes),
            )
            for minutes in (1, 2)
        )
        await s.commit()

    def keys(items: list[dict]) -> list[tuple[dt.datetime, int]]:
        return [(dt.datetime.fromisoformat(i["at"]), i["id"]) for i in items]

    params = {"action": "config.price.update", "actor": "system"}
    newest = keys(await entries(admin, **params))
    oldest = keys(await entries(admin, **params, sort="at_asc"))
    assert len(newest) >= 2 and newest == sorted(newest, reverse=True), "mặc định mới trước"
    assert len(oldest) >= 2 and oldest == sorted(oldest), "at_asc: cũ trước"
    assert keys(await entries(admin, **params, sort="at_desc")) == newest

    r = await admin.get(LOG, params={"sort": "name"})
    assert r.status_code == 422


@pytest.mark.parametrize(("size", "expected"), [(None, 50), ("20", 20), ("100", 100)])
async def test_page_size(admin, size, expected):
    params = {"size": size} if size else {}
    r = await admin.get(LOG, params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page_size"] == expected and len(body["items"]) <= expected


@pytest.mark.parametrize("size", ["30", "0", "abc"])
async def test_page_size_only_20_50_100(admin, size):
    assert (await admin.get(LOG, params={"size": size})).status_code == 422


async def test_paging_stable_when_many_rows_share_time(admin):
    """Nhiều dòng trùng ``at``: id phụ giữ thứ tự -> qua các trang không lặp, không sót."""
    day = today() - dt.timedelta(days=5)
    at = dt.datetime.combine(day, dt.time(10, 0, 0, 123457), settings.tz)
    async with SessionLocal() as s:
        rows = [
            AuditLog(
                actor_type="system",
                actor_label="Hệ thống",
                action="config.price.update",
                entity_type="price_table",
                entity_code=f"v{uuid.uuid4().hex[:8]}",
                at=at,
            )
            for _ in range(25)
        ]
        s.add_all(rows)
        await s.commit()
        ours = [r.id for r in rows]

    async def all_pages(sort: str) -> list[int]:
        params = {"from": day, "to": day, "actor": "system", "sort": sort, "size": 20}
        ids, page = [], 1
        while items := await entries(admin, **params, page=page):
            ids += [i["id"] for i in items]
            page += 1
        return ids

    for sort, desc in (("at_desc", True), ("at_asc", False)):
        ids = await all_pages(sort)
        assert len(ids) == len(set(ids)), "không lặp giữa các trang"
        mine = [i for i in ids if i in ours]
        assert mine == sorted(ours, reverse=desc)


# ------------------------------------------------------------------ quy tắc ghi (BR-004, 007, 009)


async def test_qr_payment_is_logged_by_system(anon, admin):
    court = await new_court(admin)
    r = await checkout(anon, [(court["code"], 19)])
    assert r.status_code == 201, r.text
    co = r.json()
    assert (await webhook(anon, sepay_payload(co["pay_ref"], co["amount"]))).status_code == 200
    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "booking.online.paid", AuditLog.entity_code == co["pay_ref"]
            )
        )
    assert row is not None and (row.actor_type, row.actor_id) == ("system", None)
    # T-019: đối tượng là mã đơn (cấp lúc tiền về); mã từng khối nằm trong ``codes``
    order_code = row.detail["order_code"]
    assert order_code.startswith("BK-") and row.detail["codes"] == [f"{order_code}-01"]
    shown = by_target(await entries(admin, action="payment.collect", actor="system"), order_code)
    assert shown["id"] == row.id and shown["action_label"] == "Thu tiền"


async def test_failed_action_leaves_no_row(admin, phones):
    """2 lần Thêm hội viên cùng SĐT cùng lúc: lần thua rollback -> chỉ 1 dòng nhật ký."""
    phone, name = random_phone(), f"Trùng {uuid.uuid4().hex[:6]}"
    phones.append(phone)
    body = {"full_name": name, "phone": phone}
    results = await asyncio.gather(
        admin.post(M, json=body, headers=idem()), admin.post(M, json=body, headers=idem())
    )
    assert sorted(r.status_code for r in results) == [201, 409]
    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                select(AuditLog).where(
                    AuditLog.action == "member.create",
                    AuditLog.detail["target"]["name"].astext == name,
                )
            )
        )
    assert len(rows) == 1


async def test_password_never_logged(admin):
    """Đặt lại MK nhân viên: nhật ký không có mật khẩu thô hay hash."""
    r = await admin.post(
        f"{API}/admin/staff", json={"full_name": "Đổi MK", "password": "Old-pass12"}
    )
    assert r.status_code == 201, r.text
    nv = r.json()
    new_password = f"New-{uuid.uuid4().hex[:8]}A1"
    r = await admin.post(f"{API}/admin/staff/{nv['id']}/password", json={"password": new_password})
    assert r.status_code == 204
    async with SessionLocal() as s:
        hashed = (await s.get(User, nv["id"])).hashed_password
        rows = list(
            await s.scalars(
                select(AuditLog).where(AuditLog.entity_code.in_([nv["staff_code"], str(nv["id"])]))
            )
        )
    assert {r.action for r in rows} >= {"staff.password_reset"}
    for row in rows:
        text = str(row.detail)
        assert new_password not in text and "Old-pass12" not in text and hashed not in text


# ------------------------------------------------------------------ đổi / xóa ảnh đại diện


def _avatar_files() -> dict:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (9, 99, 199)).save(buf, "PNG")
    return {"file": ("a.png", buf.getvalue(), "image/png")}


CROP = {"crop_x": 0, "crop_y": 0, "crop_size": 300}


def _assert_avatar_row(row: dict, label: str, before: str | None, after: str | None) -> None:
    assert row["action_label"] == label
    assert row["changes"] == [{"field": "Ảnh đại diện", "before": before, "after": after}]
    assert "webp" not in str(row).lower() and "RIFF" not in str(row), "không lộ dữ liệu ảnh"


@pytest.mark.parametrize(
    ("who", "actor", "label"), [("admin", "admin", "Admin"), ("staff", "staff", "Nhân viên")]
)
async def test_admin_and_staff_avatar_rows(admin, staff, who, actor, label):
    client = {"admin": admin, "staff": staff}[who]
    avatar = f"{API}/admin/auth/me/avatar"
    r = await client.put(avatar, files=_avatar_files(), data=CROP)
    assert r.status_code == 200, r.text
    updated = await entries(admin, action="account.avatar_update", actor=actor)
    _assert_avatar_row(updated[0], "Đổi ảnh đại diện", None, "Ảnh mới")
    # Đổi khi đã có ảnh: trước = "Có ảnh", không phải trống
    r = await client.put(avatar, files=_avatar_files(), data=CROP)
    assert r.status_code == 200, r.text
    assert (await client.delete(avatar)).status_code == 204
    updated = await entries(admin, action="account.avatar_update", actor=actor)
    deleted = await entries(admin, action="account.avatar_delete", actor=actor)
    _assert_avatar_row(updated[0], "Đổi ảnh đại diện", "Có ảnh", "Ảnh mới")
    _assert_avatar_row(deleted[0], "Xóa ảnh đại diện", "Có ảnh", None)
    for row in (updated[0], deleted[0]):
        assert row["actor"] == actor and row["actor_label"] == label
    if who == "staff":
        assert updated[0]["actor_name"] == STAFF_NAME and updated[0]["actor_code"]

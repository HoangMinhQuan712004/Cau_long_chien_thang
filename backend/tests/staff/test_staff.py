import asyncio
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text, update

from app.core.db import SessionLocal
from app.modules.auth.models import (
    AuditAction,
    AuditLog,
    Role,
    User,
)
from app.modules.auth.utils import (
    staff_code,
    staff_username,
)
from tests.client import API, make_client
from tests.helpers import (
    ADMIN,
    SIGN_IN,
    STAFF,
    STAFF_PASSWORD,
    anon_post,
    audit_count,
    new_staff,
    staff_login,
)


async def test_create_staff_and_list(admin):
    before = await audit_count(AuditAction.STAFF_CREATED)
    r = await admin.post(STAFF, json={"full_name": "Trần Thu", "password": STAFF_PASSWORD})
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"NV\d{3,}", body["staff_code"])
    assert body["username"] == f"thu.{body['staff_code'].lower()}"
    assert body["is_active"] is True
    assert body["active_sessions"] == 0
    assert body["last_login_at"] is None
    assert "password" not in body and "hashed_password" not in body
    assert await audit_count(AuditAction.STAFF_CREATED, body["id"]) == 1
    assert await audit_count(AuditAction.STAFF_CREATED) == before + 1
    async with SessionLocal() as s:
        detail = await s.scalar(
            select(AuditLog.detail).where(
                AuditLog.action == AuditAction.STAFF_CREATED, AuditLog.target_user_id == body["id"]
            )
        )
    assert detail == f"{body['staff_code']} · {body['username']}"

    r = await admin.get(STAFF)
    assert r.status_code == 200
    rows = r.json()
    assert any(s["id"] == body["id"] for s in rows)
    # Chỉ nhân viên, không có Admin/khách
    async with SessionLocal() as s:
        staff_ids = set((await s.scalars(select(User.id).where(User.role == Role.STAFF))).all())
    assert {s["id"] for s in rows} == staff_ids


@pytest.mark.parametrize(
    ("full_name", "name_part"),
    [
        ("Nguyễn Văn An", "an."),
        ("Lê Quang Đạt", "dat."),
        ("ĐỨC", "duc."),  # 1 từ, chữ hoa
        ("  Phạm   Thị   Ánh  ", "anh."),
        ("Hà Nhi 🌟", "nhi."),  # từ cuối không còn chữ ⇒ từ còn chữ gần cuối
        ("!!! ### ✨", ""),  # không còn chữ nào ⇒ chỉ mã
        ("Trần " + "x" * 40, "x" * 24 + "."),  # cắt phần tên ⇒ tổng ≤ 30
    ],
)
async def test_staff_username_generated_from_name_and_code(admin, full_name, name_part):
    body = await new_staff(admin, full_name)
    code = body["staff_code"].lower()
    if name_part.endswith("x."):
        name_part = "x" * (30 - len(code) - 1) + "."
    assert body["username"] == name_part + code
    # Có chữ cái (mã `nv…`) ⇒ không lẫn với SĐT khi đăng nhập
    assert re.fullmatch(r"(?=.*[a-z])[a-z0-9.]{3,30}", body["username"])
    assert body["full_name"] == full_name
    # Đăng nhập được bằng tên sinh ra
    async with make_client() as c:
        assert (await c.post(SIGN_IN, json=staff_login(body))).json()["kind"] == "admin"


def test_staff_code_format():
    assert staff_code(7) == "NV007"
    assert staff_code(1000) == "NV1000"
    assert staff_username("Nguyễn Văn An", "NV007") == "an.nv007"


async def test_create_staff_ignores_username_field(admin, staff):
    """Admin không chọn tên đăng nhập: `username` (form cũ) bị bỏ qua, không 409/422."""
    r = await admin.post(
        STAFF,
        json={"full_name": "Cố Chọn", "username": staff["username"], "password": STAFF_PASSWORD},
    )
    assert r.status_code == 201, r.text
    assert r.json()["username"] == f"chon.{r.json()['staff_code'].lower()}"


async def test_create_staff_concurrent_codes_unique(admin):
    """Tạo song song ⇒ mã (sequence) và tên đăng nhập khác nhau, mã tăng dần."""
    rows = await asyncio.gather(*[new_staff(admin, "Ngô An") for _ in range(5)])
    codes = [row["staff_code"] for row in rows]
    assert len(set(codes)) == 5
    assert len({row["username"] for row in rows}) == 5


async def test_staff_code_never_reused(admin):
    """Mã lấy từ sequence: xóa nhân viên rồi tạo mới ⇒ mã mới lớn hơn, không cấp lại mã cũ."""
    first = await new_staff(admin, "Mai Một")
    async with SessionLocal() as s:
        await s.execute(delete(User).where(User.id == first["id"]))
        await s.commit()
    second = await new_staff(admin, "Mai Hai")
    assert int(second["staff_code"][2:]) > int(first["staff_code"][2:])


async def test_create_staff_skips_code_clashing_with_old_username(admin):
    """Tên đặt tay từ trước (vd `an.nv0xx`) trùng tên sinh ra ⇒ lấy mã kế tiếp, không 500."""
    async with SessionLocal() as s:
        upcoming = await s.scalar(
            text(
                "SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END "
                "FROM staff_code_seq"
            )
        )
        clash = staff_username("An", staff_code(upcoming))
        s.add(User(username=clash, full_name="Cũ", hashed_password="x", role=Role.STAFF))
        await s.commit()
    body = await new_staff(admin, "Lê An")
    assert body["username"] != clash
    assert body["username"].startswith("an.")


@pytest.mark.parametrize(
    "payload",
    [
        {"full_name": "Sai", "password": "ngan123"},  # mật khẩu < 8
        {"full_name": "", "password": STAFF_PASSWORD},
        {"password": STAFF_PASSWORD},
    ],
)
async def test_create_staff_invalid_422(admin, payload):
    r = await admin.post(STAFF, json=payload)
    assert r.status_code == 422, payload


async def test_disable_staff_revokes_sessions_and_blocks_sign_in(admin, staff):
    async with make_client() as c:
        assert (await c.post(SIGN_IN, json=staff_login(staff))).status_code == 200

        r = await admin.patch(f"{STAFF}/{staff['id']}", json={"is_active": False})
        assert r.status_code == 200
        assert r.json()["is_active"] is False
        assert r.json()["active_sessions"] == 0
        assert await audit_count(AuditAction.STAFF_DISABLED, staff["id"]) == 1

        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "account_disabled"

    r = await anon_post(SIGN_IN, staff_login(staff))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "E-001"

    r = await admin.patch(f"{STAFF}/{staff['id']}", json={"is_active": True})
    assert r.json()["is_active"] is True
    assert await audit_count(AuditAction.STAFF_ENABLED, staff["id"]) == 1
    assert (await anon_post(SIGN_IN, staff_login(staff))).status_code == 200


async def test_update_staff_name(admin, staff):
    r = await admin.patch(f"{STAFF}/{staff['id']}", json={"full_name": "Lê Thị Mới"})
    assert r.status_code == 200
    assert r.json()["full_name"] == "Lê Thị Mới"
    # Tên đăng nhập + mã giữ nguyên (nhân viên không phải học tên mới)
    assert r.json()["username"] == staff["username"]
    assert r.json()["staff_code"] == staff["staff_code"]
    assert await audit_count(AuditAction.STAFF_UPDATED, staff["id"]) == 1
    # Không đổi gì ⇒ không ghi thêm lịch sử
    await admin.patch(f"{STAFF}/{staff['id']}", json={"full_name": "Lê Thị Mới"})
    assert await audit_count(AuditAction.STAFF_UPDATED, staff["id"]) == 1

    async with make_client() as c:
        r = await c.post(SIGN_IN, json=staff_login(staff))
        assert r.json()["account"]["display_name"] == "Lê Thị Mới"


async def test_reset_staff_password(admin, staff):
    async with make_client() as c:
        assert (await c.post(SIGN_IN, json=staff_login(staff))).status_code == 200

        r = await admin.post(f"{STAFF}/{staff['id']}/password", json={"password": "MatKhau@moi1"})
        assert r.status_code == 204
        assert await audit_count(AuditAction.STAFF_PASSWORD_RESET, staff["id"]) == 1

        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "password_changed"

    r = await anon_post(SIGN_IN, staff_login(staff))
    assert r.json()["detail"]["code"] == "E-001"
    assert (await anon_post(SIGN_IN, staff_login(staff, "MatKhau@moi1"))).status_code == 200

    r = await admin.post(f"{STAFF}/{staff['id']}/password", json={"password": "ngan"})
    assert r.status_code == 422


async def test_reset_password_clears_lock(admin, staff):
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == staff["id"])
            .values(failed_login_count=3, locked_until=datetime.now(UTC) + timedelta(minutes=5))
        )
        await s.commit()
    await admin.post(f"{STAFF}/{staff['id']}/password", json={"password": "MatKhau@moi1"})
    r = await anon_post(SIGN_IN, staff_login(staff, "MatKhau@moi1"))
    assert r.status_code == 200


async def test_list_and_revoke_staff_sessions(admin, staff):
    async with make_client() as a, make_client() as b:
        await a.post(
            SIGN_IN,
            json=staff_login(staff),
            headers={"User-Agent": "May quay 1", "X-Forwarded-For": "192.0.2.21"},
        )
        await b.post(SIGN_IN, json=staff_login(staff))

        r = await admin.get(f"{STAFF}/{staff['id']}/sessions")
        assert r.status_code == 200
        sessions = r.json()
        assert len(sessions) == 2
        first = next(s for s in sessions if s["user_agent"] == "May quay 1")
        assert first["ip"] == "192.0.2.21"
        assert {"id", "created_at", "expires_at", "user_agent", "ip"} <= first.keys()

        r = await admin.delete(f"{STAFF}/{staff['id']}/sessions/{first['id']}")
        assert r.status_code == 204
        assert await audit_count(AuditAction.SESSION_REVOKED, staff["id"]) == 1
        assert (await a.get(f"{API}/admin/auth/me")).status_code == 401
        assert (await b.get(f"{API}/admin/auth/me")).status_code == 200

        # Phiên đã thu hồi ⇒ 404
        r = await admin.delete(f"{STAFF}/{staff['id']}/sessions/{first['id']}")
        assert r.status_code == 404
        assert len((await admin.get(f"{STAFF}/{staff['id']}/sessions")).json()) == 1

    # Phiên của nhân viên khác ⇒ 404
    other = await new_staff(admin)
    async with make_client() as c:
        await c.post(SIGN_IN, json=staff_login(other))
    other_session = (await admin.get(f"{STAFF}/{other['id']}/sessions")).json()[0]
    r = await admin.delete(f"{STAFF}/{staff['id']}/sessions/{other_session['id']}")
    assert r.status_code == 404


async def test_staff_api_not_staff_id_404(admin, customer):
    customer_id = (await customer.get(f"{API}/auth/me")).json()["id"]
    async with SessionLocal() as s:
        admin_id = await s.scalar(select(User.id).where(User.role == Role.ADMIN))
    for user_id in [admin_id, customer_id, 999_999]:
        r = await admin.patch(f"{STAFF}/{user_id}", json={"is_active": False})
        assert r.status_code == 404
        r = await admin.post(f"{STAFF}/{user_id}/password", json={"password": "MatKhau@moi1"})
        assert r.status_code == 404
        assert (await admin.get(f"{STAFF}/{user_id}/sessions")).status_code == 404
        assert (await admin.delete(f"{STAFF}/{user_id}/sessions/1")).status_code == 404
    # Admin vẫn đăng nhập được (không bị khóa / đổi mật khẩu)
    assert (await anon_post(SIGN_IN, ADMIN)).status_code == 200

"""T-014 việc 11: danh mục vợt – API của Admin, tự thêm khi lưu hội viên (chọn "Khác…")."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select

from app.core.audit import AuditActor, AuditLog
from app.core.db import SessionLocal
from app.modules.members import rackets
from app.modules.members.models import Customer, Racket
from tests.conftest import API, idem
from tests.helpers_booking import patch_member, random_phone

R = f"{API}/rackets"
M = f"{API}/members"
ACTOR = AuditActor(type="admin", id=None, label="Test")


@pytest.fixture
async def cleanup():
    """Xóa vợt / hồ sơ test tạo ra (tên chứa ``tag``) – DB test dùng chung cả phiên."""
    tag = f"zz{uuid.uuid4().hex[:6]}"
    yield tag
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.full_name.contains(tag)))
        await s.execute(delete(Racket).where(Racket.name_key.contains(tag)))
        await s.commit()


async def racket_rows(key: str) -> list[Racket]:
    async with SessionLocal() as s:
        return list(await s.scalars(select(Racket).where(Racket.name_key == key)))


# ------------------------------------------------------------------ API danh mục


async def test_admin_manages_staff_reads(admin, staff, cleanup):
    r = await staff.post(R, json={"name": f"Yonex {cleanup}"})
    assert r.status_code == 403
    created = await admin.post(R, json={"name": f"  Yonex   {cleanup} "})
    assert created.status_code == 201, created.text
    racket = created.json()
    assert racket["name"] == f"Yonex {cleanup}" and racket["is_active"] is True

    r = await admin.post(R, json={"name": f"YONEX {cleanup.upper()}"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-5"
    assert (await admin.post(R, json={"name": "   "})).status_code == 422

    hidden = await admin.patch(f"{R}/{racket['id']}", json={"is_active": False})
    assert hidden.status_code == 200 and hidden.json()["is_active"] is False
    names = lambda r: {x["name"] for x in r.json()}  # noqa: E731
    assert racket["name"] not in names(await staff.get(R))
    assert racket["name"] not in names(await staff.get(R, params={"all": 1}))  # NV: bỏ qua all
    assert racket["name"] in names(await admin.get(R, params={"all": 1}))
    assert (await staff.patch(f"{R}/{racket['id']}", json={"is_active": True})).status_code == 403

    other = (await admin.post(R, json={"name": f"Lining {cleanup}"})).json()
    r = await admin.patch(f"{R}/{other['id']}", json={"name": f"yonex {cleanup}"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-5"
    r = await admin.patch(f"{R}/{other['id']}", json={"name": f"Lining {cleanup} Pro"})
    assert r.status_code == 200 and r.json()["name"] == f"Lining {cleanup} Pro"
    assert (await admin.patch(f"{R}/999999", json={"is_active": True})).status_code == 404


async def test_can_flag_and_anonymous(admin, staff, anon):
    assert (await admin.get(M)).json()["can"]["manage_rackets"] is True
    assert (await staff.get(M)).json()["can"]["manage_rackets"] is False
    assert (await anon.get(R)).status_code == 401


# ------------------------------------------------------------------ hội viên -> tự thêm


async def racket_create_audits(name: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).where(
                AuditLog.action == "racket.create", AuditLog.detail["name"].astext == name
            )
        )


async def test_member_racket_added_and_reused(admin, staff, cleanup):
    body = {"full_name": f"HV {cleanup}", "phone": random_phone(), "racket": f"Victor  {cleanup}"}
    first = await staff.post(M, json=body, headers=idem())
    assert first.status_code == 201 and first.json()["racket"] == f"Victor {cleanup}"
    [row] = await racket_rows(f"victor {cleanup}")
    assert row.is_active
    assert await racket_create_audits(f"Victor {cleanup}") == 1  # vợt mới ghi nhật ký (T-020)

    # Gõ khác hoa thường / khoảng trắng -> dùng lại tên chuẩn trong danh mục (kể cả vợt đã ẩn)
    await admin.patch(f"{R}/{row.id}", json={"is_active": False})
    second = await staff.post(
        M,
        json={**body, "phone": random_phone(), "racket": f" VICTOR {cleanup.upper()} "},
        headers=idem(),
    )
    assert second.status_code == 201 and second.json()["racket"] == f"Victor {cleanup}"
    assert await racket_create_audits(f"Victor {cleanup}") == 1  # dùng lại -> không ghi thêm
    code = second.json()["member_code"]
    r = await patch_member(staff, code, {"racket": f"Apacs {cleanup}"})
    assert r.status_code == 200 and r.json()["racket"] == f"Apacs {cleanup}"
    assert len(await racket_rows(f"apacs {cleanup}")) == 1
    # Đổi tên vợt trong danh mục không đổi hồ sơ cũ (lưu dạng chữ)
    await admin.patch(f"{R}/{row.id}", json={"name": f"Victor {cleanup} Mới"})
    assert (await admin.get(f"{M}/{first.json()['member_code']}")).json()["racket"] == (
        f"Victor {cleanup}"
    )
    r = await patch_member(staff, code, {"racket": ""})
    assert r.status_code == 200 and r.json()["racket"] is None


async def test_concurrent_new_racket_one_row(cleanup):
    """Hai transaction cùng thêm một vợt mới: B chờ A trên UNIQUE(name_key) rồi ON CONFLICT DO
    NOTHING -> dùng lại dòng của A (không IntegrityError / 500)."""
    async with SessionLocal() as a, SessionLocal() as b:
        assert await rackets.ensure(a, f"Felet {cleanup}", ACTOR) == f"Felet {cleanup}"
        second = asyncio.create_task(rackets.ensure(b, f"  felet {cleanup} ", ACTOR))
        await asyncio.sleep(0.3)
        assert not second.done()  # đang chờ khóa của A
        await a.commit()
        assert await second == f"Felet {cleanup}"
        await b.commit()
    assert len(await racket_rows(f"felet {cleanup}")) == 1
    assert await racket_create_audits(f"Felet {cleanup}") == 1  # chỉ máy thêm thật ghi nhật ký

"""T-014 việc 11: danh mục vợt – API của Admin, tự thêm khi lưu hội viên (chọn "Khác…")."""

import uuid

import pytest
from sqlalchemy import delete, func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.members.models import Customer, Racket
from tests.conftest import API, idem
from tests.helpers_booking import patch_member, random_phone

R = f"{API}/rackets"
M = f"{API}/members"


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
    # NV mặc định quản lý được vợt (người dùng chốt 2026-11-05): qua kiểm quyền, tới kiểm dữ liệu
    r = await staff.post(R, json={"name": "   "})
    assert r.status_code == 422
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
    assert racket["name"] in names(
        await staff.get(R, params={"all": 1})
    )  # NV có quyền (người dùng chốt 2026-11-05)
    assert racket["name"] in names(await admin.get(R, params={"all": 1}))
    shown = await staff.patch(
        f"{R}/{racket['id']}", json={"is_active": True}
    )  # người dùng chốt 2026-11-05
    assert shown.status_code == 200 and shown.json()["is_active"] is True

    other = (await admin.post(R, json={"name": f"Lining {cleanup}"})).json()
    r = await admin.patch(f"{R}/{other['id']}", json={"name": f"yonex {cleanup}"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-MEM-5"
    r = await admin.patch(f"{R}/{other['id']}", json={"name": f"Lining {cleanup} Pro"})
    assert r.status_code == 200 and r.json()["name"] == f"Lining {cleanup} Pro"
    assert (await admin.patch(f"{R}/999999", json={"is_active": True})).status_code == 404


async def test_can_flag_and_anonymous(admin, staff, anon):
    assert (await admin.get(M)).json()["can"]["manage_rackets"] is True
    assert (await staff.get(M)).json()["can"][
        "manage_rackets"
    ] is True  # người dùng chốt 2026-11-05
    assert (await anon.get(R)).status_code == 401


# ------------------------------------------------------------------ T-033: vợt tự nhập


async def racket_create_audits(name: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).where(
                AuditLog.action == "racket.create", AuditLog.detail["name"].astext == name
            )
        )


async def test_member_racket_is_free_text_not_added_to_catalog(admin, staff, cleanup):
    body = {"full_name": f"HV {cleanup}", "phone": random_phone(), "racket": f" Victor  {cleanup} "}
    first = await staff.post(M, json=body, headers=idem())
    assert first.status_code == 201 and first.json()["racket"] == f"Victor {cleanup}"
    assert await racket_rows(f"victor {cleanup}") == []  # AC3: không sinh dòng danh mục
    assert await racket_create_audits(f"Victor {cleanup}") == 0

    # Vợt đã có trong danh mục: giữ đúng chữ người nhập (không đổi sang tên trong danh mục)
    r = await admin.post(R, json={"name": f"Apacs {cleanup}"}, headers=idem())
    assert r.status_code == 201, r.text
    code = first.json()["member_code"]
    r = await patch_member(staff, code, {"racket": f"APACS {cleanup.upper()}"})
    assert r.status_code == 200 and r.json()["racket"] == f"APACS {cleanup.upper()}"
    assert len(await racket_rows(f"apacs {cleanup}")) == 1

    # Quá 100 ký tự sau khi gộp khoảng trắng -> 422 E-001; nhiều khoảng trắng mà gộp ≤ 100 -> lưu
    r = await patch_member(staff, code, {"racket": "x" * 101})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001"
    spaced = "  ".join(["Yonex"] * 16)  # 94 ký tự sau khi gộp, 110 trước khi gộp
    r = await patch_member(staff, code, {"racket": spaced})
    assert r.status_code == 200 and r.json()["racket"] == " ".join(["Yonex"] * 16)
    r = await patch_member(staff, code, {"racket": "   "})
    assert r.status_code == 200 and r.json()["racket"] is None

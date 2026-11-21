"""Admin › Kỷ lục & video (21/11): họ tên thật, SĐT đầy đủ, giới tính; lọc theo ngày đo."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, update

from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import API

people = base.people

ADMIN = f"{API}/admin/speed-records"
TAG = f"rec21:{uuid.uuid4().hex[:8]}:"


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord).where(SpeedRecord.source_ref.startswith(TAG)))
        await s.commit()


async def record(cid: int, kmh: int, at: datetime) -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid, speed_kmh=kmh, measured_at=at, source_ref=f"{TAG}{uuid.uuid4()}"
        )
        s.add(r)
        await s.commit()
        return r.id


def mine(rows: list[dict]) -> dict[int, dict]:
    return {r["id"]: r for r in rows}


async def test_admin_row_has_full_name_phone_gender(admin, people):
    hv = await people("Nguyễn Văn Đập")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == hv.customer_id)
            .values(gender="male", nickname="sấm sét")
        )
        await s.commit()
    rid = await record(hv.customer_id, 333, datetime(2026, 11, 18, 3, 0, tzinfo=UTC))

    r = await admin.get(ADMIN, params={"from": "2026-11-18", "to": "2026-11-18"})
    assert r.status_code == 200
    row = mine(r.json()["items"])[rid]
    assert row["member_name"] == "sấm sét"  # tên hiển thị giữ nguyên
    assert (row["full_name"], row["phone"], row["gender"]) == ("Nguyễn Văn Đập", hv.phone, "male")


async def test_date_filter_uses_court_timezone_and_is_inclusive(admin, people):
    hv = await people("Lọc Ngày")
    # 17/11 23:30 VN = 17/11 16:30 UTC · 18/11 00:10 VN = 17/11 17:10 UTC · 24/11 12:00 VN
    late_17 = await record(hv.customer_id, 201, datetime(2026, 11, 17, 16, 30, tzinfo=UTC))
    early_18 = await record(hv.customer_id, 202, datetime(2026, 11, 17, 17, 10, tzinfo=UTC))
    on_24 = await record(hv.customer_id, 203, datetime(2026, 11, 24, 5, 0, tzinfo=UTC))

    async def ids(**params) -> set[int]:
        r = await admin.get(ADMIN, params=params)
        assert r.status_code == 200, r.text
        return set(mine(r.json()["items"])) & {late_17, early_18, on_24}

    assert await ids(**{"from": "2026-11-18", "to": "2026-11-24"}) == {
        early_18,
        on_24,
    }  # cả hai đầu
    assert await ids(**{"from": "2026-11-17", "to": "2026-11-17"}) == {late_17}
    assert await ids(**{"to": "2026-11-17"}) == {late_17}  # chỉ một đầu
    assert await ids(**{"from": "2026-11-24"}) == {on_24}
    assert await ids(**{"from": "2026-11-17", "to": "2026-11-24"}) == {late_17, early_18, on_24}

    bad = await admin.get(ADMIN, params={"from": "2026-11-20", "to": "2026-11-19"})
    assert bad.status_code == 422
    assert bad.json()["detail"] == {
        "code": "E-001",
        "message": "Từ ngày phải trước hoặc bằng Đến ngày.",
    }


async def test_contact_fields_admin_only(staff):
    """Nhân viên không có quyền quản lý video thì không xem được danh sách (giữ quyền cũ)."""
    r = await staff.get(ADMIN)
    assert r.status_code == 403

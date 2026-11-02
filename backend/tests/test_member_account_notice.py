"""T-026: Thêm hội viên báo tài khoản đăng nhập (vừa tạo hay đã có) + hạn mật khẩu ban đầu."""

import datetime as dt

import pytest
from sqlalchemy import delete, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.members.models import Customer
from tests.conftest import API, idem, new_customer, unique_phone

M = f"{API}/members"


@pytest.fixture
async def phones():
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.execute(delete(User).where(User.phone.in_(created)))
        await s.commit()


async def test_new_phone_creates_account_with_deadline_and_replay(staff, phones):
    phone = unique_phone()
    phones.append(phone)
    headers = idem()
    body = {"full_name": "Nguyễn Tài Khoản", "phone": phone}
    before = dt.datetime.now(dt.UTC)
    first = await staff.post(M, json=body, headers=headers)  # NV cũng thêm được (AC6)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["account_created"] is True
    deadline = dt.datetime.fromisoformat(data["initial_password_expires_at"])
    days = dt.timedelta(days=settings.MEMBER_INITIAL_PASSWORD_DAYS)
    assert before + days <= deadline <= dt.datetime.now(dt.UTC) + days

    # AC4: gửi lại cùng key -> đúng như lần đầu (cờ + hạn), không tạo lại
    again = await staff.post(M, json=body, headers=headers)
    assert again.status_code == 201 and again.headers.get("idempotent-replayed") == "true"
    assert again.json() == data

    # AC5: không có mật khẩu ở response / audit
    assert [k for k in data if "password" in k] == ["initial_password_expires_at"]
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.phone == phone))
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "member.create", AuditLog.entity_code == data["member_code"]
            )
        )
    assert user.must_change_password and user.member_account_at is not None
    assert user.hashed_password not in first.text
    assert "password" not in str(row.detail).lower() and user.hashed_password not in str(row.detail)


async def test_existing_account_keeps_password(admin, phones):
    phone = unique_phone()
    phones.append(phone)
    async with new_customer(phone):  # tài khoản khách đã có (không phải sân tạo)
        pass
    r = await admin.post(M, json={"full_name": "Đã Có Tài Khoản", "phone": phone}, headers=idem())
    assert r.status_code == 201, r.text
    data = r.json()
    assert (data["account_created"], data["initial_password_expires_at"]) == (False, None)
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.phone == phone))
    assert not user.must_change_password and user.member_account_at is None

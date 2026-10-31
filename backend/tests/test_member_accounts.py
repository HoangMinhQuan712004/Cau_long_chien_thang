"""T-015 bảo mật: đăng ký trùng không lộ loại tài khoản; mật khẩu ban đầu (= SĐT) hết hạn 3 ngày."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.members.models import Customer
from tests.conftest import (
    API,
    _client,
    idem,
    new_registered,
    register,
    sign_in,
    unique_phone,
)

M = f"{API}/members"


@pytest.fixture
async def phones():
    """SĐT test tạo ra -> xóa hồ sơ + tài khoản sau test."""
    created: list[str] = []
    yield created
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(created)))
        await s.execute(delete(User).where(User.phone.in_(created)))
        await s.commit()


async def member_account(admin, phones: list[str]) -> str:
    """Admin thêm hội viên -> tài khoản khách mật khẩu = SĐT, bắt đổi lần đầu."""
    phone = unique_phone()
    phones.append(phone)
    r = await admin.post(
        M, json={"full_name": f"HV {uuid.uuid4().hex[:6]}", "phone": phone}, headers=idem()
    )
    assert r.status_code == 201, r.text
    return phone


async def age_initial_password(phone: str, days: float) -> None:
    """Giả thời gian: lùi mốc ``member_account_at`` ``days`` ngày."""
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.phone == phone)
            .values(member_account_at=datetime.now(UTC) - timedelta(days=days))
        )
        await s.commit()


async def register_phone(phone: str):
    """Đăng ký 2 bước (T-021): lỗi trùng chỉ báo sau khi nhập đúng mã."""
    async with _client() as c:
        return await register(c, phone, "Người Lạ")


# ------------------------------------------------------------------ đăng ký trùng (E-AUTH-22)


async def test_duplicate_register_does_not_reveal_member_account(admin, phones):
    self_registered = unique_phone()
    phones.append(self_registered)
    async with new_registered(self_registered):  # tài khoản tự đăng ký đã xác minh
        pass
    member_phone = await member_account(admin, phones)

    normal, member = await register_phone(self_registered), await register_phone(member_phone)
    assert normal.status_code == member.status_code == 409
    a, b = normal.json()["detail"], member.json()["detail"]
    assert (a["phone"], b["phone"]) == (self_registered, member_phone)  # SĐT chính người gọi gửi
    assert {**a, "phone": None} == {**b, "phone": None}  # trùng khít: mã, câu chữ, các trường
    assert a["code"] == "E-AUTH-22"
    assert "hội viên" not in b["message"] and "ban đầu" not in b["message"]


# ------------------------------------------------------------------ mật khẩu ban đầu: hạn 3 ngày


async def test_initial_password_works_within_window(admin, phones):
    phone = await member_account(admin, phones)
    await age_initial_password(phone, settings.MEMBER_INITIAL_PASSWORD_DAYS - 0.1)
    async with _client() as c:
        r = await sign_in(c, phone, phone)
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "member" and r.json()["account"]["must_change_password"]


async def test_initial_password_expired_blocks_login_and_sessions(admin, phones):
    phone = await member_account(admin, phones)
    async with _client() as c:
        assert (await sign_in(c, phone, phone)).status_code == 200  # phiên cấp khi còn hạn
        await age_initial_password(phone, settings.MEMBER_INITIAL_PASSWORD_DAYS + 0.01)

        r = await sign_in(c, phone, phone)  # đúng mật khẩu nhưng quá hạn -> không cấp phiên
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-30"
        for call in (
            c.get(f"{API}/auth/me"),
            c.post(f"{API}/auth/password/change", json={"new_password": "MatKhauMoi1"}),
        ):
            r = await call
            assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-30"

    async with _client() as c:
        r = await sign_in(c, phone, "SaiMatKhau1")  # sai mật khẩu: lỗi cũ + đếm lần sai
        assert r.status_code == 401 and r.json()["detail"]["code"] == "E-AUTH-10"
    async with SessionLocal() as s:
        assert await s.scalar(select(User.failed_login_count).where(User.phone == phone)) == 1

import asyncio
from datetime import UTC, datetime, timedelta

import jwt
from httpx import Cookies
from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import (
    ALGORITHM,
    TokenClaims,
    create_token,
    decode_token,
)
from app.modules.auth import service
from app.modules.auth.models import (
    AdminSession,
    User,
)
from tests.client import API, make_client
from tests.helpers import (
    RESET_CONFIRM,
    SIGN_IN,
    STAFF,
    STAFF_PASSWORD,
    get_me,
    get_reset_token,
    request_otp,
    staff_login,
)


async def test_staff_many_sessions_at_once(admin, staff):
    """Bỏ E-003: nhân viên đăng nhập nhiều máy cùng lúc, mỗi máy 1 phiên riêng."""

    async def attempt() -> int:
        async with make_client() as c:
            return (await c.post(SIGN_IN, json=staff_login(staff))).status_code

    assert await asyncio.gather(attempt(), attempt(), attempt()) == [200, 200, 200]
    async with make_client() as a, make_client() as b:
        assert (await a.post(SIGN_IN, json=staff_login(staff))).status_code == 200
        assert (await b.post(SIGN_IN, json=staff_login(staff))).status_code == 200
        await a.post(f"{API}/admin/auth/logout")
        assert (await a.get(f"{API}/admin/auth/me")).status_code == 401
        # Đăng xuất máy này không ảnh hưởng máy kia (BR-011)
        assert (await b.get(f"{API}/admin/auth/me")).status_code == 200

    r = await admin.get(STAFF)
    row = next(s for s in r.json() if s["id"] == staff["id"])
    assert row["active_sessions"] == 4
    assert row["last_login_at"] is not None


async def test_session_expiry_codes(staff):
    async with make_client() as c:
        assert (await c.post(SIGN_IN, json=staff_login(staff))).status_code == 200
        async with SessionLocal() as s:
            await s.execute(
                update(AdminSession)
                .where(AdminSession.user_id == staff["id"])
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await s.commit()
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "expired"

    async with make_client() as anon_client:
        r = await anon_client.get(f"{API}/admin/auth/me")
        assert r.json()["detail"]["code"] == "unauthenticated"


async def test_admin_apis_need_admin_session(admin, customer, staff):
    assert (await admin.get(STAFF)).status_code == 200
    assert (await customer.get(STAFF)).status_code == 401
    async with make_client() as c:
        await c.post(SIGN_IN, json=staff_login(staff))
        # Nhân viên không có quyền chủ sân
        assert (await c.get(STAFF)).status_code == 403
        r = await c.post(
            STAFF, json={"full_name": "X", "username": "nv.moi", "password": STAFF_PASSWORD}
        )
        assert r.status_code == 403
    # Không có API tạo thêm Admin (BR-001)
    r = await admin.post(f"{API}/admin/users", json={"phone": "0911111111"})
    assert r.status_code == 404


async def test_jwt_old_token_version_rejected(customer):
    """JWT mang `ver` cũ (cả token cấp trước khi có claim – coi là 0) bị từ chối; `ver` mới OK."""
    user_id = (await get_me(customer))["id"]
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == user_id).values(token_version=3))
        await s.commit()
        assert await service.get_customer(s, TokenClaims(str(user_id), 2)) is None
        assert await service.get_customer(s, TokenClaims(str(user_id), 3)) is not None
    legacy = jwt.encode(
        {"sub": str(user_id), "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert decode_token(legacy, "access") == TokenClaims(str(user_id), 0)
    # `sub` không phải id số ⇒ coi như token sai (không 500 ở `int(sub)`)
    odd = jwt.encode(
        {"sub": "abc", "type": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )
    assert decode_token(odd, "access") is None
    # Cookie hiện tại mang ver 0 ⇒ hết hiệu lực
    assert (await customer.get(f"{API}/auth/me")).status_code == 401


async def test_password_reset_invalidates_old_customer_jwt(customer, anon, sent_otps):
    """Cookie khách bị lộ hết dùng được sau khi đặt lại mật khẩu – refresh không gia hạn mãi."""
    user = await get_me(customer)
    stolen = make_client()
    stolen.cookies = Cookies(customer.cookies)
    async with stolen:
        assert (await stolen.get(f"{API}/auth/me")).status_code == 200

        token = await get_reset_token(anon, user["phone"], await request_otp(anon, sent_otps, user))
        r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "MatKhau@moi1"})
        assert r.status_code == 204

        assert (await stolen.get(f"{API}/auth/me")).status_code == 401
        assert (await stolen.post(f"{API}/auth/refresh")).status_code == 401

    # Đăng nhập lại ngay (cùng giây với lúc đổi) bằng mật khẩu mới ⇒ dùng được
    r = await customer.post(SIGN_IN, json={"login": user["phone"], "password": "MatKhau@moi1"})
    assert r.status_code == 200
    assert (await customer.get(f"{API}/auth/me")).status_code == 200
    assert (await customer.post(f"{API}/auth/refresh")).status_code == 200
    assert (await customer.get(f"{API}/auth/me")).status_code == 200


async def test_refresh_racing_password_reset_token_dies(customer, anon, sent_otps):
    """Token cấp từ bản đọc trước khi đổi mật khẩu commit vẫn bị từ chối (ver cũ)."""
    user = await get_me(customer)
    claims = decode_token(customer.cookies["refresh_token"], "refresh")
    assert claims is not None
    async with SessionLocal() as racing:
        # Bước "refresh" song song: đã đọc user, chưa kịp trả token
        stale = await service.get_customer(racing, claims)
        assert stale is not None

        token = await get_reset_token(anon, user["phone"], await request_otp(anon, sent_otps, user))
        r = await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": "MatKhau@moi1"})
        assert r.status_code == 204

        # Refresh cấp token từ bản đọc cũ (sau khi đổi mật khẩu đã commit)
        access = create_token(str(stale.id), "access", stale.token_version)
        refresh = create_token(str(stale.id), "refresh", stale.token_version)

    async with make_client() as c:
        r = await c.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 401
        c.cookies.set("refresh_token", refresh, path=f"{API}/auth")
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401
        # Đối chứng: cùng cách gửi cookie, token `ver` mới ⇒ refresh được
        c.cookies.clear()
        fresh = create_token(str(stale.id), "refresh", stale.token_version + 1)
        c.cookies.set("refresh_token", fresh, path=f"{API}/auth")
        assert (await c.post(f"{API}/auth/refresh")).status_code == 200

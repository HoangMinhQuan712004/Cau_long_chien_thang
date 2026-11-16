"""T-077: phiên Admin / NV trượt 30 ngày; refresh token khách 30 ngày, cookie path "/" và chịu
được hai lần làm mới cùng lúc."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import AdminSession
from tests.conftest import API, _client, new_customer, sign_in
from tests.test_auth import PASSWORD, create_staff

IDLE_S = settings.ADMIN_SESSION_IDLE_DAYS * 86400


def admin_cookie(r) -> str | None:
    return next(
        (v for v in r.headers.get_list("set-cookie") if v.startswith("admin_session=")), None
    )


async def session_row(user_id: int) -> AdminSession:
    async with SessionLocal() as s:
        return await s.scalar(
            select(AdminSession)
            .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
            .order_by(AdminSession.id.desc())
            .limit(1)
        )


async def set_expiry(row_id: int, expires_at: datetime) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(AdminSession).where(AdminSession.id == row_id).values(expires_at=expires_at)
        )
        await s.commit()


def max_age(cookie: str | None) -> int:
    assert cookie is not None
    part = next(p for p in cookie.lower().split(";") if p.strip().startswith("max-age="))
    return int(part.split("=")[1])


def remaining(expires_at: datetime) -> int:
    return int((expires_at - datetime.now(UTC)).total_seconds()) + 1


def near(a: datetime, b: datetime, seconds: int = 120) -> bool:
    return abs((a - b).total_seconds()) < seconds


async def test_admin_session_slides_and_renews_at_most_hourly(admin):
    """AC5, AC7: đăng nhập -> 30 ngày; còn dùng sau > 1 giờ -> gia hạn + gửi lại cookie;
    trong vòng 1 giờ -> không ghi DB, không gửi cookie."""
    nv = await create_staff(admin, "Phiên Trượt")
    async with _client() as c:
        r = await sign_in(c, nv["username"], PASSWORD)
        assert f"max-age={IDLE_S}" in admin_cookie(r).lower()
        row = await session_row(nv["id"])
        assert near(row.expires_at, datetime.now(UTC) + timedelta(days=30))

        r = await c.get(f"{API}/admin/auth/me")  # vừa đăng nhập: không ghi DB
        assert r.status_code == 200
        assert (await session_row(nv["id"])).expires_at == row.expires_at
        assert max_age(admin_cookie(r)) <= remaining(row.expires_at)  # cookie theo hạn DB

        # Lần gia hạn trước cách đây 13 giờ (vd đăng nhập hôm qua): request kế tiếp gia hạn
        stale = datetime.now(UTC) + timedelta(days=30) - timedelta(hours=13)
        await set_expiry(row.id, stale)
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 200
        cookie = admin_cookie(r)
        assert IDLE_S - 60 < max_age(cookie) <= IDLE_S  # hạn còn lại sau khi gia hạn
        assert "httponly" in cookie.lower()
        renewed = (await session_row(nv["id"])).expires_at
        assert near(renewed, datetime.now(UTC) + timedelta(days=30))

        r = await c.get(f"{API}/admin/auth/me")  # trong 1 giờ: không ghi lại
        assert (await session_row(nv["id"])).expires_at == renewed
        assert IDLE_S - 120 < max_age(admin_cookie(r)) <= remaining(renewed)


async def test_cookie_never_outlives_db_session(admin):
    """Mọi request hợp lệ gửi lại cookie với max-age = thời gian còn tới expires_at (không dài
    hơn DB), không ghi DB."""
    nv = await create_staff(admin, "Cookie Theo DB")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        # Vừa gia hạn 30 phút trước (chưa tới lượt gia hạn kế tiếp)
        recent = datetime.now(UTC) + timedelta(days=30) - timedelta(minutes=30)
        await set_expiry(row.id, recent)
        r = await c.get(f"{API}/admin/auth/me")
        assert (await session_row(nv["id"])).expires_at == recent
        assert remaining(recent) - 60 < max_age(admin_cookie(r)) <= remaining(recent)


async def test_session_valid_at_deploy_is_renewed_and_idle_expiry_still_ends_it(admin):
    """Phiên 12 giờ cũ còn hạn lúc triển khai -> gia hạn ngay request đầu (Q4). Quá hạn trượt ->
    401 ``expired`` như cũ."""
    nv = await create_staff(admin, "Phiên Cũ")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        await set_expiry(row.id, datetime.now(UTC) + timedelta(hours=11))
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 200 and admin_cookie(r) is not None
        assert near(
            (await session_row(nv["id"])).expires_at, datetime.now(UTC) + timedelta(days=30)
        )

        await set_expiry(row.id, datetime.now(UTC) - timedelta(seconds=1))
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 401 and r.json()["detail"]["reason"] == "expired"


async def test_concurrent_requests_renew_once(admin):
    nv = await create_staff(admin, "Hai Request")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        await set_expiry(row.id, datetime.now(UTC) + timedelta(days=2))
        results = await asyncio.gather(*(c.get(f"{API}/admin/auth/me") for _ in range(4)))
        assert {r.status_code for r in results} == {200}
        renewed = (await session_row(nv["id"])).expires_at
        assert near(renewed, datetime.now(UTC) + timedelta(days=30))
        assert all(max_age(admin_cookie(r)) <= remaining(renewed) for r in results)


async def test_logout_is_not_overridden_by_renewal(admin):
    """Đăng xuất lúc phiên đến hạn gia hạn: chỉ có cookie xóa, phiên bị thu hồi."""
    nv = await create_staff(admin, "Đăng Xuất")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        await set_expiry(row.id, datetime.now(UTC) + timedelta(days=1))
        r = await c.post(f"{API}/admin/auth/logout")
        assert r.status_code == 204
        cookies = [v for v in r.headers.get_list("set-cookie") if v.startswith("admin_session=")]
        assert len(cookies) == 1 and "max-age=0" in cookies[0].lower()
        assert (await c.get(f"{API}/admin/auth/me")).status_code == 401


def refresh_cookies(r) -> list[str]:
    return [v for v in r.headers.get_list("set-cookie") if v.startswith("refresh_token=")]


async def test_refresh_cookie_path_root_30_days_and_legacy_path_cleared():
    async with new_customer() as c:
        r = await c.post(f"{API}/auth/refresh")
        assert r.status_code == 200, r.text
        cookies = [v.lower() for v in refresh_cookies(r)]
        live = [v for v in cookies if "max-age=0" not in v]
        dead = [v for v in cookies if "max-age=0" in v]
        assert len(live) == 1 and "path=/;" in live[0] + ";"
        assert f"max-age={settings.REFRESH_TOKEN_DAYS * 86400}" in live[0]
        assert settings.REFRESH_TOKEN_DAYS == 30
        assert len(dead) == 1 and "path=/api/v1/auth" in dead[0]


async def test_concurrent_refresh_with_same_token_both_succeed():
    """AC4: proxy và trình duyệt cùng làm mới bằng một refresh token -> cả hai 200; token cũ
    vẫn dùng được (refresh token không trạng thái, chỉ hết hiệu lực khi đổi MK / khóa)."""
    async with new_customer() as c:
        old = c.cookies.get("refresh_token")
        assert old
        async with _client() as a, _client() as b:
            for x in (a, b):
                x.cookies.set("refresh_token", old)
            ra, rb = await asyncio.gather(
                a.post(f"{API}/auth/refresh"), b.post(f"{API}/auth/refresh")
            )
        assert (ra.status_code, rb.status_code) == (200, 200)
        async with _client() as late:
            late.cookies.set("refresh_token", old)
            assert (await late.post(f"{API}/auth/refresh")).status_code == 200

"""B4 / SEC4: quét mọi route khai báo quyền bằng ``require(perm)``.

Chưa đăng nhập -> 401; vai không có quyền -> 403 (kiểm quyền chạy trước kiểm body).
"""

import re

import pytest
from fastapi.routing import APIRoute

from app.core.permissions import DEFAULT_ROLE_PERMS, Perm, require
from app.main import app
from tests.conftest import idem


def _required_perms(route: APIRoute) -> set[Perm]:
    found: set[Perm] = set()

    def walk(dependant) -> None:
        for dep in dependant.dependencies:
            if isinstance(dep.call, require):
                found.add(dep.call.perm)
            walk(dep)

    walk(route.dependant)
    return found


def _all_routes(routes, prefix: str = "") -> list[tuple[str, APIRoute]]:
    """(đường dẫn đầy đủ, route) – gồm cả router con được ``include_router``."""
    result = []
    for r in routes:
        if isinstance(r, APIRoute):
            result.append((prefix + r.path, r))
        elif hasattr(r, "original_router"):
            result += _all_routes(r.original_router.routes, prefix + r.include_context.prefix)
    return result


ROUTES = _all_routes(app.routes)
GUARDED = [
    (path, method, perms)
    for path, route in ROUTES
    for method in sorted(route.methods)
    if (perms := _required_perms(route))
]


async def _call(client, path: str, method: str):
    url = re.sub(r"\{[^}]+\}", "1", path)
    return await client.request(method, url, json={}, headers=idem())


# Route công khai có chủ đích (không cần đăng nhập)
PUBLIC_ROUTES = {"/api/v1/booking/prices/public"}


def test_every_booking_route_declares_a_permission():
    prefixes = ("/api/v1/booking/", "/api/v1/front-desk/", "/api/v1/members/")
    booking = [(p, r) for p, r in ROUTES if p.startswith(prefixes) and p not in PUBLIC_ROUTES]
    assert len(booking) >= 20
    missing = [p for p, r in booking if not _required_perms(r)]
    assert missing == []


def test_quote_is_admin_and_staff_only():
    assert Perm.BOOKING_QUOTE in DEFAULT_ROLE_PERMS["staff"]
    assert Perm.BOOKING_QUOTE not in DEFAULT_ROLE_PERMS["member"]
    # NV mặc định có Sân & bảng giá, Tạo / xóa sự kiện, Danh mục vợt (người dùng chốt 2026-11-05)
    for perm in (Perm.BOOKING_CONFIG_MANAGE, Perm.BOOKING_SESSION_MANAGE, Perm.RACKET_MANAGE):
        assert perm in DEFAULT_ROLE_PERMS["staff"]
    # NV vẫn KHÔNG có các quyền này
    for perm in (
        Perm.MEMBER_STATUS,
        Perm.PAYMENTS_SETTINGS,
        Perm.STAFF_MANAGE,
        Perm.REPORTS_VIEW,
        Perm.AUDIT_LOG_VIEW,
        Perm.ROLES_MANAGE,
        Perm.SETTINGS_MENU,
    ):
        assert perm not in DEFAULT_ROLE_PERMS["staff"], perm


@pytest.mark.parametrize(
    ("path", "method", "perms"), GUARDED, ids=[f"{m} {p}" for p, m, _ in GUARDED]
)
async def test_permission_matrix(path, method, perms, anon, customer, staff, admin):
    r = await _call(anon, path, method)
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "E-AUTH-1"

    for role, client in (("member", customer), ("staff", staff), ("admin", admin)):
        allowed = perms <= DEFAULT_ROLE_PERMS[role]
        r = await _call(client, path, method)
        if allowed:
            assert r.status_code not in (401, 403), (role, r.text)
        else:
            assert r.status_code == 403, (role, r.text)
            assert r.json()["detail"]["code"] == "E-AUTH-2"

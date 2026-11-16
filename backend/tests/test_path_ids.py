"""T-070: id số trong đường dẫn ngoài khoảng cột (quá lớn, 0, âm) -> 404 như bản ghi không tồn tại,
không 500 (asyncpg tràn số) và không 422 (không lộ khác biệt – T-054). Quét **mọi** route có id số
trong path: route mới thêm mà quên ``app.core.params.path_id`` thì đỏ ở đây.
"""

import re

import pytest
from fastapi.routing import APIRoute

from app.core.params import BIGINT_MAX
from app.main import app
from tests import conftest
from tests import test_play_rooms as base
from tests.conftest import idem

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)
OUT_OF_RANGE = (str(BIGINT_MAX + 1), "99999999999999999999", "0", "-1")


def _routes(routes, prefix=""):
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append((prefix + r.path, r))
        elif hasattr(r, "original_router"):
            out += _routes(r.original_router.routes, prefix + r.include_context.prefix)
    return out


def _int_path_params(route: APIRoute) -> set[str]:
    names: set[str] = set()

    def walk(dependant) -> None:
        for p in dependant.path_params:
            if p.field_info.annotation is int:
                names.add(p.alias or p.name)
        for sub in dependant.dependencies:
            walk(sub)

    walk(route.dependant)
    return names


ID_ROUTES = [
    pytest.param(method, path, names, id=f"{method} {path}")
    for path, route in _routes(app.routes)
    if (names := _int_path_params(route))
    for method in sorted(route.methods - {"HEAD"})
]


def test_routes_with_numeric_ids_are_found():
    assert len(ID_ROUTES) >= 40  # phòng chơi, kỷ lục, nhân viên, Lễ/Tết, vợt, thông báo…


@pytest.mark.parametrize(("method", "path", "names"), ID_ROUTES)
async def test_out_of_range_id_is_404(method, path, names, admin, people):
    client = (await people("Quét Id")).client if "/member-area/" in path else admin
    for value in OUT_OF_RANGE:
        url = path
        for name in re.findall(r"\{(\w+)\}", path):
            url = url.replace("{" + name + "}", value if name in names else "x")
        conftest._rate_limit_backend.clear()  # nhiều lần gọi liên tiếp: không vướng 429
        r = await client.request(method, url, json={}, headers=idem())
        assert r.status_code == 404, (method, url, r.status_code, r.text[:200])

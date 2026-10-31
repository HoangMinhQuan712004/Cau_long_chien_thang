# ruff: noqa: E501
"""Helper dùng chung cho test QA T-017 (không phải test): hội viên có tài khoản, tạo phòng bằng đường thật, gọi API phòng."""

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, text

from app.core.db import SessionLocal, engine
from app.modules.auth.models import User
from app.modules.booking_engine import api as engine_api
from app.modules.members.models import Customer
from tests.conftest import API, idem, new_registered, unique_phone
from tests.helpers_booking import book, member, new_court, safe_hour

MA = f"{API}/member-area"
ROOMS = f"{MA}/rooms"
NOTI = f"{MA}/notifications"
M = f"{API}/members"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def err(r) -> dict:
    return r.json()["detail"]


@dataclass
class Hv:
    client: AsyncClient
    code: str
    phone: str
    name: str


@pytest.fixture
async def people():
    """``await people("Tên")`` -> hội viên có tài khoản liên kết (đăng ký 2 bước T-021), đã đăng nhập. Dọn khi xong."""
    phones: list[str] = []
    async with AsyncExitStack() as stack:

        async def make(name: str = "Hội Viên") -> Hv:
            phone = unique_phone()
            phones.append(phone)
            client = await stack.enter_async_context(new_registered(phone, name))
            me = (await client.get(f"{MA}/me")).json()
            return Hv(client, me["member_code"], phone, name)

        yield make
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(phones)))
        await s.execute(delete(User).where(User.phone.in_(phones)))
        await s.commit()


async def publish() -> int:
    n = 0
    for _ in range(30):
        k = await engine_api.publish_outbox(SessionLocal)
        n += k
        if k == 0:
            break
    return n


async def tick() -> tuple[int, int]:
    from app.workers.worker import play_rooms_tick

    return await play_rooms_tick({})


async def find_room(viewer: AsyncClient, court_name: str) -> dict | None:
    r = await viewer.get(ROOMS, params={"scope": "all"})
    assert r.status_code == 200, r.text
    return next((i for i in r.json()["items"] if i["resource_name"] == court_name), None)


async def make_room(
    admin,
    viewer: AsyncClient,
    host_code: str | None,
    *,
    offset: int = 0,
    customer: dict | None = None,
    via="outbox",
):
    """Đặt quầy cho Host rồi tạo phòng qua outbox (hoặc job `tick`); trả {court, code, room (thẻ) | None}."""
    court = await new_court(admin)
    hour = await safe_hour() + offset
    if hour >= 23:
        pytest.skip("không đủ giờ trong ngày để đặt quầy")
    r = await book(admin, court["code"], hour, hour + 1, customer or member(host_code))
    assert r.status_code == 201, r.text
    body = r.json()
    code = body["code"] if "code" in body else body["bookings"][0]["code"]
    await publish() if via == "outbox" else await tick()
    return {
        "court": court,
        "code": code,
        "room": await find_room(viewer, court["name"]),
        "hour": hour,
    }


async def detail(c: AsyncClient, rid: int) -> dict:
    r = await c.get(f"{ROOMS}/{rid}")
    assert r.status_code == 200, r.text
    return r.json()


async def act(
    c: AsyncClient, rid: int, path: str, body: dict | None = None, *, method="post", headers=None
):
    return await getattr(c, method)(
        f"{ROOMS}/{rid}{path}",
        **({"json": body or {}} if method != "delete" else {}),
        headers=headers or idem(),
    )


async def with_v(c, rid, path, extra: dict | None = None):
    v = (await detail(c, rid))["version"]
    return await act(c, rid, path, {"version": v, **(extra or {})})


async def fill(room_id: int, host: Hv, others: list[Hv]) -> None:
    """Đưa các hội viên vào phòng bằng đường thật: xin vào + Host duyệt."""
    for o in others:
        r = await with_v(o.client, room_id, "/join-requests")
        assert r.status_code == 200, r.text
        req = (await detail(host.client, room_id))["join_requests"][0]
        r = await with_v(host.client, room_id, f"/join-requests/{req['id']}/approve")
        assert r.status_code == 200, r.text


def digits_leak(payload, *phones: str) -> list[str]:
    s = json.dumps(payload, ensure_ascii=False)
    return [p for p in phones if p in s or p[1:] in s]

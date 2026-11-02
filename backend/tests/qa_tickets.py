# ruff: noqa: E501
"""Helper dùng chung cho test QA T-023 (không phải test): sự kiện, mua vé online, đọc vé."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.core.db import engine
from tests.conftest import API, idem
from tests.helpers_booking import BK, new_court, random_phone, safe_hour, today
from tests.helpers_web import WEB, phone_token, tomorrow

FD = f"{API}/front-desk"
LOOKUP = f"{WEB}/lookup"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


def code_of(r) -> str:
    return r.json()["detail"]["code"]


async def mk_event(
    admin, *, day: date | None = None, hours=(9, 11), capacity=8, price=50_000, name=None
) -> dict:
    court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": (day or tomorrow()).isoformat(),
            "start_hour": hours[0],
            "end_hour": hours[1],
            "name": name or f"QA sự kiện {uuid.uuid4().hex[:5]}",
            "capacity": capacity,
            "ticket_price": price,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return {**r.json(), "court": court}


async def today_event(admin, **kw) -> dict:
    """Sự kiện hôm nay ở giờ kế tiếp (chưa bắt đầu)."""
    h = await safe_hour() + 1
    if h + 2 > 24:
        pytest.skip("không còn khung giờ chưa bắt đầu trong ngày")
    return await mk_event(admin, day=today(), hours=(h, h + 2), **kw)


async def buy(
    client,
    code: str,
    seats: int = 1,
    *,
    phone: str | None = None,
    name="Khách QA Vé",
    token=True,
    **extra,
):
    body = {"event_code": code, "seats": seats, "full_name": name, "as_member": False, **extra}
    if not body["as_member"]:
        body["phone"] = phone = phone or random_phone()
        if token and "phone_token" not in body:
            body["phone_token"] = await phone_token(client, phone)
    return await client.post(f"{WEB}/event-checkouts", json=body, headers=idem())


async def info(client, code: str):
    return await client.get(f"{WEB}/events/{code}")


async def tickets_of(code: str) -> list[dict]:
    return list(
        await q(
            "SELECT code, source::text AS source, payment_status::text AS st, amount FROM booking.ticket WHERE code LIKE :c ORDER BY code",
            c=f"{code}-V%",
        )
    )

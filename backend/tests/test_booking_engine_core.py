"""C3 mã ``BK-YYYYMMDD-NNN``, C4 outbox, exclusion constraint của ``allocation``."""

import asyncio
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from app.core import events
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import api
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.models import Allocation, OutboxEvent, Resource
from app.modules.booking_engine.outbox import add_event
from app.modules.booking_engine.testing import make_allocation

TENANT = settings.TENANT_ID


async def test_codes_sequential_per_play_date():
    day = date(2040, 10, 20)
    async with SessionLocal() as s:
        a = await next_code(s, TENANT, "BK", day)
        b = await next_code(s, TENANT, "BK", day)
        other_day = await next_code(s, TENANT, "BK", day + timedelta(days=1))
        await s.commit()
    assert (a, b) == ("BK-20401020-001", "BK-20401020-002")
    assert other_day == "BK-20401021-001"


async def test_codes_unique_under_concurrency():
    day = date(2040, 11, 1)

    async def take() -> str:
        async with SessionLocal() as s:
            code = await next_code(s, TENANT, "BK", day)
            await asyncio.sleep(0.01)  # giữ khóa dòng đếm một chút
            await s.commit()
            return code

    codes = await asyncio.gather(*(take() for _ in range(10)))
    assert sorted(codes) == [f"BK-20401101-{i:03d}" for i in range(1, 11)]


async def test_committed_code_never_reused():
    day = date(2040, 12, 5)
    async with SessionLocal() as s:
        first = await next_code(s, TENANT, "BK", day)
        await s.commit()
    async with SessionLocal() as s:
        await next_code(s, TENANT, "BK", day)
        await s.rollback()  # giao dịch tạo đối tượng bị hủy
    async with SessionLocal() as s:
        again = await next_code(s, TENANT, "BK", day)
        await s.commit()
    assert first == "BK-20401205-001"
    assert again != first


async def test_outbox_published_after_commit():
    received: list[dict] = []

    @events.subscribe("test.outbox.ping")
    async def handler(payload: dict) -> None:
        received.append(payload)

    try:
        async with SessionLocal() as s:
            add_event(s, TENANT, "test.outbox.ping", {"n": 1})
            await s.rollback()  # không commit -> không phát
            add_event(s, TENANT, "test.outbox.ping", {"n": 2})
            await s.commit()
        published = await api.publish_outbox(SessionLocal)
        assert published >= 1
        assert received == [{"tenant_id": TENANT, "n": 2}]
        async with SessionLocal() as s:
            pending = await s.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "test.outbox.ping",
                    OutboxEvent.published_at.is_(None),
                )
            )
            assert pending.all() == []
        await api.publish_outbox(SessionLocal)
        assert len(received) == 1  # không phát lại sự kiện đã phát
    finally:
        events._handlers["test.outbox.ping"].remove(handler)


async def test_allocation_exclusion_constraint():
    tz = settings.tz
    day = date(2041, 1, 7)

    def at(h: int) -> datetime:
        return datetime.combine(day, time(h), tz)

    async with SessionLocal() as s:
        await make_allocation(s, "S02", at(18), at(19), owner_code="BK-EX-1")
        # Khung liền kề [19, 20) không trùng
        await make_allocation(s, "S02", at(19), at(20), owner_code="BK-EX-2")
        await s.commit()
    async with SessionLocal() as s:
        with pytest.raises(IntegrityError) as e:
            await make_allocation(s, "S02", at(18), at(20), kind="session", owner_code="BK-EX-3")
        assert getattr(e.value.orig, "sqlstate", None) == "23P01"


async def test_allocation_requires_owner_and_whole_hours():
    async with SessionLocal() as s:
        resource_id = await s.scalar(select(Resource.id).where(Resource.code == "S02"))
    tz = settings.tz
    day = date(2041, 1, 8)
    rng = Range(datetime.combine(day, time(8), tz), datetime.combine(day, time(9), tz), bounds="[)")
    async with SessionLocal() as s:
        s.add(Allocation(tenant_id=TENANT, resource_id=resource_id, time_range=rng, kind="booking"))
        with pytest.raises(IntegrityError) as e:
            await s.flush()
        assert "ck_allocation_one_owner" in str(e.value.orig)
    async with SessionLocal() as s:
        with pytest.raises(IntegrityError) as e:
            await make_allocation(
                s, "S02", datetime.combine(day, time(8, 30), tz), datetime.combine(day, time(9), tz)
            )
        assert "ck_allocation_whole_hours" in str(e.value.orig)

"""Hàm **chỉ dùng cho test**: tạo chỗ chiếm / giữ chỗ trực tiếp, không qua API.

Không import từ code sản phẩm. Ví dụ trong test::

    async with SessionLocal() as s:
        await make_allocation(s, "S01", start, end, owner_code="BK-20261030-001")
        await s.commit()

Từ T-006 mỗi allocation phải có chủ (CHECK ``one_owner``): ``make_allocation`` tạo (hoặc dùng
lại theo ``owner_code``) một booking / sự kiện giả làm chủ. Giữ chỗ online (T-008 mới có API)
tạo bằng ``make_hold``.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    EventSession,
    Hold,
    Resource,
)
from app.modules.booking_engine.tenant import current_tenant_id

TEST_CUSTOMER = {
    "customer_ref": "test",
    "customer_kind": "temp",
    "customer_name": "Khách test",
    "customer_phone": "0900000000",
}


def _aware(*moments: datetime) -> None:
    if any(m.tzinfo is None for m in moments):
        raise ValueError("start/end must be timezone-aware")


async def _resource_id(session: AsyncSession, tid: int, code: str) -> int:
    resource_id = await session.scalar(
        select(Resource.id).where(Resource.tenant_id == tid, Resource.code == code)
    )
    if resource_id is None:
        raise ValueError(f"Unknown resource {code}")
    return resource_id


async def _owner_booking(
    session: AsyncSession, tid: int, code: str, resource_id: int, start: datetime, end: datetime
) -> int:
    existing = await session.scalar(
        select(Booking.id).where(Booking.tenant_id == tid, Booking.code == code)
    )
    if existing is not None:
        return existing
    row = Booking(
        tenant_id=tid,
        code=code,
        source="counter",
        resource_id=resource_id,
        play_date=start.date(),
        start_at=start,
        end_at=end,
        amount=0,
        payment_status="unpaid",
        created_by_type="system",
        created_by_label="Test",
        **TEST_CUSTOMER,
    )
    session.add(row)
    await session.flush()
    return row.id


async def _owner_session(
    session: AsyncSession, tid: int, code: str, start: datetime, end: datetime
) -> int:
    existing = await session.scalar(
        select(EventSession.id).where(EventSession.tenant_id == tid, EventSession.code == code)
    )
    if existing is not None:
        return existing
    row = EventSession(
        tenant_id=tid,
        code=code,
        name="Sự kiện test",
        play_date=start.date(),
        start_at=start,
        end_at=end,
        capacity=10,
        ticket_price=0,
        created_by_type="system",
        created_by_label="Test",
    )
    session.add(row)
    await session.flush()
    return row.id


async def make_allocation(
    session: AsyncSession,
    resource_code: str,
    start: datetime,
    end: datetime,
    *,
    kind: str = "booking",
    owner_code: str | None = None,
    tenant_id: int | None = None,
) -> int:
    """Chèn một chỗ chiếm ``active`` ``[start, end)`` (giờ tròn, có múi giờ). Không commit; trả id.

    ``kind``: ``booking`` (mặc định) hoặc ``session``; chủ được tạo / dùng lại theo ``owner_code``.
    """
    _aware(start, end)
    tid = current_tenant_id() if tenant_id is None else tenant_id
    resource_id = await _resource_id(session, tid, resource_code)
    code = owner_code or f"TEST-{uuid.uuid4().hex[:10].upper()}"
    owner: dict
    if kind == "booking":
        owner = {"booking_id": await _owner_booking(session, tid, code, resource_id, start, end)}
    elif kind == "session":
        owner = {"session_id": await _owner_session(session, tid, code, start, end)}
    else:
        raise ValueError("kind must be 'booking' or 'session' (giữ chỗ: dùng make_hold)")
    row = Allocation(
        tenant_id=tid,
        resource_id=resource_id,
        time_range=Range(start, end, bounds="[)"),
        kind=kind,
        owner_code=code,
        active=True,
        **owner,
    )
    session.add(row)
    await session.flush()
    return row.id


async def release_allocation(session: AsyncSession, allocation_id: int) -> None:
    """Tắt chỗ chiếm (để test dọn dữ liệu của mình). Không commit."""
    row = await session.get(Allocation, allocation_id)
    if row is not None:
        row.active = False
        await session.flush()


async def make_hold(
    session: AsyncSession,
    *,
    resource_code: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    session_code: str | None = None,
    seats: int = 1,
    minutes: float = 7,
    tenant_id: int | None = None,
) -> uuid.UUID:
    """Giữ chỗ online còn ``minutes`` phút (âm = đã quá hạn, chờ worker). Không commit.

    - Khung sân: ``resource_code`` + ``start``/``end`` -> hold ``court`` + allocation ``hold``.
    - Chỗ trong sự kiện: ``session_code`` + ``seats`` -> hold ``seat``.
    """
    tid = current_tenant_id() if tenant_id is None else tenant_id
    expires_at = datetime.now().astimezone() + timedelta(minutes=minutes)
    if session_code is not None:
        sid = await session.scalar(
            select(EventSession.id).where(
                EventSession.tenant_id == tid, EventSession.code == session_code
            )
        )
        if sid is None:
            raise ValueError(f"Unknown session {session_code}")
        hold = Hold(tenant_id=tid, kind="seat", session_id=sid, seats=seats, expires_at=expires_at)
        session.add(hold)
        await session.flush()
        return hold.id
    if resource_code is None or start is None or end is None:
        raise ValueError("court hold needs resource_code, start, end")
    _aware(start, end)
    resource_id = await _resource_id(session, tid, resource_code)
    hold = Hold(tenant_id=tid, kind="court", seats=1, expires_at=expires_at)
    session.add(hold)
    await session.flush()
    session.add(
        Allocation(
            tenant_id=tid,
            resource_id=resource_id,
            time_range=Range(start, end, bounds="[)"),
            kind="hold",
            hold_id=hold.id,
            active=True,
        )
    )
    await session.flush()
    return hold.id

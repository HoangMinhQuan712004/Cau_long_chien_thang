"""Hàm **chỉ dùng cho test** (T-005 Q5): tạo chỗ chiếm khi chưa có API đặt (T-006).

Không import từ code sản phẩm. Ví dụ trong test::

    async with SessionLocal() as s:
        await make_allocation(s, "S01", start, end, owner_code="BK-20261030-001")
        await s.commit()
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import Allocation, Resource
from app.modules.booking_engine.tenant import current_tenant_id


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
    """Chèn một chỗ chiếm ``active`` ``[start, end)`` (giờ có múi giờ). Không commit; trả id."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")
    tid = current_tenant_id() if tenant_id is None else tenant_id
    resource_id = await session.scalar(
        select(Resource.id).where(Resource.tenant_id == tid, Resource.code == resource_code)
    )
    if resource_id is None:
        raise ValueError(f"Unknown resource {resource_code}")
    row = Allocation(
        tenant_id=tid,
        resource_id=resource_id,
        time_range=Range(start, end, bounds="[)"),
        kind=kind,
        owner_code=owner_code,
        active=True,
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

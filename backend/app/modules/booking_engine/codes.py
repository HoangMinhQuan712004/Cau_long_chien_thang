"""Cấp mã ``{prefix}-YYYYMMDD-NNN`` (T-005 C3, SRS BR-012).

YYYYMMDD = **ngày chơi**; số tuần tự theo (tenant, tiền tố, ngày), dùng chung cho booking
và sự kiện.
Cấp bằng ``INSERT … ON CONFLICT DO UPDATE … RETURNING`` trong transaction tạo đối tượng: dòng đếm bị
khóa tới khi transaction kết thúc nên hai giao dịch đồng thời không bao giờ nhận cùng số; mã đã cấp
cho đối tượng đã lưu không bao giờ được cấp lại (bộ đếm chỉ tăng).
"""

from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import CodeSequence


async def next_code(session: AsyncSession, tenant_id: int, prefix: str, day: date) -> str:
    value = await _next_value(session, tenant_id, prefix, day)
    return f"{prefix}-{day:%Y%m%d}-{value:03d}"


SERIES_PREFIX = "GT"


async def next_series_code(session: AsyncSession, tenant_id: int, month: date) -> str:
    """Gói đặt theo tháng: ``GT-YYMM-NNN`` (đếm theo tháng của gói, cùng cơ chế khóa dòng đếm)."""
    value = await _next_value(session, tenant_id, SERIES_PREFIX, month.replace(day=1))
    return f"{SERIES_PREFIX}-{month:%y%m}-{value:03d}"


async def _next_value(session: AsyncSession, tenant_id: int, prefix: str, day: date) -> int:
    stmt = (
        insert(CodeSequence)
        .values(tenant_id=tenant_id, prefix=prefix, day=day, last_value=1)
        .on_conflict_do_update(
            index_elements=[CodeSequence.tenant_id, CodeSequence.prefix, CodeSequence.day],
            set_={"last_value": CodeSequence.last_value + 1},
        )
        .returning(CodeSequence.last_value)
    )
    return (await session.execute(stmt)).scalar_one()

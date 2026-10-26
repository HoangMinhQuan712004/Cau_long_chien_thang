"""Giữ chỗ online (BR-002, 7 phút): hết hạn -> ``expired`` + trả khung (tắt allocation)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Một câu lệnh: đổi trạng thái giữ chỗ quá hạn và tắt allocation của chúng
_EXPIRE_SQL = text(
    """
    WITH expired AS (
        UPDATE booking.hold SET status = 'expired'
        WHERE status = 'active' AND expires_at <= now()
        RETURNING id
    ), freed AS (
        UPDATE booking.allocation a SET active = false
        FROM expired e
        WHERE a.hold_id = e.id AND a.active
        RETURNING a.id
    )
    SELECT (SELECT count(*) FROM expired) AS holds, (SELECT count(*) FROM freed) AS slots
    """
)


async def expire_holds(session: AsyncSession) -> int:
    """Hết hạn giữ chỗ quá giờ (không commit). Trả số giữ chỗ vừa hết hạn.

    Worker gọi mỗi 30 giây; thao tác đặt cũng gọi trước khi chiếm khung để giữ chỗ vừa hết
    hạn không chặn lượt đặt mới.
    """
    row = (await session.execute(_EXPIRE_SQL)).one()
    return int(row.holds)

"""Mặt tiền của module Kỷ lục – module khác (member_area) chỉ gọi các hàm ở đây."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.records import service


async def record_kmh(session: AsyncSession, customer_id: int) -> int | None:
    """Kỷ lục tốc độ cú đập mọi thời gian của hội viên (km/h); None khi chưa có số đo."""
    return await service.record_kmh(session, customer_id)

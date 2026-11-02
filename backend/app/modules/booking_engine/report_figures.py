"""Gom số liệu báo cáo (doanh thu, lượt, theo ngày, theo sân, công suất) cho một kỳ + kỳ trước.

Không mở / đóng transaction: người gọi đặt mức cô lập (REPEATABLE READ) để thẻ, biểu đồ ngày
và biểu đồ sân đọc cùng một ảnh dữ liệu (NFR-002).
"""

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine import report_occupancy, report_revenue
from app.modules.booking_engine.common import context
from app.modules.booking_engine.report_dto import ReportFigures


async def figures(
    session: AsyncSession,
    tenant_id: int,
    period: tuple[date, date],
    previous: tuple[date, date],
    previous_until: datetime | None,
) -> ReportFigures:
    ctx = await context(session, tenant_id)
    date_from, date_to = period
    courts = await report_revenue.by_court(session, tenant_id, date_from, date_to)
    return ReportFigures(
        current=await report_revenue.totals(session, tenant_id, date_from, date_to),
        previous=await report_revenue.totals(session, tenant_id, *previous, previous_until),
        daily=await report_revenue.daily(session, tenant_id, date_from, date_to),
        courts=courts,
        active_courts=sum(c.is_active for c in courts),
        occupancy=await report_occupancy.occupancy(session, ctx, tenant_id, date_from, date_to),
    )

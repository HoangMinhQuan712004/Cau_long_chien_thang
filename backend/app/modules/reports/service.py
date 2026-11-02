"""Màn Báo cáo & phân tích: 3 chỉ số, doanh thu theo ngày / sân, heatmap (FR-001 … FR-007)."""

from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine import api as booking
from app.modules.members import api as members
from app.modules.reports import heatmap, periods
from app.modules.reports.schemas import (
    BookingsOut,
    CourtOut,
    DailyOut,
    MetricOut,
    PeriodOut,
    PreviousOut,
    ReportOverviewOut,
)


async def overview(
    session: AsyncSession,
    date_from: date | None,
    date_to: date | None,
    *,
    now: datetime | None = None,
    tenant_id: int | None = None,
) -> ReportOverviewOut:
    now = now or datetime.now(settings.tz)
    p = periods.resolve(date_from, date_to, now)
    # Mọi số đọc từ một ảnh dữ liệu (NFR-002): kết thúc transaction của bước kiểm đăng nhập
    # (chỉ đọc) rồi mở transaction REPEATABLE READ cho cả màn
    await session.commit()
    await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    figs = await booking.report(
        session,
        (p.date_from, p.date_to),
        (p.prev_from, p.prev_to),
        p.prev_until,
        tenant_id=tenant_id,
    )
    members_now = await members.count_new_members(session, *periods.current_window(p, now))
    members_before = await members.count_new_members(session, *periods.previous_window(p, now))
    await session.rollback()  # chỉ đọc
    return ReportOverviewOut(
        period=PeriodOut(date_from=p.date_from, date_to=p.date_to, days=p.days),
        previous=PreviousOut(date_from=p.prev_from, date_to=p.prev_to, until=p.prev_until),
        computed_at=datetime.now(settings.tz),
        active_courts=figs.active_courts,
        revenue=MetricOut(current=figs.current.revenue, previous=figs.previous.revenue),
        bookings=BookingsOut(
            current=figs.current.bookings,
            previous=figs.previous.bookings,
            tickets=figs.current.tickets,
        ),
        new_members=MetricOut(current=members_now, previous=members_before),
        daily=[DailyOut(date=d.date, revenue=d.revenue) for d in figs.daily],
        courts=[CourtOut(**c.model_dump()) for c in figs.courts],
        heatmap=heatmap.build(figs.occupancy, now.date()),
    )

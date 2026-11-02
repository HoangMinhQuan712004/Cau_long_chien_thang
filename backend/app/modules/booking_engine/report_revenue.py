"""Doanh thu + lượt đặt theo ngày chơi (SRS Báo cáo & phân tích BR-006, BR-007, BR-014, BR-015).

Chỉ tính booking / vé ``paid``; tiền lấy từ chính dòng đã thu (``amount``), không từ bảng giá.
Vé ghi vào ngày của sự kiện; sự kiện nhiều sân chia tiền vé theo giờ dùng từng sân.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.models import Allocation, Booking, EventSession, Resource, Ticket
from app.modules.booking_engine.report_dto import CourtRevenue, DailyRevenue, RevenueTotals


def _bookings(tenant_id: int, date_from: date, date_to: date, until: datetime | None):
    conds = [
        Booking.tenant_id == tenant_id,
        Booking.payment_status == "paid",
        Booking.play_date.between(date_from, date_to),
    ]
    # So cùng mốc (BR-005): ngày chơi tính theo giờ bắt đầu chơi
    if until is not None:
        conds.append(Booking.start_at < until)
    return conds


def _tickets(tenant_id: int, date_from: date, date_to: date, until: datetime | None):
    conds = [
        Ticket.tenant_id == tenant_id,
        Ticket.payment_status == "paid",
        EventSession.play_date.between(date_from, date_to),
    ]
    if until is not None:
        conds.append(EventSession.start_at < until)
    return conds


async def totals(
    session: AsyncSession,
    tenant_id: int,
    date_from: date,
    date_to: date,
    until: datetime | None = None,
) -> RevenueTotals:
    """Doanh thu, số lượt (1 booking = 1 lượt, 1 vé = 1 lượt), số vé của khoảng ngày chơi."""
    b_sum, b_count = (
        await session.execute(
            select(func.coalesce(func.sum(Booking.amount), 0), func.count(Booking.id)).where(
                *_bookings(tenant_id, date_from, date_to, until)
            )
        )
    ).one()
    t_sum, t_count = (
        await session.execute(
            select(func.coalesce(func.sum(Ticket.amount), 0), func.count(Ticket.id))
            .join(EventSession, EventSession.id == Ticket.session_id)
            .where(*_tickets(tenant_id, date_from, date_to, until))
        )
    ).one()
    return RevenueTotals(
        revenue=int(b_sum) + int(t_sum), bookings=b_count + t_count, tickets=t_count
    )


async def daily(
    session: AsyncSession, tenant_id: int, date_from: date, date_to: date
) -> list[DailyRevenue]:
    """Mỗi ngày trong kỳ một điểm, ngày không có doanh thu = 0."""
    by_day: dict[date, int] = {}
    booking_rows = await session.execute(
        select(Booking.play_date, func.sum(Booking.amount))
        .where(*_bookings(tenant_id, date_from, date_to, None))
        .group_by(Booking.play_date)
    )
    ticket_rows = await session.execute(
        select(EventSession.play_date, func.sum(Ticket.amount))
        .join(EventSession, EventSession.id == Ticket.session_id)
        .where(*_tickets(tenant_id, date_from, date_to, None))
        .group_by(EventSession.play_date)
    )
    for day, amount in [*booking_rows, *ticket_rows]:
        by_day[day] = by_day.get(day, 0) + int(amount)
    days = (date_to - date_from).days + 1
    return [
        DailyRevenue(date=d, revenue=by_day.get(d, 0))
        for d in (date_from + timedelta(days=i) for i in range(days))
    ]


def code_key(code: str) -> tuple[int, str]:
    """Thứ tự mã sân: S02 < S10 < S100 (độ dài trước, rồi chữ)."""
    return len(code), code


def split_by_hours(total: int, minutes: dict[str, int]) -> dict[str, int]:
    """Chia ``total`` theo phút dùng từng sân (mã -> phút); phần lẻ đồng cho sân mã nhỏ nhất."""
    weight = sum(minutes.values())
    if total == 0 or weight == 0:
        return {}
    shares = {code: total * m // weight for code, m in minutes.items()}
    smallest = min(minutes, key=code_key)
    shares[smallest] += total - sum(shares.values())
    return shares


async def _ticket_shares(
    session: AsyncSession, tenant_id: int, date_from: date, date_to: date
) -> dict[str, int]:
    """Tiền vé đã thu của từng sự kiện, chia cho các sân của sự kiện (OQ-6)."""
    rows = await session.execute(
        select(Ticket.session_id, func.sum(Ticket.amount))
        .join(EventSession, EventSession.id == Ticket.session_id)
        .where(*_tickets(tenant_id, date_from, date_to, None))
        .group_by(Ticket.session_id)
    )
    per_session: dict[int, int] = {session_id: int(amount) for session_id, amount in rows}
    if not per_session:
        return {}
    seconds = func.extract(
        "epoch", func.upper(Allocation.time_range) - func.lower(Allocation.time_range)
    )
    used = await session.execute(
        select(Allocation.session_id, Resource.code, func.sum(seconds))
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.kind == "session",
            Allocation.active.is_(True),
            Allocation.session_id.in_(per_session),
        )
        .group_by(Allocation.session_id, Resource.code)
    )
    minutes: dict[int, dict[str, int]] = {}
    for session_id, code, secs in used:
        minutes.setdefault(session_id, {})[code] = int(secs) // 60
    shares: dict[str, int] = {}
    for session_id, amount in per_session.items():
        for code, part in split_by_hours(amount, minutes.get(session_id, {})).items():
            shares[code] = shares.get(code, 0) + part
    return shares


async def by_court(
    session: AsyncSession, tenant_id: int, date_from: date, date_to: date
) -> list[CourtRevenue]:
    """Sân đang hoạt động + sân ngừng nhưng có doanh thu trong kỳ (OQ-7), sắp theo mã."""
    revenue = await _ticket_shares(session, tenant_id, date_from, date_to)
    booking_rows = await session.execute(
        select(Resource.code, func.sum(Booking.amount))
        .join(Resource, Resource.id == Booking.resource_id)
        .where(*_bookings(tenant_id, date_from, date_to, None))
        .group_by(Resource.code)
    )
    for code, amount in booking_rows:
        revenue[code] = revenue.get(code, 0) + int(amount)
    courts = await session.execute(
        select(Resource.code, Resource.name, Resource.is_active).where(
            Resource.tenant_id == tenant_id
        )
    )
    result = [
        CourtRevenue(code=code, name=name, revenue=revenue.get(code, 0), is_active=is_active)
        for code, name, is_active in courts
        if is_active or revenue.get(code, 0) > 0
    ]
    return sorted(result, key=lambda c: code_key(c.code))

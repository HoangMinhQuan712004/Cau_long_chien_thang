"""Doanh thu theo **ngày tiền về** + lượt đặt theo ngày chơi (SRS Báo cáo & phân tích BR-006,
BR-007, BR-014, BR-015; ADR-014).

- Tiền = Σ ``in`` − Σ ``refund`` của sổ tiền vào theo ngày ``occurred_at`` (giờ của sân). Hoàn trừ
  vào ngày hủy, ngày đã qua không đổi; một ngày có thể âm. Theo sân: mục booking -> sân của khối;
  mục vé chia theo giờ dùng từng sân của sự kiện; mục hoàn trừ vào sân của mục gốc.
- Lượt đặt (1 booking = 1 lượt, 1 vé = 1 lượt) vẫn theo ngày chơi, chỉ tính khoản ``paid``.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    EventSession,
    PaymentEntry,
    PaymentEntryItem,
    Resource,
    Ticket,
)
from app.modules.booking_engine.report_dto import CourtRevenue, DailyRevenue, RevenueTotals

# Thu cộng, hoàn trừ
_SIGNED = case((PaymentEntry.kind == "refund", -PaymentEntry.amount), else_=PaymentEntry.amount)
_SIGNED_ITEM = case(
    (PaymentEntry.kind == "refund", -PaymentEntryItem.amount), else_=PaymentEntryItem.amount
)


async def _tz(session: AsyncSession, tenant_id: int) -> ZoneInfo:
    return (await context(session, tenant_id)).tz


def _received(tenant_id: int, tz: ZoneInfo, date_from: date, date_to: date, until: datetime | None):
    """Dòng sổ có ngày tiền về trong khoảng; ``until``: so cùng mốc (BR-005) – tiền về trước mốc."""
    conds = [
        PaymentEntry.tenant_id == tenant_id,
        PaymentEntry.occurred_at >= datetime.combine(date_from, time(), tz),
        PaymentEntry.occurred_at < datetime.combine(date_to + timedelta(days=1), time(), tz),
    ]
    if until is not None:
        conds.append(PaymentEntry.occurred_at < until)
    return conds


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
    """Doanh thu (ngày tiền về), số lượt + số vé (ngày chơi) của khoảng ngày."""
    tz = await _tz(session, tenant_id)
    revenue = await session.scalar(
        select(func.coalesce(func.sum(_SIGNED), 0)).where(
            *_received(tenant_id, tz, date_from, date_to, until)
        )
    )
    b_count = await session.scalar(
        select(func.count(Booking.id)).where(*_bookings(tenant_id, date_from, date_to, until))
    )
    t_count = await session.scalar(
        select(func.count(Ticket.id))
        .join(EventSession, EventSession.id == Ticket.session_id)
        .where(*_tickets(tenant_id, date_from, date_to, until))
    )
    return RevenueTotals(revenue=int(revenue or 0), bookings=b_count + t_count, tickets=t_count)


async def daily(
    session: AsyncSession, tenant_id: int, date_from: date, date_to: date
) -> list[DailyRevenue]:
    """Mỗi ngày trong kỳ một điểm (ngày tiền về); ngày không có tiền = 0; có thể âm."""
    tz = await _tz(session, tenant_id)
    day = cast(func.timezone(tz.key, PaymentEntry.occurred_at), Date)
    by_day: dict[date, int] = {
        d: int(amount)
        for d, amount in await session.execute(
            select(day, func.sum(_SIGNED))
            .where(*_received(tenant_id, tz, date_from, date_to, None))
            .group_by(day)
        )
    }
    days = (date_to - date_from).days + 1
    return [
        DailyRevenue(date=d, revenue=by_day.get(d, 0))
        for d in (date_from + timedelta(days=i) for i in range(days))
    ]


def code_key(code: str) -> tuple[int, str]:
    """Thứ tự mã sân: S02 < S10 < S100 (độ dài trước, rồi chữ)."""
    return len(code), code


def split_by_hours(total: int, minutes: dict[str, int]) -> dict[str, int]:
    """Chia ``total`` theo phút dùng từng sân (mã -> phút); phần lẻ đồng cho sân mã nhỏ nhất.

    ``total`` âm (hoàn nhiều hơn thu) chia như số dương rồi đổi dấu -> tổng các phần vẫn đúng.
    """
    weight = sum(minutes.values())
    if total == 0 or weight == 0:
        return {}
    if total < 0:
        return {code: -part for code, part in split_by_hours(-total, minutes).items()}
    shares = {code: total * m // weight for code, m in minutes.items()}
    smallest = min(minutes, key=code_key)
    shares[smallest] += total - sum(shares.values())
    return shares


async def _ticket_shares(
    session: AsyncSession, tenant_id: int, date_from: date, date_to: date
) -> dict[str, int]:
    """Tiền vé (thu − hoàn, ngày tiền về) của từng sự kiện, chia cho các sân của sự kiện (OQ-6)."""
    tz = await _tz(session, tenant_id)
    rows = await session.execute(
        select(Ticket.session_id, func.sum(_SIGNED_ITEM))
        .select_from(PaymentEntryItem)
        .join(PaymentEntry, PaymentEntry.id == PaymentEntryItem.entry_id)
        .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
        .where(*_received(tenant_id, tz, date_from, date_to, None))
        .group_by(Ticket.session_id)
    )
    per_session: dict[int, int] = {sid: int(amount) for sid, amount in rows if amount}
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
    """Sân đang hoạt động + sân ngừng nhưng có tiền (khác 0) trong kỳ (OQ-7), sắp theo mã."""
    revenue = await _ticket_shares(session, tenant_id, date_from, date_to)
    tz = await _tz(session, tenant_id)
    booking_rows = await session.execute(
        select(Resource.code, func.sum(_SIGNED_ITEM))
        .select_from(PaymentEntryItem)
        .join(PaymentEntry, PaymentEntry.id == PaymentEntryItem.entry_id)
        .join(Booking, Booking.id == PaymentEntryItem.booking_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(*_received(tenant_id, tz, date_from, date_to, None))
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
        if is_active or revenue.get(code, 0) != 0
    ]
    return sorted(result, key=lambda c: code_key(c.code))

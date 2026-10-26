"""Lịch sử giao dịch (T-006 §3 BR-020, FR-010).

Mỗi dòng = 1 booking hoặc 1 vé, lọc theo ngày chơi; 3 thẻ tổng theo đúng bộ lọc.
"""

import re
from datetime import timedelta

from sqlalchemy import String, exists, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import aggregate_order_by, array
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.booking_engine.common import context, masked
from app.modules.booking_engine.dto import (
    TransactionCard,
    TransactionCards,
    TransactionRow,
    TransactionsOut,
    TransactionsQuery,
)
from app.modules.booking_engine.models import Allocation, Booking, EventSession, Resource, Ticket

PAGE_SIZE = 8
MAX_DAYS = 92
DEFAULT_DAYS = 7
TRANSFER_METHODS = ("transfer", "online_transfer")


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filters(item, q: TransactionsQuery, resource_match):
    """Điều kiện chung cho booking / vé (cột trạng thái, phương thức, tìm kiếm)."""
    conds = []
    if q.status:
        conds.append(item.payment_status == q.status)
    if q.method:
        methods = ("cash",) if q.method == "cash" else TRANSFER_METHODS
        conds += [item.payment_status == "paid", item.payment_method.in_(methods)]
    if q.resource:
        conds.append(resource_match)
    text = (q.q or "").strip()
    if text:
        found = [
            item.code.ilike(_like(text.replace(" ", ""))),
            item.customer_name.ilike(_like(text)),
        ]
        digits = re.sub(r"[\s.]", "", text)
        if digits.isdigit():
            found.append(item.customer_phone.like(_like(digits)))
        conds.append(or_(*found))
    return conds


async def list_transactions(
    session: AsyncSession, tenant_id: int, q: TransactionsQuery
) -> TransactionsOut:
    ctx = await context(session, tenant_id)
    date_to = q.date_to or ctx.today
    date_from = q.date_from or date_to - timedelta(days=DEFAULT_DAYS - 1)
    if date_from > date_to:
        raise AppError("E-016", "Từ ngày không được sau Đến ngày.", 422)
    if (date_to - date_from).days + 1 > MAX_DAYS:
        raise AppError("E-020", f"Chỉ xem được tối đa {MAX_DAYS} ngày mỗi lần.", 422)
    resource_code = (q.resource or "").strip().upper()

    bookings = (
        select(
            literal("booking", String).label("kind"),
            Booking.code,
            Booking.play_date,
            Booking.start_at,
            Booking.end_at,
            array([Resource.code]).label("resource_codes"),
            Resource.code.label("sort_resource"),
            Booking.customer_name,
            Booking.customer_phone,
            Booking.amount,
            Booking.payment_status,
            Booking.payment_method,
            Booking.source,
        )
        .join(Resource, Resource.id == Booking.resource_id)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.play_date.between(date_from, date_to),
            *_filters(Booking, q, Resource.code == resource_code),
        )
    )

    session_resource = (
        select(Resource.code)
        .join(Allocation, Allocation.resource_id == Resource.id)
        .where(Allocation.session_id == Ticket.session_id)
        .correlate(Ticket)
    )
    ticket_codes = (
        select(func.array_agg(aggregate_order_by(Resource.code, Resource.sort_order)))
        .join(Allocation, Allocation.resource_id == Resource.id)
        .where(Allocation.session_id == Ticket.session_id)
        .correlate(Ticket)
        .scalar_subquery()
    )
    tickets = (
        select(
            literal("ticket", String).label("kind"),
            Ticket.code,
            EventSession.play_date,
            EventSession.start_at,
            EventSession.end_at,
            func.coalesce(ticket_codes, array([], type_=String)).label("resource_codes"),
            func.coalesce(
                session_resource.with_only_columns(func.min(Resource.code)).scalar_subquery(), ""
            ).label("sort_resource"),
            Ticket.customer_name,
            Ticket.customer_phone,
            Ticket.amount,
            Ticket.payment_status,
            Ticket.payment_method,
            Ticket.source,
        )
        .join(EventSession, EventSession.id == Ticket.session_id)
        .where(
            Ticket.tenant_id == tenant_id,
            EventSession.play_date.between(date_from, date_to),
            *_filters(Ticket, q, exists(session_resource.where(Resource.code == resource_code))),
        )
    )
    u = union_all(bookings, tickets).subquery("tx")

    cards = {s: TransactionCard(amount=0, count=0) for s in ("paid", "unpaid", "uncollectible")}
    for status, amount, count in await session.execute(
        select(u.c.payment_status, func.coalesce(func.sum(u.c.amount), 0), func.count()).group_by(
            u.c.payment_status
        )
    ):
        cards[status] = TransactionCard(amount=int(amount), count=count)
    total = sum(c.count for c in cards.values())

    page = max(1, q.page)
    rows = await session.execute(
        select(u)
        .order_by(u.c.start_at.desc(), u.c.sort_resource, u.c.code)
        .limit(PAGE_SIZE)
        .offset((page - 1) * PAGE_SIZE)
    )
    return TransactionsOut(
        date_from=date_from,
        date_to=date_to,
        rows=[
            TransactionRow(
                kind=r.kind,
                code=r.code,
                play_date=r.play_date,
                start_time=ctx.hhmm(r.play_date, r.start_at),
                end_time=ctx.hhmm(r.play_date, r.end_at),
                resource_codes=list(r.resource_codes or []),
                customer_name=r.customer_name,
                phone_masked=masked(r.customer_phone),
                amount=r.amount,
                payment_status=r.payment_status,
                payment_method=r.payment_method,
                source=r.source,
            )
            for r in rows
        ],
        page=page,
        page_size=PAGE_SIZE,
        total=total,
        cards=TransactionCards(**cards),
    )

"""Lịch sử giao dịch = sổ tiền vào (T-057, ADR-014; trước đây T-006 BR-020, FR-010).

Mỗi dòng = một lần nhận tiền hoặc một lần hoàn, lọc theo ngày ``occurred_at`` (giờ của sân);
4 thẻ (thực thu, tiền mặt, chuyển khoản, hoàn) theo bộ lọc ngày + sân. Chỉ đọc.
"""

import re
from datetime import timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.privacy import mask_phone
from app.modules.booking_engine.booking_service import session_resources
from app.modules.booking_engine.common import context
from app.modules.booking_engine.dto import (
    TransactionCards,
    TransactionEntry,
    TransactionEntryItem,
    TransactionsOut,
    TransactionsQuery,
)
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    EventSession,
    PaymentEntry,
    PaymentEntryItem,
    Resource,
    Ticket,
)

PAGE_SIZE = 8
MAX_DAYS = 92
DEFAULT_DAYS = 7
TRANSFER_METHODS = ("transfer", "online_transfer")


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _on_resource(code: str):
    """Dòng có mục thuộc sân ``code`` (booking: sân của khối; vé: một trong các sân sự kiện)."""
    on_booking = (
        select(PaymentEntryItem.id)
        .join(Booking, Booking.id == PaymentEntryItem.booking_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(PaymentEntryItem.entry_id == PaymentEntry.id, Resource.code == code)
    )
    on_ticket = (
        select(PaymentEntryItem.id)
        .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
        .join(Allocation, Allocation.session_id == Ticket.session_id)
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(PaymentEntryItem.entry_id == PaymentEntry.id, Resource.code == code)
    )
    return or_(exists(on_booking), exists(on_ticket))


def _search(text: str):
    """Mã đơn / mã con / mã vé, tên khách, SĐT (chữ số)."""
    code = _like(text.replace(" ", ""))
    found = [
        PaymentEntry.order_code.ilike(code),
        PaymentEntry.customer_name.ilike(_like(text)),
        exists(
            select(PaymentEntryItem.id)
            .join(Booking, Booking.id == PaymentEntryItem.booking_id)
            .where(PaymentEntryItem.entry_id == PaymentEntry.id, Booking.code.ilike(code))
        ),
        exists(
            select(PaymentEntryItem.id)
            .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
            .where(PaymentEntryItem.entry_id == PaymentEntry.id, Ticket.code.ilike(code))
        ),
    ]
    digits = re.sub(r"[\s.]", "", text)
    if digits.isdigit():
        found.append(PaymentEntry.customer_phone.like(_like(digits)))
    return or_(*found)


async def _items(
    session: AsyncSession, tenant_id: int, entry_ids: list[int]
) -> dict[int, list[TransactionEntryItem]]:
    if not entry_ids:
        return {}
    rows: list[tuple[int, int, TransactionEntryItem]] = []
    for item_id, entry_id, amount, code, day, start, end, name in await session.execute(
        select(
            PaymentEntryItem.id,
            PaymentEntryItem.entry_id,
            PaymentEntryItem.amount,
            Booking.code,
            Booking.play_date,
            Booking.start_at,
            Booking.end_at,
            Resource.name,
        )
        .join(Booking, Booking.id == PaymentEntryItem.booking_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(PaymentEntryItem.entry_id.in_(entry_ids))
    ):
        rows.append(
            (
                entry_id,
                item_id,
                TransactionEntryItem(
                    code=code,
                    kind="booking",
                    resource_name=name,
                    play_date=day,
                    start_at=start,
                    end_at=end,
                    amount=amount,
                ),
            )
        )
    tickets = list(
        await session.execute(
            select(
                PaymentEntryItem.id,
                PaymentEntryItem.entry_id,
                PaymentEntryItem.amount,
                Ticket.code,
                EventSession.id,
                EventSession.play_date,
                EventSession.start_at,
                EventSession.end_at,
            )
            .join(Ticket, Ticket.id == PaymentEntryItem.ticket_id)
            .join(EventSession, EventSession.id == Ticket.session_id)
            .where(PaymentEntryItem.entry_id.in_(entry_ids))
        )
    )
    courts = await session_resources(session, tenant_id, list({t[4] for t in tickets}))
    for item_id, entry_id, amount, code, session_id, day, start, end in tickets:
        rows.append(
            (
                entry_id,
                item_id,
                TransactionEntryItem(
                    code=code,
                    kind="ticket",
                    resource_name=", ".join(r.name for r in courts.get(session_id, [])),
                    play_date=day,
                    start_at=start,
                    end_at=end,
                    amount=amount,
                ),
            )
        )
    by_entry: dict[int, list[TransactionEntryItem]] = {}
    for entry_id, _, item in sorted(rows, key=lambda r: r[1]):
        by_entry.setdefault(entry_id, []).append(item)
    return by_entry


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

    scope = [
        PaymentEntry.tenant_id == tenant_id,
        PaymentEntry.occurred_at >= ctx.at(date_from, 0),
        PaymentEntry.occurred_at < ctx.at(date_to + timedelta(days=1), 0),
    ]
    resource_code = (q.resource or "").strip().upper()
    if resource_code:
        scope.append(_on_resource(resource_code))

    def total_of(*conds):
        return func.coalesce(func.sum(PaymentEntry.amount).filter(and_(*conds)), 0)

    cash, transfer, refund = (
        await session.execute(
            select(
                total_of(PaymentEntry.kind == "in", PaymentEntry.method == "cash"),
                total_of(PaymentEntry.kind == "in", PaymentEntry.method.in_(TRANSFER_METHODS)),
                total_of(PaymentEntry.kind == "refund"),
            ).where(*scope)
        )
    ).one()

    conds = list(scope)
    if q.method:
        methods = ("cash",) if q.method == "cash" else TRANSFER_METHODS
        conds.append(PaymentEntry.method.in_(methods))
    if q.kind:
        conds.append(PaymentEntry.kind == q.kind)
    text = (q.q or "").strip()
    if text:
        conds.append(_search(text))

    total = await session.scalar(select(func.count(PaymentEntry.id)).where(*conds)) or 0
    page = max(1, q.page)
    entries = list(
        await session.scalars(
            select(PaymentEntry)
            .where(*conds)
            .order_by(PaymentEntry.occurred_at.desc(), PaymentEntry.id.desc())
            .limit(PAGE_SIZE)
            .offset((page - 1) * PAGE_SIZE)
        )
    )
    items = await _items(session, tenant_id, [e.id for e in entries])
    return TransactionsOut(
        date_from=date_from,
        date_to=date_to,
        cards=TransactionCards(
            net=int(cash) + int(transfer) - int(refund),
            cash=int(cash),
            transfer=int(transfer),
            refund=int(refund),
        ),
        items=[
            TransactionEntry(
                kind=e.kind,
                method="cash" if e.method == "cash" else "transfer",
                source=e.source,
                amount=e.amount,
                occurred_at=e.occurred_at,
                order_code=e.order_code,
                customer_name=e.customer_name,
                customer_phone_masked=mask_phone(e.customer_phone),
                member_code=e.member_code,
                actor_label=e.actor_label,
                items=items.get(e.id, []),
            )
            for e in entries
        ],
        total=total,
        page=page,
        size=PAGE_SIZE,
    )

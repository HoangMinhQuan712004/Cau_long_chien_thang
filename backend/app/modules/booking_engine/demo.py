"""Dữ liệu mẫu cho link dev (T-034) – **chỉ** ``app.scripts.seed_demo`` gọi (qua ``api``).

Booking mẫu (kể cả ngày đã qua, để có Lịch sử chơi / Lịch sử thanh toán) **vẫn đi qua
exclusion constraint** của ``allocation``: khung đã có người -> thử khung / sân khác, không bao giờ
né. Đặt quầy thường chỉ cho hôm nay nên seed cần hàm riêng này; mọi hàm từ chối khi
``ENV=production``.

Dấu mẫu: khách có SĐT trong dải mẫu (do lớp gọi truyền), sự kiện tên bắt đầu bằng ``[Mẫu]``.
Hàm ở đây **không commit**.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.booking_engine import ledger, session_service
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import EXCLUSION_VIOLATION, context, sqlstate
from app.modules.booking_engine.config_service import price_slots
from app.modules.booking_engine.dto import Actor, CustomerSnapshot, SessionCreate
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    Checkout,
    EventSession,
    Hold,
    PaymentEntry,
    PaymentEntryItem,
    Resource,
    Ticket,
)
from app.modules.booking_engine.orders import child_code, new_order, snapshot_values

DEMO_EVENT_PREFIX = "[Mẫu]"
DEMO_ACTOR = Actor(type="system", id=None, label="Dữ liệu mẫu")
FALLBACK_PRICE = 100_000


def _guard() -> None:
    if settings.is_production:
        raise RuntimeError("Dữ liệu mẫu không được tạo / xóa khi ENV=production.")


@dataclass(frozen=True)
class DemoPayment:
    method: str  # "cash" | "online_transfer"
    paid_at: datetime


async def _resources(session: AsyncSession, tenant_id: int) -> list[Resource]:
    return list(
        await session.scalars(
            select(Resource)
            .where(Resource.tenant_id == tenant_id, Resource.is_active.is_(True))
            .order_by(Resource.sort_order, Resource.code)
        )
    )


async def _price(session: AsyncSession, tenant, r: Resource, day: date, hour: int) -> int:
    try:
        _, items = await price_slots(session, tenant, r, day, hour, hour + 1)
        return sum(i.price for i in items)
    except AppError:  # ngày / giờ không có bảng giá -> giá mẫu cố định (chỉ là số hiển thị)
        return FALLBACK_PRICE


async def seed_booking(
    session: AsyncSession,
    tenant_id: int,
    customer: CustomerSnapshot,
    day: date,
    hours: list[int],
    *,
    channel: str = "counter",
    payment: DemoPayment | None = None,
    min_tier: str | None = None,
    max_tier: str | None = None,
) -> str | None:
    """Một đơn một khối 1 giờ: thử lần lượt ``hours`` × sân đang hoạt động tới khi chiếm được khung.

    Trả mã con của khối, hoặc None khi mọi khung đã có người (exclusion constraint chặn).
    """
    _guard()
    ctx = await context(session, tenant_id)
    for hour in hours:
        for r in await _resources(session, tenant_id):
            start, end = ctx.at(day, hour * 60), ctx.at(day, hour * 60 + 60)
            amount = await _price(session, ctx.tenant, r, day, hour)
            order_code = await next_code(session, tenant_id, ctx.code_prefix, day)
            code = child_code(order_code, 1)
            try:
                async with session.begin_nested():
                    order = new_order(
                        tenant_id,
                        order_code,
                        day,
                        channel,
                        snapshot_values(customer),
                        DEMO_ACTOR.label,
                    )
                    order.min_tier, order.max_tier = min_tier, max_tier
                    session.add(order)
                    await session.flush()
                    booking = Booking(
                        tenant_id=tenant_id,
                        order_id=order.id,
                        seq=1,
                        code=code,
                        source=channel,
                        resource_id=r.id,
                        play_date=day,
                        start_at=start,
                        end_at=end,
                        amount=amount,
                        price_breakdown=[],
                        payment_status="paid" if payment else "unpaid",
                        payment_method=payment.method if payment else None,
                        paid_at=payment.paid_at if payment else None,
                        collected_by_type=DEMO_ACTOR.type if payment else None,
                        collected_by_label=DEMO_ACTOR.label if payment else None,
                        created_by_type=DEMO_ACTOR.type,
                        created_by_label=DEMO_ACTOR.label,
                        version=1,
                        **snapshot_values(customer),
                    )
                    session.add(booking)
                    await session.flush()
                    session.add(
                        Allocation(
                            tenant_id=tenant_id,
                            resource_id=r.id,
                            time_range=Range(start, end, bounds="[)"),
                            kind="booking",
                            booking_id=booking.id,
                            owner_code=code,
                            active=True,
                        )
                    )
                    await session.flush()
                    if payment:
                        await ledger.record_in(
                            session,
                            tenant_id,
                            [booking],
                            method=payment.method,
                            occurred_at=payment.paid_at,
                            actor=DEMO_ACTOR,
                        )
            except IntegrityError as e:
                if sqlstate(e) == EXCLUSION_VIOLATION:
                    continue  # khung đã có người -> thử chỗ khác
                raise
            return code
    return None


async def seed_event(
    session: AsyncSession,
    tenant_id: int,
    name: str,
    day: date,
    hours: list[int],
    capacity: int,
    ticket_price: int,
    buyers: list[CustomerSnapshot],
    paid_at: datetime,
) -> str | None:
    """Sự kiện ``[Mẫu] …`` 2 giờ qua đường tạo sự kiện thật (kiểm giờ bán + exclusion), kèm vé đã
    thanh toán online của ``buyers``. Trả mã sự kiện, hoặc None khi không còn chỗ."""
    _guard()
    for hour in hours:
        for r in await _resources(session, tenant_id):
            try:
                out = await session_service.create_session(
                    session,
                    tenant_id,
                    DEMO_ACTOR,
                    SessionCreate(
                        resource_codes=[r.code],
                        date=day,
                        start_hour=hour,
                        end_hour=hour + 2,
                        name=f"{DEMO_EVENT_PREFIX} {name}",
                        capacity=capacity,
                        ticket_price=ticket_price,
                    ),
                )
            except AppError:  # khung trùng / không bán -> thử chỗ khác
                continue
            ev = await session.scalar(
                select(EventSession).where(
                    EventSession.tenant_id == tenant_id, EventSession.code == out.code
                )
            )
            tickets = []
            for seq, buyer in enumerate(buyers, start=1):
                tickets.append(
                    Ticket(
                        tenant_id=tenant_id,
                        session_id=ev.id,
                        seq=seq,
                        code=f"{ev.code}-V{seq:02d}",
                        source="online",
                        amount=ticket_price,
                        payment_status="paid",
                        payment_method="online_transfer",
                        paid_at=paid_at,
                        collected_by_type=DEMO_ACTOR.type,
                        collected_by_label=DEMO_ACTOR.label,
                        created_by_type=DEMO_ACTOR.type,
                        created_by_label=DEMO_ACTOR.label,
                        version=1,
                        **snapshot_values(buyer),
                    )
                )
            session.add_all(tickets)
            await session.flush()
            # Mỗi người mua một lần trả (như đơn vé online)
            for t in tickets:
                await ledger.record_in(
                    session,
                    tenant_id,
                    [t],
                    method="online_transfer",
                    occurred_at=paid_at,
                    actor=DEMO_ACTOR,
                )
            return ev.code
    return None


async def demo_booking_codes(session: AsyncSession, tenant_id: int, phones: list[str]) -> list[str]:
    """Mã con các khối của khách mẫu (để module phòng chơi xóa phòng tương ứng)."""
    if not phones:
        return []
    return list(
        await session.scalars(
            select(Booking.code).where(
                Booking.tenant_id == tenant_id, Booking.customer_phone.in_(phones)
            )
        )
    )


async def purge_demo(session: AsyncSession, tenant_id: int, phones: list[str]) -> dict[str, int]:
    """Xóa dữ liệu engine của khách mẫu (``phones``) + sự kiện ``[Mẫu]``. Không commit.

    Gồm cả lượt thanh toán / vé / booking người dùng tự tạo bằng tài khoản mẫu trên link dev.
    """
    _guard()
    events = list(
        await session.scalars(
            select(EventSession.id).where(
                EventSession.tenant_id == tenant_id,
                EventSession.name.startswith(DEMO_EVENT_PREFIX),
            )
        )
    )
    bookings = list(
        await session.scalars(
            select(Booking.id).where(
                Booking.tenant_id == tenant_id, Booking.customer_phone.in_(phones)
            )
        )
    )
    checkouts = list(
        await session.scalars(
            select(Checkout.id).where(
                Checkout.tenant_id == tenant_id, Checkout.customer_phone.in_(phones)
            )
        )
    )
    holds = list(
        await session.scalars(
            select(Hold.id).where(or_(Hold.checkout_id.in_(checkouts), Hold.session_id.in_(events)))
        )
    )
    counts: dict[str, int] = {}

    async def run(name: str, stmt) -> None:
        counts[name] = (await session.execute(stmt)).rowcount or 0

    demo_tickets = select(Ticket.id).where(
        Ticket.tenant_id == tenant_id,
        or_(
            Ticket.session_id.in_(events),
            Ticket.customer_phone.in_(phones),
            Ticket.checkout_id.in_(checkouts),
        ),
    )
    # Dòng sổ của khoản mẫu (mục xóa theo, ON DELETE CASCADE) – trước khi xóa booking / vé
    await run(
        "payment_entries",
        delete(PaymentEntry).where(
            PaymentEntry.id.in_(
                select(PaymentEntryItem.entry_id).where(
                    or_(
                        PaymentEntryItem.booking_id.in_(bookings),
                        PaymentEntryItem.ticket_id.in_(demo_tickets),
                    )
                )
            )
        ),
    )

    await run(
        "allocations",
        delete(Allocation).where(
            or_(
                Allocation.booking_id.in_(bookings),
                Allocation.hold_id.in_(holds),
                Allocation.session_id.in_(events),
            )
        ),
    )
    await run(
        "tickets",
        delete(Ticket).where(
            Ticket.tenant_id == tenant_id,
            or_(
                Ticket.session_id.in_(events),
                Ticket.customer_phone.in_(phones),
                Ticket.checkout_id.in_(checkouts),
            ),
        ),
    )
    await run("bookings", delete(Booking).where(Booking.id.in_(bookings)))
    await run(
        "orders",
        delete(BookingOrder).where(
            BookingOrder.tenant_id == tenant_id, BookingOrder.customer_phone.in_(phones)
        ),
    )
    await run("holds", delete(Hold).where(Hold.id.in_(holds)))
    await run("checkouts", delete(Checkout).where(Checkout.id.in_(checkouts)))
    await run("events", delete(EventSession).where(EventSession.id.in_(events)))
    return counts

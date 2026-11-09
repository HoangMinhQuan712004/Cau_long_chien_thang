"""Mua vé sự kiện online bằng QR (T-023): chi tiết sự kiện, giữ ghế, tiền về -> vé, tra cứu vé.

Một lượt mua = một ``checkout`` ``kind='ticket'`` + **một** hold ``seat`` (``seats`` = số vé) mang
mã đơn ``BK-…`` (cấp theo ngày diễn ra, cùng dãy với booking / sự kiện – ADR-010) và tổng tiền
chốt lúc giữ. Ghế không chiếm allocation (sự kiện đã chiếm sân); chống bán vượt bằng khóa dòng
``session`` (``FOR UPDATE``) như đăng ký vé tại quầy – mọi nơi đếm chỗ đều cộng ghế đang giữ, kể
cả trong ân hạn nhận tiền trễ.

Hàm ở đây **không commit** – lớp gọi sở hữu transaction.
"""

import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SYSTEM_ACTOR, audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import ledger, outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import (
    normalize_code,
    session_counts,
    session_resources,
)
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import Ctx, audit_actor, context, token_hash
from app.modules.booking_engine.dto import (
    Actor,
    CheckoutCreated,
    CheckoutEvent,
    CheckoutView,
    CustomerSnapshot,
    EventBuyBlock,
    EventInfo,
    LookupEvent,
    LookupPending,
    LookupResult,
    LookupTicket,
    MyTicket,
    OnlinePaymentIn,
    OnlinePaymentResult,
    UpcomingEvent,
)
from app.modules.booking_engine.holds import expire_holds
from app.modules.booking_engine.models import Checkout, EventSession, Hold, Ticket
from app.modules.booking_engine.orders import snapshot_values

MAX_TICKETS = 10
ONLINE_ACTOR = Actor(type="web", id=None, label="Khách đặt online")
PENDING_PHONE_INDEX = "uq_checkout_pending_phone"


def _event_not_found() -> AppError:
    return AppError("E-NOT-FOUND", "Không tìm thấy sự kiện.", 404)


BUY_ERRORS: dict[EventBuyBlock, tuple[str, str]] = {
    "deleted": ("E-WEB-9", "Sự kiện đã bị hủy."),
    "started": ("E-WEB-9", "Sự kiện đã bắt đầu, không mua vé online được."),
    "free": ("E-WEB-11", "Sự kiện này không bán vé online. Vui lòng đăng ký tại quầy."),
    "full": ("E-WEB-10", "Sự kiện đã hết chỗ."),
}


def _buy_block(ctx: Ctx, ev: EventSession, remaining: int) -> EventBuyBlock | None:
    if ev.status != "active":
        return "deleted"
    if ctx.now >= ev.start_at:
        return "started"
    if ev.ticket_price <= 0:
        return "free"
    if remaining <= 0:
        return "full"
    return None


async def _event_by_code(
    session: AsyncSession, tenant_id: int, code: str, for_update: bool = False
) -> EventSession:
    stmt = select(EventSession).where(
        EventSession.tenant_id == tenant_id, EventSession.code == normalize_code(code)
    )
    if for_update:
        stmt = stmt.with_for_update()
    ev = await session.scalar(stmt)
    if ev is None:
        raise _event_not_found()
    return ev


async def _taken(session: AsyncSession, tenant_id: int, ev: EventSession) -> int:
    tickets_n, _, held = (await session_counts(session, tenant_id, [ev.id]))[ev.id]
    return tickets_n + held


async def _resource_names(session: AsyncSession, tenant_id: int, ev: EventSession) -> list[str]:
    return [r.name for r in (await session_resources(session, tenant_id, [ev.id])).get(ev.id, [])]


# ------------------------------------------------------------------ chi tiết sự kiện (AC5)


async def event_info(
    session: AsyncSession, tenant_id: int, code: str, refs: list[str] | None
) -> EventInfo:
    """Sự kiện công khai: không danh sách người mua. ``refs`` (hội viên) -> thêm ``my_tickets``."""
    ctx = await context(session, tenant_id)
    ev = await _event_by_code(session, tenant_id, code)
    taken = await _taken(session, tenant_id, ev)
    remaining = max(ev.capacity - taken, 0)
    reason = _buy_block(ctx, ev, remaining)
    mine = None
    if refs is not None:
        mine = [
            MyTicket(code=t.code, pay_status=t.payment_status)
            for t in await session.scalars(
                select(Ticket)
                .where(
                    Ticket.tenant_id == tenant_id,
                    Ticket.session_id == ev.id,
                    Ticket.customer_ref.in_(refs),
                    Ticket.payment_status != "cancelled",
                )
                .order_by(Ticket.seq)
            )
        ]
    return EventInfo(
        code=ev.code,
        name=ev.name,
        play_date=ev.play_date,
        start_time=ctx.hhmm(ev.play_date, ev.start_at),
        end_time=ctx.hhmm(ev.play_date, ev.end_at),
        resource_names=await _resource_names(session, tenant_id, ev),
        ticket_price=ev.ticket_price,
        capacity=ev.capacity,
        taken=taken,
        max_seats=0 if reason else min(remaining, MAX_TICKETS),
        can_buy=reason is None,
        reason=reason,
        my_tickets=mine,
    )


# ------------------------------------------------------------------ giữ ghế (AC8, AC9, AC12)


def _pending_exists() -> AppError:
    return AppError(
        "E-WEB-4",
        "Số điện thoại này đang có lượt giữ chỗ chưa thanh toán. "
        "Vui lòng thanh toán hoặc chờ hết hạn.",
        409,
    )


async def create_ticket_checkout(
    session: AsyncSession,
    tenant_id: int,
    event_code: str,
    seats: int,
    customer: CustomerSnapshot,
    hold_minutes: int,
) -> CheckoutCreated:
    """Giữ ``seats`` ghế ``hold_minutes`` phút, cấp mã đơn, chốt tiền = ``seats`` × giá vé."""
    if not 1 <= seats <= MAX_TICKETS:
        raise AppError("E-WEB-1", f"Số vé phải từ 1 đến {MAX_TICKETS}.", 422)
    ctx = await context(session, tenant_id)
    await expire_holds(session)
    # Khóa dòng sự kiện: đếm chỗ (vé + ghế đang giữ) không đua với lượt mua khác / quầy
    ev = await _event_by_code(session, tenant_id, event_code, for_update=True)
    remaining = ev.capacity - await _taken(session, tenant_id, ev)
    reason = _buy_block(ctx, ev, remaining)
    if reason is not None:
        code, message = BUY_ERRORS[reason]
        raise AppError(code, message, 409, remaining=max(remaining, 0))
    if seats > remaining:
        raise AppError("E-WEB-10", f"Sự kiện chỉ còn {remaining} chỗ.", 409, remaining=remaining)
    pending = await session.scalar(
        select(Checkout.id).where(
            Checkout.tenant_id == tenant_id,
            Checkout.customer_phone == customer.phone,
            Checkout.status == "pending",
        )
    )
    if pending is not None:
        raise _pending_exists()

    order_code = await next_code(session, tenant_id, ctx.code_prefix, ev.play_date)
    token = secrets.token_urlsafe(32)
    expires_at = ctx.now + timedelta(minutes=hold_minutes)
    total = seats * ev.ticket_price
    checkout = Checkout(
        tenant_id=tenant_id,
        kind="ticket",
        token_hash=token_hash(token),
        order_code=order_code,
        pay_ref=order_code.replace("-", ""),
        play_date=ev.play_date,
        amount=total,
        paid_amount=0,
        status="pending",
        expires_at=expires_at,
        **snapshot_values(customer),
    )
    try:
        async with session.begin_nested():
            session.add(checkout)
            await session.flush()
            session.add(
                Hold(
                    tenant_id=tenant_id,
                    kind="seat",
                    session_id=ev.id,
                    checkout_id=checkout.id,
                    code=order_code,
                    amount=total,
                    seats=seats,
                    expires_at=expires_at,
                    status="active",
                )
            )
            await session.flush()
    except IntegrityError as e:
        if PENDING_PHONE_INDEX in str(e.orig):
            raise _pending_exists() from None
        raise

    audit(
        session,
        audit_actor(ONLINE_ACTOR),
        "checkout.create",
        "checkout",
        checkout.pay_ref,
        {
            "kind": "ticket",
            "order_code": order_code,
            "session": ev.code,
            "seats": seats,
            "amount": total,
            "date": ev.play_date.isoformat(),
        },
    )
    outbox.add_event(
        session,
        tenant_id,
        "checkout.created",
        {"pay_ref": checkout.pay_ref, "order_code": order_code, "session": ev.code},
    )
    await session.flush()
    view = await ticket_checkout_view(session, ctx, checkout)
    return CheckoutCreated(**view.model_dump(), token=token)


async def _seat_hold(session: AsyncSession, checkout: Checkout) -> Hold:
    hold = await session.scalar(select(Hold).where(Hold.checkout_id == checkout.id))
    if hold is None or hold.session_id is None:  # bất biến: lượt mua vé có đúng một hold seat
        raise RuntimeError(f"Ticket checkout {checkout.order_code} has no seat hold")
    return hold


async def ticket_checkout_view(session: AsyncSession, ctx: Ctx, checkout: Checkout) -> CheckoutView:
    hold = await _seat_hold(session, checkout)
    ev = await session.get(EventSession, hold.session_id)
    tickets = list(
        await session.scalars(
            select(Ticket).where(Ticket.checkout_id == checkout.id).order_by(Ticket.seq)
        )
    )
    return CheckoutView(
        kind="ticket",
        status=checkout.status,
        expires_at=checkout.expires_at,
        server_now=ctx.now,
        amount=checkout.amount,
        paid_amount=checkout.paid_amount,
        paid_at=checkout.paid_at,
        order_code=checkout.order_code,
        pay_ref=checkout.pay_ref,
        customer_name=checkout.customer_name,
        customer_phone=checkout.customer_phone,
        play_date=checkout.play_date,
        items=[],
        event=CheckoutEvent(
            code=ev.code,
            name=ev.name,
            play_date=ev.play_date,
            start_time=ctx.hhmm(ev.play_date, ev.start_at),
            end_time=ctx.hhmm(ev.play_date, ev.end_at),
            resource_names=await _resource_names(session, checkout.tenant_id, ev),
            seats=hold.seats,
            ticket_price=(hold.amount or 0) // hold.seats,
            ticket_codes=[t.code for t in tickets],
            cancelled_ticket_codes=[t.code for t in tickets if t.payment_status == "cancelled"],
        ),
    )


# ------------------------------------------------------------------ tiền về -> vé (AC10, AC14)


async def apply_ticket_payment(
    session: AsyncSession, checkout: Checkout, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Checkout vé đã khóa (``FOR UPDATE``), trong hạn và đủ tiền -> ``seats`` vé đã thanh toán.

    Ghế đã giữ nên không kiểm lại sức chứa; vẫn khóa dòng sự kiện để cấp số vé tuần tự không đua
    với quầy.
    """
    tenant_id = checkout.tenant_id
    hold = await _seat_hold(session, checkout)
    ev = await session.scalar(
        select(EventSession).where(EventSession.id == hold.session_id).with_for_update()
    )
    seq = await session.scalar(select(func.max(Ticket.seq)).where(Ticket.session_id == ev.id)) or 0
    price = (hold.amount or 0) // hold.seats
    codes, tickets = [], []
    for n in range(1, hold.seats + 1):
        ticket = Ticket(
            tenant_id=tenant_id,
            session_id=ev.id,
            seq=seq + n,
            code=f"{ev.code}-V{seq + n:02d}",
            source="online",
            checkout_id=checkout.id,
            amount=price,
            payment_status="paid",
            payment_method="online_transfer",
            paid_at=data.transaction_at,
            collected_by_type=ONLINE_ACTOR.type,
            collected_by_label=ONLINE_ACTOR.label,
            gateway_ref=f"{data.reference}:{n}",
            created_by_type=ONLINE_ACTOR.type,
            created_by_label=ONLINE_ACTOR.label,
            version=1,
            customer_ref=checkout.customer_ref,
            customer_kind=checkout.customer_kind,
            customer_name=checkout.customer_name,
            customer_phone=checkout.customer_phone,
            member_code=checkout.member_code,
            member_tier=checkout.member_tier,
        )
        session.add(ticket)
        codes.append(ticket.code)
        tickets.append(ticket)
    await session.flush()
    hold.status = "converted"
    checkout.status = "paid"
    checkout.paid_at = data.transaction_at
    await ledger.record_in(
        session,
        tenant_id,
        tickets,
        method="online_transfer",
        occurred_at=data.transaction_at,
        actor=ledger.GATEWAY_ACTOR,
        reference=data.reference,
    )
    # Như booking online: tiền về qua bên thứ 3 -> người làm là Hệ thống; 1 lần trả = 1 dòng
    audit(
        session,
        SYSTEM_ACTOR,
        "ticket.online.paid",
        "checkout",
        checkout.pay_ref,
        audit_detail(
            checkout.order_code,
            checkout.customer_name,
            paid_changes("QR"),
            order_code=checkout.order_code,
            session=ev.code,
            codes=codes,
            amount=checkout.amount,
            paid_amount=checkout.paid_amount,
        ),
    )
    for code in codes:
        outbox.add_event(session, tenant_id, "ticket.created", {"code": code, "session": ev.code})
    outbox.add_event(
        session,
        tenant_id,
        "ticket.online_paid",
        {
            "order_code": checkout.order_code,
            "session": ev.code,
            "codes": codes,
            "customer_kind": checkout.customer_kind,
            "full_name": checkout.customer_name,
            "phone": checkout.customer_phone,
        },
    )
    await session.flush()
    return OnlinePaymentResult(
        outcome="applied",
        refund_amount=checkout.paid_amount - checkout.amount,
        booking_codes=codes,
    )


# ------------------------------------------------------------------ tra cứu vé (AC21)


def _ticket_status(statuses: list[str]) -> str:
    statuses = [s for s in statuses if s != "cancelled"]
    if not statuses:
        return "cancelled"
    if "unpaid" in statuses:
        return "unpaid"
    if all(s == "paid" for s in statuses):
        return "paid"
    return "uncollectible"


async def lookup_ticket_checkout(
    session: AsyncSession, ctx: Ctx, checkout: Checkout
) -> LookupResult:
    """Đơn vé online theo mã đơn: chờ thanh toán / hết hạn / đã trả (kèm mã vé)."""
    view = await ticket_checkout_view(session, ctx, checkout)
    ev = view.event
    tickets = list(
        await session.scalars(
            select(Ticket).where(Ticket.checkout_id == checkout.id).order_by(Ticket.seq)
        )
    )
    if checkout.status == "paid":
        status = _ticket_status([t.payment_status for t in tickets])
    else:
        status = checkout.status
    pending = checkout.status == "pending"
    return LookupResult(
        kind="ticket",
        order_code=checkout.order_code,
        status=status,
        play_date=checkout.play_date,
        hours=0,
        customer_name=checkout.customer_name,
        customer_phone=checkout.customer_phone,
        amount=(
            sum(t.amount for t in tickets if t.payment_status != "cancelled")
            if checkout.status == "paid"
            else checkout.amount
        ),
        payment_method="online_transfer" if checkout.status == "paid" else None,
        paid_at=checkout.paid_at,
        items=[],
        pending=LookupPending(
            expires_at=checkout.expires_at,
            server_now=ctx.now,
            pay_ref=checkout.pay_ref,
            amount=checkout.amount,
        )
        if pending
        else None,
        event=LookupEvent(
            code=ev.code,
            name=ev.name,
            start_time=ev.start_time,
            end_time=ev.end_time,
            resource_names=ev.resource_names,
            seats=ev.seats,
            ticket_price=ev.ticket_price,
            tickets=[LookupTicket(code=t.code, pay_status=t.payment_status) for t in tickets],
        ),
    )


async def lookup_counter_ticket(session: AsyncSession, ctx: Ctx, ticket: Ticket) -> LookupResult:
    """Vé đăng ký tại quầy (không có lượt thanh toán) tra theo mã vé: một vé."""
    ev = await session.get(EventSession, ticket.session_id)
    return LookupResult(
        kind="ticket",
        order_code=ticket.code,
        status=ticket.payment_status,
        play_date=ev.play_date,
        hours=0,
        customer_name=ticket.customer_name,
        customer_phone=ticket.customer_phone,
        amount=0 if ticket.payment_status == "cancelled" else ticket.amount,
        payment_method=ticket.payment_method,
        paid_at=ticket.paid_at,
        items=[],
        event=LookupEvent(
            code=ev.code,
            name=ev.name,
            start_time=ctx.hhmm(ev.play_date, ev.start_at),
            end_time=ctx.hhmm(ev.play_date, ev.end_at),
            resource_names=await _resource_names(session, ticket.tenant_id, ev),
            seats=1,
            ticket_price=ticket.amount,
            tickets=[LookupTicket(code=ticket.code, pay_status=ticket.payment_status)],
        ),
    )


async def find_ticket(session: AsyncSession, tenant_id: int, code: str) -> Ticket | None:
    return await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.code == code)
    )


# ------------------------------------------------------------------ sự kiện sắp tới (T-045)


async def upcoming_events(
    session: AsyncSession, tenant_id: int, refs: list[str], days: int
) -> list[UpcomingEvent]:
    """Sự kiện còn hiệu lực **chưa bắt đầu**, ngày diễn ra từ hôm nay tới hôm nay + ``days`` (giờ
    VN), sắp theo giờ bắt đầu. ``refs`` = customer_ref của hội viên -> đếm vé của mình."""
    ctx = await context(session, tenant_id)
    events = list(
        await session.scalars(
            select(EventSession)
            .where(
                EventSession.tenant_id == tenant_id,
                EventSession.status == "active",
                EventSession.start_at > ctx.now,
                EventSession.play_date <= ctx.today + timedelta(days=days),
            )
            .order_by(EventSession.start_at, EventSession.code)
        )
    )
    if not events:
        return []
    ids = [ev.id for ev in events]
    counts = await session_counts(session, tenant_id, ids)
    courts = await session_resources(session, tenant_id, ids)
    mine = (
        dict(
            (
                await session.execute(
                    select(Ticket.session_id, func.count())
                    .where(
                        Ticket.tenant_id == tenant_id,
                        Ticket.session_id.in_(ids),
                        Ticket.customer_ref.in_(refs),
                        Ticket.payment_status != "cancelled",
                    )
                    .group_by(Ticket.session_id)
                )
            ).all()
        )
        if refs
        else {}
    )
    out = []
    for ev in events:
        tickets_n, _, held = counts[ev.id]
        taken = tickets_n + held
        remaining = max(ev.capacity - taken, 0)
        reason = _buy_block(ctx, ev, remaining)
        out.append(
            UpcomingEvent(
                code=ev.code,
                name=ev.name,
                play_date=ev.play_date,
                start_at=ev.start_at,
                end_at=ev.end_at,
                start_time=ctx.hhmm(ev.play_date, ev.start_at),
                end_time=ctx.hhmm(ev.play_date, ev.end_at),
                resource_names=[r.name for r in courts.get(ev.id, [])],
                ticket_price=ev.ticket_price,
                capacity=ev.capacity,
                taken=taken,
                remaining=remaining,
                can_buy=reason is None,
                reason=reason,
                my_ticket_count=mine.get(ev.id, 0),
            )
        )
    return out

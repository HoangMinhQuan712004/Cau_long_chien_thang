"""Lịch ngày, tìm mã, đặt tại quầy, thông tin booking / vé (T-006 §3, FR-001…004, FR-006, FR-011).

Hàm ở đây **không commit** – lớp gọi sở hữu transaction. Chống trùng lịch chỉ bằng exclusion
constraint của ``allocation`` (BR-010): lỗi ``23P01`` -> ``E-003``.
"""

import math
from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    PAST_SLOT,
    Ctx,
    audit_actor,
    context,
    not_found,
    profile_label,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code, price_slots
from app.modules.booking_engine.dto import (
    Actor,
    CalendarBlock,
    CalendarCan,
    CalendarOut,
    CalendarResource,
    CounterBookingIn,
    CustomerSnapshot,
    ItemCustomer,
    ItemOut,
    ItemPayment,
    ItemSchedule,
    ItemSessionRef,
    QuoteItem,
    SearchResult,
)
from app.modules.booking_engine.holds import expire_holds, hold_visible
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    EventSession,
    Hold,
    Resource,
    ResourceType,
    Ticket,
)
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

DEFAULT_COLUMNS = (5, 22)


# ------------------------------------------------------------------ chỗ chiếm theo ngày


async def session_resources(
    session: AsyncSession, tenant_id: int, session_ids: list[int]
) -> dict[int, list[Resource]]:
    """Tài nguyên của từng sự kiện (theo allocation, kể cả đã tắt), sắp theo thứ tự hiển thị."""
    if not session_ids:
        return {}
    rows = await session.execute(
        select(Allocation.session_id, Resource)
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(Allocation.tenant_id == tenant_id, Allocation.session_id.in_(session_ids))
        .distinct()
        .order_by(Resource.sort_order, Resource.code)
    )
    result: dict[int, list[Resource]] = defaultdict(list)
    for sid, r in rows:
        if r not in result[sid]:
            result[sid].append(r)
    return result


async def session_counts(
    session: AsyncSession, tenant_id: int, session_ids: list[int]
) -> dict[int, tuple[int, int, int]]:
    """(số vé mọi trạng thái, số vé chưa trả, số chỗ đang giữ online còn hạn) theo sự kiện."""
    if not session_ids:
        return {}
    counts: dict[int, list[int]] = {sid: [0, 0, 0] for sid in session_ids}
    for sid, total, unpaid in await session.execute(
        select(
            Ticket.session_id,
            func.count(),
            func.count().filter(Ticket.payment_status == "unpaid"),
        )
        .where(Ticket.tenant_id == tenant_id, Ticket.session_id.in_(session_ids))
        .group_by(Ticket.session_id)
    ):
        counts[sid][0], counts[sid][1] = total, unpaid
    for sid, seats in await session.execute(
        select(Hold.session_id, func.coalesce(func.sum(Hold.seats), 0))
        .where(
            Hold.tenant_id == tenant_id,
            Hold.session_id.in_(session_ids),
            Hold.status == "active",
            Hold.expires_at > func.now(),
        )
        .group_by(Hold.session_id)
    ):
        counts[sid][2] = int(seats)
    return {sid: (a, b, c) for sid, (a, b, c) in counts.items()}


# ------------------------------------------------------------------ lịch ngày (BR-001, 002, 004)


async def calendar(
    session: AsyncSession,
    tenant_id: int,
    day: date,
    can_counter: bool,
    can_session: bool,
) -> CalendarOut:
    """Xem được mọi ngày (ngày đã qua: chỉ xem) – T-008 AC31b.

    ``can.counter_book``: chỉ hôm nay (cả Admin);
    ``can.create_session``: từ hôm nay, không giới hạn ngày tới.
    """
    ctx = await context(session, tenant_id)
    day_start, day_end = ctx.at(day, 0), ctx.at(day, 24 * 60)

    resources = list(
        await session.scalars(
            select(Resource)
            .where(Resource.tenant_id == tenant_id)
            .order_by(Resource.sort_order, Resource.code)
        )
    )
    types = {
        t.id: t.code
        for t in await session.scalars(
            select(ResourceType).where(ResourceType.tenant_id == tenant_id)
        )
    }
    by_id = {r.id: r for r in resources}
    schedules = await schedules_of(session, tenant_id)

    blocks: list[CalendarBlock] = []
    busy_resources: set[int] = set()
    span = [24 * 60, 0]  # phút sớm nhất / muộn nhất của các khối

    def add_span(start_min: int, end_min: int) -> None:
        span[0], span[1] = min(span[0], start_min), max(span[1], end_min)

    # Booking của ngày (Không thu được vẫn giữ khối)
    bookings = list(
        await session.scalars(
            select(Booking)
            .where(Booking.tenant_id == tenant_id, Booking.play_date == day)
            .order_by(Booking.start_at)
        )
    )
    for b in bookings:
        r = by_id[b.resource_id]
        s_min, e_min = ctx.minute_of(day, b.start_at), ctx.minute_of(day, b.end_at)
        busy_resources.add(r.id)
        add_span(s_min, e_min)
        blocks.append(
            CalendarBlock(
                type="booking",
                code=b.code,
                resource_codes=[r.code],
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                start_hour=s_min // 60,
                end_hour=math.ceil(e_min / 60),
                payment_status=b.payment_status,
                customer_name=b.customer_name,
                phone=b.customer_phone,
                source=b.source,
            )
        )

    # Sự kiện còn hiệu lực trong ngày
    sessions = list(
        await session.scalars(
            select(EventSession)
            .where(
                EventSession.tenant_id == tenant_id,
                EventSession.play_date == day,
                EventSession.status == "active",
            )
            .order_by(EventSession.start_at)
        )
    )
    sids = [s.id for s in sessions]
    res_of = await session_resources(session, tenant_id, sids)
    counts = await session_counts(session, tenant_id, sids)
    unpaid_tickets_total = 0
    for ev in sessions:
        s_min, e_min = ctx.minute_of(day, ev.start_at), ctx.minute_of(day, ev.end_at)
        ev_res = res_of.get(ev.id, [])
        busy_resources.update(r.id for r in ev_res)
        add_span(s_min, e_min)
        tickets, unpaid, held = counts.get(ev.id, (0, 0, 0))
        unpaid_tickets_total += unpaid
        taken = tickets + held
        blocks.append(
            CalendarBlock(
                type="session",
                code=ev.code,
                resource_codes=[r.code for r in ev_res],
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                start_hour=s_min // 60,
                end_hour=math.ceil(e_min / 60),
                name=ev.name,
                taken=taken,
                capacity=ev.capacity,
                is_full=taken >= ev.capacity,
                unpaid_tickets=unpaid,
            )
        )

    # Giữ chỗ khung sân còn hạn (viền đứt, đếm ngược tới expires_at)
    holds = await session.execute(
        select(Allocation, Hold)
        .join(Hold, Hold.id == Allocation.hold_id)
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.kind == "hold",
            Allocation.active.is_(True),
            Allocation.time_range.overlaps(Range(day_start, day_end, bounds="[)")),
            hold_visible(ctx.now),
        )
    )
    for alloc, hold in holds:
        r = by_id[alloc.resource_id]
        s_min = ctx.minute_of(day, alloc.time_range.lower)
        e_min = ctx.minute_of(day, alloc.time_range.upper)
        busy_resources.add(r.id)
        add_span(s_min, e_min)
        blocks.append(
            CalendarBlock(
                type="hold",
                code=None,
                resource_codes=[r.code],
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                start_hour=s_min // 60,
                end_hour=math.ceil(e_min / 60),
                expires_at=hold.expires_at,
            )
        )

    # Hàng: sân hoạt động + sân ngừng còn chỗ chiếm trong ngày
    shown = [r for r in resources if r.is_active or r.id in busy_resources]
    hours_of: dict[int, Hours | None] = {}
    for r in shown:
        sched = effective_on(schedules.get(r.id, []), day)
        hours_of[r.id] = Hours.of(sched) if sched else None
    open_hours = [h for r in shown if r.is_active and (h := hours_of[r.id]) is not None]
    if open_hours:
        add_span(min(h.open_minute for h in open_hours), max(h.close_minute for h in open_hours))
    if span[0] >= span[1]:
        span = [DEFAULT_COLUMNS[0] * 60, DEFAULT_COLUMNS[1] * 60]
    columns = list(range(span[0] // 60, math.ceil(span[1] / 60)))

    calendar_resources = []
    for r in shown:
        hours = hours_of[r.id]
        off = [
            h
            for h in columns
            if not r.is_active or hours is None or not hours.sells(h * 60, h * 60 + 60)
        ]
        calendar_resources.append(
            CalendarResource(
                code=r.code,
                name=r.name,
                type=types.get(r.resource_type_id, ""),
                is_active=r.is_active,
                off_hours=off,
            )
        )

    unpaid_count = sum(1 for b in bookings if b.payment_status == "unpaid") + unpaid_tickets_total
    blocks.sort(key=lambda b: (b.start_hour, b.resource_codes[0] if b.resource_codes else ""))
    return CalendarOut(
        date=day,
        now=ctx.now,
        is_past=day < ctx.today,
        columns=columns,
        resources=calendar_resources,
        blocks=blocks,
        unpaid_count=unpaid_count,
        can=CalendarCan(
            counter_book=can_counter and day == ctx.today,
            create_session=can_session and ctx.today <= day,
        ),
    )


# ------------------------------------------------------------------ tìm mã (BR-023)


def normalize_code(raw: str) -> str:
    return "".join((raw or "").split()).upper()


async def search(session: AsyncSession, tenant_id: int, raw: str) -> SearchResult:
    code = normalize_code(raw)
    if code:
        b = await session.scalar(
            select(Booking).where(Booking.tenant_id == tenant_id, Booking.code == code)
        )
        if b is not None:
            return SearchResult(kind="booking", code=b.code, play_date=b.play_date)
        row = (
            await session.execute(
                select(Ticket.code, EventSession.play_date)
                .join(EventSession, EventSession.id == Ticket.session_id)
                .where(Ticket.tenant_id == tenant_id, Ticket.code == code)
            )
        ).first()
        if row is not None:
            return SearchResult(kind="ticket", code=row.code, play_date=row.play_date)
        ev = await session.scalar(
            select(EventSession).where(
                EventSession.tenant_id == tenant_id,
                EventSession.code == code,
                EventSession.status == "active",
            )
        )
        if ev is not None:
            return SearchResult(kind="session", code=ev.code, play_date=ev.play_date)
    shown = code or (raw or "").strip()
    raise AppError("E-021", f"Không tìm thấy mã {shown}. Kiểm tra lại mã.", 404)


# ------------------------------------------------------------------ thông tin booking / vé


def payment_actions(item: Booking | Ticket, start_at, ctx: Ctx) -> list[str]:
    """Thao tác được phép lúc này (BR-013, BR-015)."""
    if item.payment_status != "unpaid":
        return []
    actions = ["collect"]
    if item.source == "counter" and ctx.now >= start_at:
        actions.append("uncollectible")
    return actions


def _payment(item: Booking | Ticket) -> ItemPayment:
    return ItemPayment(
        amount=item.amount,
        payment_status=item.payment_status,
        payment_method=item.payment_method,
        paid_at=item.paid_at,
        collected_by=item.collected_by_label,
        uncollectible_reason=item.uncollectible_reason,
        marked_by=item.marked_by_label,
        marked_at=item.marked_at,
    )


def _customer(item: Booking | Ticket) -> ItemCustomer:
    return ItemCustomer(
        name=item.customer_name,
        phone=item.customer_phone,
        profile_label=profile_label(item.customer_kind, item.member_code, item.member_tier),
        kind=item.customer_kind,
        member_code=item.member_code,
        tier=item.member_tier,
    )


async def booking_item(session: AsyncSession, ctx: Ctx, b: Booking) -> ItemOut:
    r = await session.get(Resource, b.resource_id)
    return ItemOut(
        kind="booking",
        code=b.code,
        version=b.version,
        source=b.source,
        customer=_customer(b),
        schedule=ItemSchedule(
            resource_codes=[r.code],
            resource_names=[r.name],
            play_date=b.play_date,
            start_time=ctx.hhmm(b.play_date, b.start_at),
            end_time=ctx.hhmm(b.play_date, b.end_at),
        ),
        payment=_payment(b),
        price_breakdown=[QuoteItem(**p) for p in b.price_breakdown or []],
        note=b.note,
        created_by=b.created_by_label,
        created_at=b.created_at,
        actions=payment_actions(b, b.start_at, ctx),
    )


async def ticket_item(session: AsyncSession, ctx: Ctx, t: Ticket) -> ItemOut:
    ev = await session.get(EventSession, t.session_id)
    res = (await session_resources(session, ctx.tenant.id, [ev.id])).get(ev.id, [])
    return ItemOut(
        kind="ticket",
        code=t.code,
        version=t.version,
        source=t.source,
        customer=_customer(t),
        schedule=ItemSchedule(
            resource_codes=[r.code for r in res],
            resource_names=[r.name for r in res],
            play_date=ev.play_date,
            start_time=ctx.hhmm(ev.play_date, ev.start_at),
            end_time=ctx.hhmm(ev.play_date, ev.end_at),
            session=ItemSessionRef(code=ev.code, name=ev.name),
        ),
        payment=_payment(t),
        note=t.note,
        created_by=t.created_by_label,
        created_at=t.created_at,
        actions=payment_actions(t, ev.start_at, ctx),
    )


async def get_item(session: AsyncSession, tenant_id: int, raw_code: str) -> ItemOut:
    ctx = await context(session, tenant_id)
    code = normalize_code(raw_code)
    b = await session.scalar(
        select(Booking).where(Booking.tenant_id == tenant_id, Booking.code == code)
    )
    if b is not None:
        return await booking_item(session, ctx, b)
    t = await session.scalar(
        select(Ticket).where(Ticket.tenant_id == tenant_id, Ticket.code == code)
    )
    if t is not None:
        return await ticket_item(session, ctx, t)
    raise not_found(f"booking hoặc vé {code}")


# ------------------------------------------------------------------ đặt tại quầy (BR-005…011)


def snapshot_values(customer: CustomerSnapshot) -> dict:
    return {
        "customer_ref": customer.ref_id,
        "customer_kind": customer.kind,
        "customer_name": customer.display_name,
        "customer_phone": customer.phone,
        "member_code": customer.member_code,
        "member_tier": customer.tier,
    }


def slot_taken() -> AppError:
    return AppError("E-003", "Khung giờ này vừa có người đặt. Vui lòng chọn khung khác.", 409)


async def create_counter_booking(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    data: CounterBookingIn,
    customer: CustomerSnapshot,
    note: str | None = None,
) -> ItemOut:
    """1 lần chọn = 1 booking ``unpaid`` trên 1 sân, hôm nay; tiền tính ở server (BR-009)."""
    ctx = await context(session, tenant_id)
    if data.date > ctx.today and ctx.settings.get("counter_same_day_only", True):
        raise AppError(
            "E-AUTH-2",
            "Đặt sân tại quầy chỉ cho ngày hôm nay. Ngày khác dùng Đặt sự kiện.",
            403,
        )
    if data.date < ctx.today:
        raise AppError("E-004", PAST_SLOT, 422)
    r = await _resource_by_code(session, tenant_id, data.resource_code)
    _, items = await price_slots(session, ctx.tenant, r, data.date, data.start_hour, data.end_hour)
    # Khung đã qua = giờ kết thúc ≤ hiện tại; khung đang diễn ra vẫn đặt được (BR-011).
    # Vùng chọn chứa một khung đã qua (khung đầu tiên) là không hợp lệ.
    if ctx.at(data.date, (data.start_hour + 1) * 60) <= ctx.now:
        raise AppError("E-004", PAST_SLOT, 422)

    start_at = ctx.at(data.date, data.start_hour * 60)
    end_at = ctx.at(data.date, data.end_hour * 60)
    await expire_holds(session)
    code = await next_code(session, tenant_id, ctx.code_prefix, data.date)
    amount = sum(i.price for i in items)
    booking = Booking(
        tenant_id=tenant_id,
        code=code,
        source="counter",
        resource_id=r.id,
        play_date=data.date,
        start_at=start_at,
        end_at=end_at,
        amount=amount,
        price_breakdown=[i.model_dump() for i in items],
        payment_status="unpaid",
        note=(note or "").strip() or None,
        created_by_type=actor.type,
        created_by_id=actor.id,
        created_by_label=actor.label,
        version=1,
        **snapshot_values(customer),
    )
    try:
        async with session.begin_nested():
            session.add(booking)
            await session.flush()
            session.add(
                Allocation(
                    tenant_id=tenant_id,
                    resource_id=r.id,
                    time_range=Range(start_at, end_at, bounds="[)"),
                    kind="booking",
                    booking_id=booking.id,
                    owner_code=code,
                    active=True,
                )
            )
            await session.flush()
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            raise slot_taken() from None
        raise

    audit(
        session,
        audit_actor(actor),
        "booking.counter.create",
        "booking",
        code,
        {
            "resource": r.code,
            "date": data.date.isoformat(),
            "start_time": to_hhmm(data.start_hour * 60),
            "end_time": to_hhmm(data.end_hour * 60),
            "amount": amount,
            "customer_kind": customer.kind,
            "member_code": customer.member_code,
        },
    )
    outbox.add_event(
        session,
        tenant_id,
        "booking.created",
        {"code": code, "source": "counter", "play_date": data.date.isoformat()},
    )
    await session.flush()
    await session.refresh(booking)
    return await booking_item(session, ctx, booking)

"""Sự kiện (buổi bán vé) và vé (T-006 §3: BR-017, BR-024, BR-025; FR-005, FR-012…014).

Hàm ở đây **không commit**. Đăng ký vé / xóa buổi khóa dòng ``session`` (``FOR UPDATE``) để đếm
chỗ và kiểm "đã có người đăng ký" không bị đua.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.booking_service import (
    normalize_code,
    session_counts,
    session_resources,
    snapshot_values,
    ticket_item,
)
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    PAST_SLOT,
    Ctx,
    audit_actor,
    context,
    masked,
    not_found,
    not_sold,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code
from app.modules.booking_engine.dto import (
    Actor,
    CustomerSnapshot,
    ItemOut,
    ResourceRef,
    SessionCan,
    SessionCreate,
    SessionHold,
    SessionOut,
    SessionTicket,
)
from app.modules.booking_engine.holds import expire_holds
from app.modules.booking_engine.models import Allocation, EventSession, Hold, Resource, Ticket
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

NAME_MAX = 100
CAPACITY_RANGE = (1, 99)
STALE_SESSION = "Sự kiện vừa được cập nhật ở máy khác. Vui lòng xem lại."


def _required(field: str) -> AppError:
    return AppError("E-001", f"Vui lòng nhập {field}.", 422)


def _is_int(value) -> bool:
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


# ------------------------------------------------------------------ xem


async def _session_by_code(
    session: AsyncSession, tenant_id: int, code: str, for_update: bool = False
) -> EventSession:
    stmt = select(EventSession).where(
        EventSession.tenant_id == tenant_id,
        EventSession.code == normalize_code(code),
        EventSession.status == "active",
    )
    if for_update:
        stmt = stmt.with_for_update()
    ev = await session.scalar(stmt)
    if ev is None:
        raise not_found(f"sự kiện {normalize_code(code)}")
    return ev


def _can_register(ctx: Ctx, ev: EventSession, taken: int) -> bool:
    return (
        ev.status == "active"
        and ev.play_date == ctx.today
        and ctx.now < ev.end_at
        and taken < ev.capacity
    )


async def session_view(
    session: AsyncSession,
    ctx: Ctx,
    ev: EventSession,
    can_register_perm: bool,
    can_delete_perm: bool,
) -> SessionOut:
    resources = (await session_resources(session, ctx.tenant.id, [ev.id])).get(ev.id, [])
    tickets_n, _, held = (await session_counts(session, ctx.tenant.id, [ev.id]))[ev.id]
    taken = tickets_n + held
    tickets = await session.scalars(
        select(Ticket)
        .where(Ticket.tenant_id == ctx.tenant.id, Ticket.session_id == ev.id)
        .order_by(Ticket.seq.desc())
    )
    holds = await session.scalars(
        select(Hold)
        .where(
            Hold.tenant_id == ctx.tenant.id,
            Hold.session_id == ev.id,
            Hold.status == "active",
            Hold.expires_at > ctx.now,
        )
        .order_by(Hold.expires_at)
    )
    return SessionOut(
        code=ev.code,
        name=ev.name,
        status=ev.status,
        play_date=ev.play_date,
        start_time=ctx.hhmm(ev.play_date, ev.start_at),
        end_time=ctx.hhmm(ev.play_date, ev.end_at),
        resources=[ResourceRef(code=r.code, name=r.name) for r in resources],
        ticket_price=ev.ticket_price,
        capacity=ev.capacity,
        taken=taken,
        is_full=taken >= ev.capacity,
        created_by=ev.created_by_label,
        created_at=ev.created_at,
        version=ev.version,
        tickets=[
            SessionTicket(
                code=t.code,
                customer_name=t.customer_name,
                phone_masked=masked(t.customer_phone),
                source=t.source,
                payment_status=t.payment_status,
                amount=t.amount,
                created_at=t.created_at,
            )
            for t in tickets
        ],
        active_holds=[SessionHold(seats=h.seats, expires_at=h.expires_at) for h in holds],
        can=SessionCan(
            register=can_register_perm and _can_register(ctx, ev, taken),
            delete=can_delete_perm and ev.status == "active" and taken == 0,
        ),
    )


async def get_session(
    session: AsyncSession,
    tenant_id: int,
    code: str,
    can_register_perm: bool,
    can_delete_perm: bool,
) -> SessionOut:
    ctx = await context(session, tenant_id)
    ev = await _session_by_code(session, tenant_id, code)
    return await session_view(session, ctx, ev, can_register_perm, can_delete_perm)


# ------------------------------------------------------------------ tạo sự kiện (BR-017)


def _validate_fields(data: SessionCreate) -> tuple[str, int, int]:
    name = " ".join(data.name.split())
    if not name:
        raise _required("Tên sự kiện")
    if len(name) > NAME_MAX:
        raise AppError("E-001", f"Tên sự kiện tối đa {NAME_MAX} ký tự.", 422)
    if data.capacity is None:
        raise _required("Số chỗ tối đa")
    if not _is_int(data.capacity) or not CAPACITY_RANGE[0] <= data.capacity <= CAPACITY_RANGE[1]:
        raise AppError("E-009", "Số chỗ tối đa là số nguyên từ 1 đến 99.", 422)
    if data.ticket_price is None:
        raise _required("Giá vé")
    if not _is_int(data.ticket_price) or data.ticket_price < 0:
        raise AppError("E-013", "Giá vé phải là số nguyên từ 0 trở lên.", 422)
    return name, int(data.capacity), int(data.ticket_price)


async def _resources_for(
    session: AsyncSession, ctx: Ctx, codes: list[str], data: SessionCreate
) -> list[Resource]:
    """Sân chọn: tồn tại, đang hoạt động, liền nhau theo thứ tự hiển thị, bán được khung giờ."""
    wanted = list(dict.fromkeys(c.strip().upper() for c in codes))
    resources = [await _resource_by_code(session, ctx.tenant.id, c) for c in wanted]
    active = list(
        await session.scalars(
            select(Resource.id)
            .where(Resource.tenant_id == ctx.tenant.id, Resource.is_active.is_(True))
            .order_by(Resource.sort_order, Resource.code)
        )
    )
    schedules = await schedules_of(session, ctx.tenant.id, [r.id for r in resources])
    for r in resources:
        sched = effective_on(schedules.get(r.id, []), data.date)
        if not r.is_active or sched is None:
            raise not_sold(f"{r.name} không nhận đặt vào ngày {data.date:%d/%m/%Y}.")
        hours = Hours.of(sched)
        for h in range(data.start_hour, data.end_hour):
            if not hours.sells(h * 60, h * 60 + 60):
                raise not_sold(f"Khung {h:02d}:00–{h + 1:02d}:00 của {r.name} không bán.")
    positions = sorted(active.index(r.id) for r in resources)
    if positions != list(range(positions[0], positions[0] + len(positions))):
        raise AppError("E-BOOK-2", "Các sân của sự kiện phải liền nhau.", 422)
    return sorted(resources, key=lambda r: active.index(r.id))


async def _clash_message(
    session: AsyncSession, ctx: Ctx, resources: list[Resource], start: datetime, end: datetime
) -> str:
    """Tìm khung vướng đầu tiên để báo E-010 cụ thể (sau khi exclusion đã chặn)."""
    for r in resources:
        row = await session.scalar(
            select(Allocation)
            .where(
                Allocation.tenant_id == ctx.tenant.id,
                Allocation.resource_id == r.id,
                Allocation.active.is_(True),
                Allocation.time_range.overlaps(Range(start, end, bounds="[)")),
            )
            .order_by(func.lower(Allocation.time_range))
            .limit(1)
        )
        if row is not None:
            day = start.astimezone(ctx.tz).date()
            s = max(row.time_range.lower, start)
            e = min(row.time_range.upper, end)
            return (
                f"Khung {ctx.hhmm(day, s)}–{ctx.hhmm(day, e)} ở {r.name} đã có người đặt. "
                "Vui lòng chọn vùng khác."
            )
    return "Khung giờ đã chọn đã có người đặt. Vui lòng chọn vùng khác."


async def create_session(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    data: SessionCreate,
    can_register_perm: bool = True,
    can_delete_perm: bool = True,
) -> SessionOut:
    """Thứ tự kiểm theo SRS: ô bắt buộc, số chỗ, giá vé -> khung chưa qua -> khung còn trống."""
    ctx = await context(session, tenant_id)
    name, capacity, ticket_price = _validate_fields(data)
    if data.start_hour >= data.end_hour:
        raise not_sold("Giờ kết thúc phải sau giờ bắt đầu.")
    if data.date < ctx.today or ctx.at(data.date, (data.start_hour + 1) * 60) <= ctx.now:
        raise AppError("E-004", PAST_SLOT, 422)
    resources = await _resources_for(session, ctx, data.resource_codes, data)

    start_at = ctx.at(data.date, data.start_hour * 60)
    end_at = ctx.at(data.date, data.end_hour * 60)
    await expire_holds(session)
    code = await next_code(session, tenant_id, ctx.code_prefix, data.date)
    ev = EventSession(
        tenant_id=tenant_id,
        code=code,
        name=name,
        play_date=data.date,
        start_at=start_at,
        end_at=end_at,
        capacity=capacity,
        ticket_price=ticket_price,
        status="active",
        created_by_type=actor.type,
        created_by_id=actor.id,
        created_by_label=actor.label,
        version=1,
    )
    try:
        async with session.begin_nested():
            session.add(ev)
            await session.flush()
            for r in resources:
                session.add(
                    Allocation(
                        tenant_id=tenant_id,
                        resource_id=r.id,
                        time_range=Range(start_at, end_at, bounds="[)"),
                        kind="session",
                        session_id=ev.id,
                        owner_code=code,
                        active=True,
                    )
                )
            await session.flush()
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            message = await _clash_message(session, ctx, resources, start_at, end_at)
            raise AppError("E-010", message, 409) from None
        raise

    audit(
        session,
        audit_actor(actor),
        "session.create",
        "session",
        code,
        {
            "name": name,
            "resources": [r.code for r in resources],
            "date": data.date.isoformat(),
            "start_time": to_hhmm(data.start_hour * 60),
            "end_time": to_hhmm(data.end_hour * 60),
            "capacity": capacity,
            "ticket_price": ticket_price,
        },
    )
    outbox.add_event(
        session, tenant_id, "session.created", {"code": code, "play_date": data.date.isoformat()}
    )
    await session.flush()
    await session.refresh(ev)
    return await session_view(session, ctx, ev, can_register_perm, can_delete_perm)


# ------------------------------------------------------------------ xóa buổi (BR-025)


async def delete_session(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, version: int
) -> SessionOut:
    ctx = await context(session, tenant_id)
    ev = await _session_by_code(session, tenant_id, code, for_update=True)
    tickets_n, _, held = (await session_counts(session, tenant_id, [ev.id]))[ev.id]
    if tickets_n or held:
        raise AppError("E-023", "Sự kiện đã có người đăng ký, không xóa được.", 409)
    if version != ev.version:
        raise AppError("E-012", STALE_SESSION, 409)

    resources = (await session_resources(session, tenant_id, [ev.id])).get(ev.id, [])
    ev.status = "deleted"
    ev.deleted_at = ctx.now
    ev.deleted_by_type, ev.deleted_by_id, ev.deleted_by_label = actor.type, actor.id, actor.label
    ev.version += 1
    for alloc in await session.scalars(
        select(Allocation).where(Allocation.tenant_id == tenant_id, Allocation.session_id == ev.id)
    ):
        alloc.active = False
    audit(
        session,
        audit_actor(actor),
        "session.delete",
        "session",
        ev.code,
        {"name": ev.name, "resources": [r.code for r in resources]},
    )
    outbox.add_event(session, tenant_id, "session.deleted", {"code": ev.code})
    await session.flush()
    return await session_view(session, ctx, ev, False, False)


# ------------------------------------------------------------------ đăng ký vé tại quầy (BR-024)


async def register_ticket(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    code: str,
    customer: CustomerSnapshot,
    note: str | None = None,
) -> ItemOut:
    ctx = await context(session, tenant_id)
    # Khóa dòng sự kiện: đếm chỗ + cấp số vé tuần tự, hai máy không vượt sức chứa
    ev = await _session_by_code(session, tenant_id, code, for_update=True)
    if ev.play_date != ctx.today:
        message = (
            "Không thể đăng ký vé cho sự kiện đã qua."
            if ev.play_date < ctx.today
            else "Chỉ đăng ký vé tại quầy cho sự kiện diễn ra hôm nay."
        )
        raise AppError("E-004", message, 422)
    if ev.end_at <= ctx.now:
        raise AppError("E-004", "Không thể đăng ký vé cho sự kiện đã kết thúc.", 422)
    tickets_n, _, held = (await session_counts(session, tenant_id, [ev.id]))[ev.id]
    if tickets_n + held >= ev.capacity:
        raise AppError("E-024", "Sự kiện đã đủ chỗ.", 409)

    seq = (
        await session.scalar(select(func.max(Ticket.seq)).where(Ticket.session_id == ev.id)) or 0
    ) + 1
    ticket = Ticket(
        tenant_id=tenant_id,
        session_id=ev.id,
        seq=seq,
        code=f"{ev.code}-V{seq:02d}",
        source="counter",
        amount=ev.ticket_price,
        payment_status="unpaid",
        note=(note or "").strip() or None,
        created_by_type=actor.type,
        created_by_id=actor.id,
        created_by_label=actor.label,
        version=1,
        **snapshot_values(customer),
    )
    session.add(ticket)
    await session.flush()
    audit(
        session,
        audit_actor(actor),
        "ticket.create",
        "ticket",
        ticket.code,
        {
            "session": ev.code,
            "amount": ticket.amount,
            "customer_kind": customer.kind,
            "member_code": customer.member_code,
        },
    )
    outbox.add_event(
        session, tenant_id, "ticket.created", {"code": ticket.code, "session": ev.code}
    )
    await session.flush()
    await session.refresh(ticket)
    return await ticket_item(session, ctx, ticket)

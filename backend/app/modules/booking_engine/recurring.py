"""Đặt sân định kỳ (T-035): Admin chọn các thứ + khung giờ, từ ngày -> đến ngày, một sân.

- Mỗi ngày khớp thứ = **một buổi** = một booking nhiều giờ, mã con ``{mã đơn}-NN`` theo thời gian.
- Kiểm **theo từng ngày** với cấu hình có hiệu lực ngày đó: sân hoạt động, giờ mở cửa, bảng giá
  (thường / cuối tuần / Lễ × cao / thấp điểm – ``price_slots``), giờ đã qua, chỗ đã bị chiếm.
- Giảm % cho cả đơn: ``discount = round_half_up(gốc × pct / 100)``, phân bổ ``floor`` theo tỉ lệ
  giá, phần dư dồn buổi cuối -> tổng các buổi = gốc − giảm, khớp từng đồng.
- Tạo: một transaction, **tất cả hoặc không** – exclusion constraint vẫn là chốt chặn cuối.

Hàm ở đây **không commit**.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine.audit_fields import customer_text_masked, new_values, vnd
from app.modules.booking_engine.booking_service import booking_item
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    Ctx,
    audit_actor,
    context,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code, price_slots
from app.modules.booking_engine.dto import (
    Actor,
    CustomerSnapshot,
    RecurringCreated,
    RecurringIn,
    RecurringPreview,
    RecurringReason,
    RecurringSession,
)
from app.modules.booking_engine.holds import expire_holds, hold_visible
from app.modules.booking_engine.models import Allocation, Booking, Hold, Resource
from app.modules.booking_engine.orders import child_code, emit_created, new_order, snapshot_values
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

MAX_DAYS = 92
MAX_SESSIONS = 60
REASONS: dict[RecurringReason, str] = {
    "booked": "Đã có người đặt",
    "event": "Có sự kiện",
    "hold": "Đang giữ chỗ online",
    "closed": "Ngoài giờ mở cửa",
    "inactive": "Sân ngừng hoạt động",
    "past": "Giờ đã qua",
    "no_price": "Chưa có bảng giá cho ngày này",
}


def _invalid(message: str) -> AppError:
    return AppError("E-001", message, 422)


def _dates(ctx: Ctx, data: RecurringIn) -> list[date]:
    """Ngày khớp thứ trong [từ, đến]; kiểm giới hạn (422)."""
    weekdays = set(data.weekdays)
    if not weekdays:
        raise _invalid("Chọn ít nhất 1 thứ trong tuần.")
    if not weekdays <= set(range(1, 8)):
        raise _invalid("Thứ trong tuần phải từ 1 (Thứ 2) đến 7 (Chủ nhật).")
    if data.start_hour >= data.end_hour:
        raise _invalid("Giờ kết thúc phải sau giờ bắt đầu.")
    if data.date_from < ctx.today:
        raise AppError("E-004", "Từ ngày phải từ hôm nay trở đi.", 422)
    if data.date_to < data.date_from:
        raise AppError("E-016", "Từ ngày không được sau Đến ngày.", 422)
    if (data.date_to - data.date_from).days + 1 > MAX_DAYS:
        raise _invalid(f"Khoảng ngày tối đa {MAX_DAYS} ngày.")
    days = [
        d
        for i in range((data.date_to - data.date_from).days + 1)
        if (d := data.date_from + timedelta(days=i)).isoweekday() in weekdays
    ]
    if not days:
        raise _invalid("Không có buổi nào trong khoảng ngày đã chọn.")
    if len(days) > MAX_SESSIONS:
        raise _invalid(f"Mỗi đơn định kỳ tối đa {MAX_SESSIONS} buổi (đang có {len(days)}).")
    return days


async def _taken_reason(
    session: AsyncSession, ctx: Ctx, r: Resource, start: datetime, end: datetime
) -> RecurringReason | None:
    """Chỗ đang bị chiếm: sự kiện > đã đặt > giữ chỗ online còn hiệu lực."""
    rows = await session.execute(
        select(Allocation.kind, Hold.id)
        .outerjoin(Hold, (Hold.id == Allocation.hold_id) & hold_visible(ctx.now))
        .where(
            Allocation.tenant_id == ctx.tenant.id,
            Allocation.resource_id == r.id,
            Allocation.active.is_(True),
            Allocation.time_range.overlaps(Range(start, end, bounds="[)")),
        )
    )
    kinds = {kind for kind, hold_id in rows if kind != "hold" or hold_id is not None}
    for kind, reason in (("session", "event"), ("booking", "booked"), ("hold", "hold")):
        if kind in kinds:
            return reason  # type: ignore[return-value]
    return None


def _allocate(prices: list[int], pct: int) -> tuple[int, int, list[int]]:
    """(gốc, giảm, giảm từng buổi): half-up cho tổng giảm, floor theo tỉ lệ, dư dồn buổi cuối."""
    original = sum(prices)
    discount = (original * pct + 50) // 100
    if original == 0 or discount == 0:
        return original, 0, [0] * len(prices)
    shares = [p * discount // original for p in prices]
    shares[-1] += discount - sum(shares)
    return original, discount, shares


async def _plan(
    session: AsyncSession, ctx: Ctx, r: Resource, data: RecurringIn
) -> tuple[list[RecurringSession], list[list]]:
    """Từng buổi + lý do lỗi (nếu có) + giá; trả kèm bảng giá chi tiết từng buổi để lưu."""
    days = _dates(ctx, data)
    schedules = (await schedules_of(session, ctx.tenant.id, [r.id])).get(r.id, [])
    a, b = data.start_hour, data.end_hour
    plans: list[tuple[date, datetime, datetime, int | None, RecurringReason | None, list]] = []
    for day in days:
        start, end = ctx.at(day, a * 60), ctx.at(day, b * 60)
        reason: RecurringReason | None = None
        price: int | None = None
        items: list = []
        sched = effective_on(schedules, day)
        if not r.is_active:
            reason = "inactive"
        elif sched is None or not Hours.of(sched).sells(a * 60, b * 60):
            reason = "closed"
        else:
            try:
                _, quote = await price_slots(session, ctx.tenant, r, day, a, b)
                price, items = sum(i.price for i in quote), [i.model_dump() for i in quote]
            except AppError as e:
                reason = "no_price" if e.code == "E-019" else "closed"
        if reason is None and start <= ctx.now:
            reason = "past"
        if reason is None:
            reason = await _taken_reason(session, ctx, r, start, end)
        plans.append((day, start, end, price, reason, items))

    priced = [p[3] for p in plans if p[3] is not None]
    _, _, shares = _allocate(priced, data.discount_pct)
    share_of = iter(shares)
    out = []
    for day, start, end, price, reason, _items in plans:
        after = price - next(share_of) if price is not None else None
        out.append(
            RecurringSession(
                date=day,
                weekday=day.isoweekday(),
                start_time=to_hhmm(a * 60),
                end_time=to_hhmm(b * 60),
                start_at=start,
                end_at=end,
                price=price,
                price_after_discount=after,
                ok=reason is None,
                reason=reason,
                reason_text=REASONS[reason] if reason else None,
            )
        )
    return out, [p[5] for p in plans]


def _summary(sessions: list[RecurringSession], pct: int) -> RecurringPreview:
    original, discount, _ = _allocate([s.price for s in sessions if s.price is not None], pct)
    return RecurringPreview(
        sessions=sessions,
        count=len(sessions),
        original_amount=original,
        discount_pct=pct,
        discount_amount=discount,
        total=original - discount,
        conflicts_count=sum(not s.ok for s in sessions),
    )


async def preview(session: AsyncSession, tenant_id: int, data: RecurringIn) -> RecurringPreview:
    """Xem trước – không ghi gì."""
    ctx = await context(session, tenant_id)
    r = await _resource_by_code(session, tenant_id, data.resource_code)
    sessions, _ = await _plan(session, ctx, r, data)
    return _summary(sessions, data.discount_pct)


def _not_bookable(sessions: list[RecurringSession]) -> AppError:
    bad = [s for s in sessions if not s.ok]
    return AppError(
        "E-BOOK-5",
        f"Có {len(bad)} buổi không đặt được.",
        409,
        conflicts=[
            {
                "date": s.date.isoformat(),
                "start": s.start_time,
                "reason": s.reason,
                "reason_text": s.reason_text,
            }
            for s in bad
        ],
    )


async def create(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    data: RecurringIn,
    customer: CustomerSnapshot,
) -> RecurringCreated:
    """Một đơn (mã theo ngày buổi đầu) + mọi buổi ``unpaid`` trong một transaction.

    Có buổi lỗi -> 409 ``E-BOOK-5`` kèm ``conflicts``, không tạo gì. Hai Admin đặt chồng cùng lúc:
    exclusion constraint chặn người sau -> rollback cả đơn, tính lại danh sách buổi lỗi.
    """
    ctx = await context(session, tenant_id)
    r = await _resource_by_code(session, tenant_id, data.resource_code)
    await expire_holds(session)
    sessions, breakdowns = await _plan(session, ctx, r, data)
    if any(not s.ok for s in sessions):
        raise _not_bookable(sessions)
    summary = _summary(sessions, data.discount_pct)
    discounted = data.discount_pct > 0

    order_code = await next_code(session, tenant_id, ctx.code_prefix, sessions[0].date)
    order = new_order(
        tenant_id, order_code, sessions[0].date, "counter", snapshot_values(customer), actor.label
    )
    order.kind = "recurring"
    order.discount_pct = data.discount_pct
    order.discount_amount = summary.discount_amount
    created: list[Booking] = []
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
            for seq, (s, items) in enumerate(zip(sessions, breakdowns, strict=True), start=1):
                code = child_code(order_code, seq)
                booking = Booking(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    seq=seq,
                    code=code,
                    source="counter",
                    resource_id=r.id,
                    play_date=s.date,
                    start_at=s.start_at,
                    end_at=s.end_at,
                    amount=s.price_after_discount or 0,
                    list_amount=s.price if discounted else None,
                    price_breakdown=items,
                    payment_status="unpaid",
                    created_by_type=actor.type,
                    created_by_id=actor.id,
                    created_by_label=actor.label,
                    version=1,
                    **snapshot_values(customer),
                )
                session.add(booking)
                await session.flush()
                session.add(
                    Allocation(
                        tenant_id=tenant_id,
                        resource_id=r.id,
                        time_range=Range(s.start_at, s.end_at, bounds="[)"),
                        kind="booking",
                        booking_id=booking.id,
                        owner_code=code,
                        active=True,
                    )
                )
                await session.flush()
                created.append(booking)
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            again, _ = await _plan(session, ctx, r, data)
            raise _not_bookable(again) from None
        raise

    first, last = sessions[0], sessions[-1]
    schedule_text = (
        f"{len(sessions)} buổi, {first.date:%d/%m/%Y}–{last.date:%d/%m/%Y}, "
        f"{first.start_time}–{first.end_time}"
    )
    audit(
        session,
        audit_actor(actor),
        "booking.recurring.create",
        "booking_order",
        order_code,
        audit_detail(
            order_code,
            customer.display_name,
            new_values(
                **{
                    "Sân": r.name,
                    "Lịch": schedule_text,
                    "Khách": customer_text_masked(customer),  # spec T-035: không SĐT đầy đủ
                    "Giảm giá": f"{data.discount_pct}% ({vnd(summary.discount_amount)})"
                    if data.discount_pct
                    else None,
                    "Phải thu": vnd(summary.total),
                }
            ),
            order_code=order_code,
            resource=r.code,
            weekdays=sorted(set(data.weekdays)),
            sessions=len(sessions),
            original_amount=summary.original_amount,
            discount_pct=data.discount_pct,
            discount_amount=summary.discount_amount,
            total=summary.total,
            customer_kind=customer.kind,
            member_code=customer.member_code,
        ),
    )
    for booking in created:
        await emit_created(session, tenant_id, order, booking)  # mỗi buổi tự có phòng (T-017)
    await session.flush()
    items_out = []
    for booking in created:
        await session.refresh(booking)
        items_out.append(await booking_item(session, ctx, booking))
    return RecurringCreated(
        order_code=order_code,
        bookings=items_out,
        original_amount=summary.original_amount,
        discount_pct=data.discount_pct,
        discount_amount=summary.discount_amount,
        total=summary.total,
    )

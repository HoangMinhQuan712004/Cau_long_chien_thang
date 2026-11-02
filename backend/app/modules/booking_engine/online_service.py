"""Đặt sân online (T-008, ADR-007): lịch cho khách, lượt thanh toán (checkout), tra cứu, tiền về.

Hàm ở đây **không commit** – lớp gọi sở hữu transaction. Chống trùng vẫn chỉ bằng exclusion
constraint của ``allocation`` (giữ chỗ và booking dùng chung): ``23P01`` -> ``E-WEB-3``.
"""

import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SYSTEM_ACTOR, audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import outbox, ticket_online
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import calendar, snapshot_values
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    Ctx,
    audit_actor,
    context,
    sqlstate,
    token_hash,
)
from app.modules.booking_engine.config_service import price_slots
from app.modules.booking_engine.dto import (
    Actor,
    CheckoutCreate,
    CheckoutCreated,
    CheckoutItem,
    CheckoutView,
    CustomerSnapshot,
    LookupItem,
    LookupPending,
    LookupResult,
    OnlinePaymentIn,
    OnlinePaymentResult,
    PublicCalendar,
    PublicCalendarResource,
    PublicSlot,
)
from app.modules.booking_engine.holds import expire_holds, grace
from app.modules.booking_engine.models import (
    Allocation,
    Booking,
    BookingOrder,
    Checkout,
    Hold,
    Resource,
)
from app.modules.booking_engine.orders import (
    child_code,
    conflicts_of,
    emit_created,
    find_order,
    new_order,
    order_blocks,
    order_of_child,
    ranges_of,
)
from app.modules.booking_engine.pricing import hour_price, prices_for_day
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

MAX_SLOTS = 16
ONLINE_ACTOR = Actor(type="web", id=None, label="Khách đặt online")
PENDING_PHONE_INDEX = "uq_checkout_pending_phone"


def _web_error(code: str, message: str, status: int, **extra) -> AppError:
    return AppError(code, message, status, **extra)


def _past_day() -> AppError:
    return _web_error("E-WEB-2", "Không đặt được ngày đã qua.", 422)


# ------------------------------------------------------------------ lịch cho khách (AC1–AC2)


async def public_calendar(session: AsyncSession, tenant_id: int, day: date) -> PublicCalendar:
    ctx = await context(session, tenant_id)
    if day < ctx.today:
        raise _past_day()
    cal = await calendar(session, tenant_id, day, False, False)
    resources = {
        r.code: r
        for r in await session.scalars(
            select(Resource).where(Resource.tenant_id == tenant_id, Resource.is_active.is_(True))
        )
    }
    schedules = await schedules_of(session, tenant_id, [r.id for r in resources.values()])
    prices = await prices_for_day(session, tenant_id, day)

    occupied: dict[tuple[str, int], PublicSlot] = {}
    for b in cal.blocks:
        for code in b.resource_codes:
            for h in range(b.start_hour, b.end_hour):
                if b.type == "session":
                    occupied[(code, h)] = PublicSlot(
                        start_hour=h,
                        state="event",
                        taken=b.taken,
                        capacity=b.capacity,
                        event_code=b.code,
                    )
                else:  # booking mọi trạng thái + giữ chỗ của người khác
                    occupied.setdefault((code, h), PublicSlot(start_hour=h, state="booked"))

    out: list[PublicCalendarResource] = []
    for cr in cal.resources:
        r = resources.get(cr.code)
        if r is None:  # sân ngừng: khách không thấy
            continue
        sched = effective_on(schedules.get(r.id, []), day)
        hours = Hours.of(sched) if sched else None
        type_prices = prices.get(r.resource_type_id, {})
        slots = []
        for h in cal.columns:
            if (r.code, h) in occupied:
                slots.append(occupied[(r.code, h)])
                continue
            started = ctx.at(day, h * 60) <= ctx.now
            priced = hour_price(hours, h, type_prices)
            if started or h in cr.off_hours or priced is None:
                slots.append(PublicSlot(start_hour=h, state="closed"))
                continue
            band, price = priced
            slots.append(PublicSlot(start_hour=h, state="free", price=price, band=band))
        out.append(PublicCalendarResource(code=r.code, name=r.name, slots=slots))
    return PublicCalendar(date=day, server_now=ctx.now, columns=cal.columns, resources=out)


# ------------------------------------------------------------------ lượt thanh toán (AC10–AC14)


def _slot_error(name: str, hour: int) -> AppError:
    return _web_error(
        "E-WEB-2",
        f"Khung {name} {hour:02d}:00 không đặt được "
        "(đã qua, ngoài giờ mở cửa hoặc sân ngừng hoạt động).",
        422,
    )


async def _validatedranges_of(
    session: AsyncSession, ctx: Ctx, data: CheckoutCreate
) -> list[tuple[Resource, int, int]]:
    """Kiểm từng ô rồi gom thành dải giờ liền nhau theo sân (thứ tự: sân, giờ)."""
    if not data.slots:
        raise _web_error("E-WEB-1", "Chọn ít nhất 1 khung giờ.", 422)
    wanted = {(s.resource_code.strip().upper(), s.start_hour) for s in data.slots}
    if len(wanted) > MAX_SLOTS:
        raise _web_error("E-WEB-1", f"Mỗi lần đặt tối đa {MAX_SLOTS} khung giờ.", 422)
    if data.date < ctx.today:
        raise _past_day()
    codes = sorted({c for c, _ in wanted})
    resources = {
        r.code: r
        for r in await session.scalars(
            select(Resource).where(Resource.tenant_id == ctx.tenant.id, Resource.code.in_(codes))
        )
    }
    schedules = await schedules_of(session, ctx.tenant.id, [r.id for r in resources.values()])
    by_resource: dict[str, list[int]] = defaultdict(list)
    for code, hour in sorted(wanted):
        r = resources.get(code)
        sched = effective_on(schedules.get(r.id, []), data.date) if r else None
        if (
            r is None
            or not r.is_active
            or sched is None
            or not Hours.of(sched).sells(hour * 60, hour * 60 + 60)
            or ctx.at(data.date, hour * 60) <= ctx.now
        ):
            raise _slot_error(r.name if r else code, hour)
        by_resource[code].append(hour)
    ordered = sorted(resources.values(), key=lambda r: (r.sort_order, r.code))
    return [
        (r, a, b)
        for r in ordered
        if r.code in by_resource
        for a, b in ranges_of(by_resource[r.code])
    ]


def _pending_exists() -> AppError:
    return _web_error(
        "E-WEB-4",
        "Số điện thoại này đang có lượt giữ chỗ chưa thanh toán. "
        "Vui lòng thanh toán hoặc chờ hết hạn.",
        409,
    )


async def create_checkout(
    session: AsyncSession,
    tenant_id: int,
    data: CheckoutCreate,
    customer: CustomerSnapshot,
    hold_minutes: int,
) -> CheckoutCreated:
    """Giữ chỗ ``hold_minutes`` phút: mỗi dải = 1 hold mang mã ``BK-…`` + giá chốt (AC10, AC11)."""
    ctx = await context(session, tenant_id)
    ranges = await _validatedranges_of(session, ctx, data)
    priced = []
    for r, a, b in ranges:
        _, items = await price_slots(session, ctx.tenant, r, data.date, a, b)
        priced.append((r, a, b, items))

    await expire_holds(session)
    pending = await session.scalar(
        select(Checkout.id).where(
            Checkout.tenant_id == tenant_id,
            Checkout.customer_phone == customer.phone,
            Checkout.status == "pending",
        )
    )
    if pending is not None:
        raise _pending_exists()

    # Một mã đơn cho cả lượt; mỗi dải (sân, giờ liền nhau) mang mã con -NN (ADR-010)
    order_code = await next_code(session, tenant_id, ctx.code_prefix, data.date)
    codes = [child_code(order_code, seq) for seq in range(1, len(priced) + 1)]
    token = secrets.token_urlsafe(32)
    expires_at = ctx.now + timedelta(minutes=hold_minutes)
    total = sum(i.price for _, _, _, items in priced for i in items)
    checkout = Checkout(
        tenant_id=tenant_id,
        token_hash=token_hash(token),
        order_code=order_code,
        pay_ref=order_code.replace("-", ""),
        play_date=data.date,
        amount=total,
        paid_amount=0,
        note=(data.note or "").strip() or None,
        status="pending",
        expires_at=expires_at,
        **snapshot_values(customer),
    )
    try:
        async with session.begin_nested():
            session.add(checkout)
            await session.flush()
            for code, (r, a, b, items) in zip(codes, priced, strict=True):
                hold = Hold(
                    tenant_id=tenant_id,
                    kind="court",
                    checkout_id=checkout.id,
                    code=code,
                    amount=sum(i.price for i in items),
                    price_breakdown=[i.model_dump() for i in items],
                    seats=1,
                    expires_at=expires_at,
                    status="active",
                )
                session.add(hold)
                await session.flush()
                session.add(
                    Allocation(
                        tenant_id=tenant_id,
                        resource_id=r.id,
                        time_range=Range(
                            ctx.at(data.date, a * 60), ctx.at(data.date, b * 60), bounds="[)"
                        ),
                        kind="hold",
                        hold_id=hold.id,
                        owner_code=code,
                        active=True,
                    )
                )
            await session.flush()
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            conflicts = await conflicts_of(
                session, ctx, data.date, [(r, a, b) for r, a, b, _ in priced]
            )
            raise _web_error(
                "E-WEB-3",
                "Khung giờ vừa có người đặt. Vui lòng chọn khung khác.",
                409,
                conflicts=conflicts,
            ) from None
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
            "order_code": order_code,
            "codes": codes,
            "amount": total,
            "date": data.date.isoformat(),
        },
    )
    outbox.add_event(
        session,
        tenant_id,
        "checkout.created",
        {"pay_ref": checkout.pay_ref, "order_code": order_code, "codes": codes},
    )
    await session.flush()
    view = await checkout_view(session, ctx, checkout)
    return CheckoutCreated(**view.model_dump(), token=token)


async def checkout_view(session: AsyncSession, ctx: Ctx, checkout: Checkout) -> CheckoutView:
    if checkout.kind == "ticket":
        return await ticket_online.ticket_checkout_view(session, ctx, checkout)
    holds = list(
        await session.scalars(
            select(Hold).where(Hold.checkout_id == checkout.id).order_by(Hold.code)
        )
    )
    # Vị trí khung: allocation của hold (đang giữ / đã hết hạn) hoặc của booking (đã thanh toán)
    ranges: dict[str, tuple[Resource, datetime, datetime]] = {}
    rows = await session.execute(
        select(Allocation, Resource)
        .join(Resource, Resource.id == Allocation.resource_id)
        .where(Allocation.hold_id.in_([h.id for h in holds]))
    )
    for alloc, r in rows:
        ranges[alloc.owner_code] = (r, alloc.time_range.lower, alloc.time_range.upper)
    rows = await session.execute(
        select(Booking, Resource)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(Booking.checkout_id == checkout.id)
    )
    for b, r in rows:
        ranges[b.code] = (r, b.start_at, b.end_at)

    items = []
    for h in holds:
        if h.code not in ranges:  # bất biến: mỗi hold có allocation hoặc booking cùng mã
            raise RuntimeError(f"Checkout item {h.code} has no allocation or booking")
        r, start, end = ranges[h.code]
        s_min = ctx.minute_of(checkout.play_date, start)
        e_min = ctx.minute_of(checkout.play_date, end)
        items.append(
            CheckoutItem(
                code=h.code,
                resource_code=r.code,
                resource_name=r.name,
                play_date=checkout.play_date,
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                start_hour=s_min // 60,
                end_hour=e_min // 60,
                hours=(e_min - s_min) // 60,
                amount=h.amount or 0,
            )
        )
    items.sort(key=lambda i: i.code)
    return CheckoutView(
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
        items=items,
    )


def _not_found_checkout() -> AppError:
    return _web_error("E-WEB-6", "Không tìm thấy lượt thanh toán.", 404)


async def get_checkout(session: AsyncSession, tenant_id: int, token: str) -> CheckoutView:
    ctx = await context(session, tenant_id)
    if not token or len(token) > 100:
        raise _not_found_checkout()
    checkout = await session.scalar(
        select(Checkout).where(
            Checkout.tenant_id == tenant_id, Checkout.token_hash == token_hash(token)
        )
    )
    if checkout is None:
        raise _not_found_checkout()
    return await checkout_view(session, ctx, checkout)


async def count_pending_checkouts(session: AsyncSession, tenant_id: int) -> int:
    """Lượt thanh toán còn chờ (kể cả trong ân hạn) – chặn đổi tài khoản nhận tiền (T-012 AC6)."""
    return await session.scalar(
        select(func.count())
        .select_from(Checkout)
        .where(Checkout.tenant_id == tenant_id, Checkout.status == "pending")
    )


# ------------------------------------------------------------------ tra cứu (AC25–AC27)


def _same_phone(stored: str, given: str) -> bool:
    return secrets.compare_digest(stored.encode(), given.encode())


def _not_found_booking() -> AppError:
    return _web_error("E-WEB-7", "Không tìm thấy booking. Kiểm tra lại mã và số điện thoại.", 404)


def _order_status(statuses: list[str]) -> str:
    """Trạng thái chung của đơn: còn khối chưa thu -> unpaid; tất cả đã thu -> paid;
    còn lại (có khối Không thu được) -> uncollectible. Từng khối có trạng thái riêng."""
    if "unpaid" in statuses:
        return "unpaid"
    if all(s == "paid" for s in statuses):
        return "paid"
    return "uncollectible"


async def _lookup_order(
    session: AsyncSession, ctx: Ctx, order: BookingOrder, code: str
) -> LookupResult:
    blocks = await order_blocks(session, order.id)
    names = {
        r.id: r.name
        for r in await session.scalars(
            select(Resource).where(Resource.id.in_({b.resource_id for b in blocks}))
        )
    }
    items = []
    for b in blocks:
        s_min = ctx.minute_of(b.play_date, b.start_at)
        e_min = ctx.minute_of(b.play_date, b.end_at)
        items.append(
            LookupItem(
                code=b.code,
                resource_name=names[b.resource_id],
                start_time=to_hhmm(s_min),
                end_time=to_hhmm(e_min),
                hours=(e_min - s_min) // 60,
                amount=b.amount,
                status=b.payment_status,
                matched=b.code == code,
            )
        )
    paid = [b for b in blocks if b.payment_status == "paid"]
    methods = {b.payment_method for b in paid}
    return LookupResult(
        order_code=order.code,
        status=_order_status([b.payment_status for b in blocks]),
        play_date=order.play_date,
        hours=sum(i.hours for i in items),
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        amount=sum(b.amount for b in blocks),
        payment_method=methods.pop() if len(methods) == 1 else None,
        paid_at=max((b.paid_at for b in paid if b.paid_at), default=None),
        items=items,
    )


async def _lookup_checkout(
    session: AsyncSession, ctx: Ctx, checkout: Checkout, code: str
) -> LookupResult:
    view = await checkout_view(session, ctx, checkout)
    pending = checkout.status == "pending"
    status = "pending" if pending else "expired"
    return LookupResult(
        order_code=checkout.order_code,
        status=status,
        play_date=checkout.play_date,
        hours=sum(i.hours for i in view.items),
        customer_name=checkout.customer_name,
        customer_phone=checkout.customer_phone,
        amount=checkout.amount,
        payment_method=None,
        paid_at=None,
        items=[
            LookupItem(
                code=i.code,
                resource_name=i.resource_name,
                start_time=i.start_time,
                end_time=i.end_time,
                hours=i.hours,
                amount=i.amount,
                status=status,
                matched=i.code == code,
            )
            for i in view.items
        ],
        pending=LookupPending(
            expires_at=checkout.expires_at,
            server_now=ctx.now,
            pay_ref=checkout.pay_ref,
            amount=checkout.amount,
        )
        if pending
        else None,
    )


async def lookup(session: AsyncSession, tenant_id: int, code: str, phone: str) -> LookupResult:
    """Mã đơn **hoặc** mã con + SĐT (đã chuẩn hóa ở lớp gọi) -> cả đơn (T-019 AC3).

    Sai mã hay sai SĐT -> cùng một lỗi E-WEB-7. Lượt chờ thanh toán / hết hạn (chưa thành đơn)
    tra theo mã đơn của checkout hoặc mã con của giữ chỗ.
    """
    ctx = await context(session, tenant_id)
    order = await find_order(session, tenant_id, code)
    if order is not None:
        if not _same_phone(order.customer_phone, phone):
            raise _not_found_booking()
        return await _lookup_order(session, ctx, order, code)
    # Mã vé {mã sự kiện}-Vnn (T-023 AC21): vé mua online -> cả đơn vé; vé tại quầy -> một vé
    ticket = await ticket_online.find_ticket(session, tenant_id, code)
    if ticket is not None:
        if not _same_phone(ticket.customer_phone, phone):
            raise _not_found_booking()
        if ticket.checkout_id is None:
            return await ticket_online.lookup_counter_ticket(session, ctx, ticket)
        checkout = await session.get(Checkout, ticket.checkout_id)
        return await ticket_online.lookup_ticket_checkout(session, ctx, checkout)
    # Chưa thành đơn: lượt chờ thanh toán / hết hạn, theo mã đơn của lượt hoặc mã con của giữ chỗ
    order_code = order_of_child(code) or code
    checkout = await session.scalar(
        select(Checkout).where(Checkout.tenant_id == tenant_id, Checkout.order_code == order_code)
    )
    if checkout is None or not _same_phone(checkout.customer_phone, phone):
        raise _not_found_booking()
    if checkout.kind == "ticket":  # đơn vé: chỉ mã đơn (mã vé tra ở trên)
        if code != checkout.order_code:
            raise _not_found_booking()
        return await ticket_online.lookup_ticket_checkout(session, ctx, checkout)
    if code != checkout.order_code:  # mã con phải là một khối của lượt này
        hold = await session.scalar(
            select(Hold.id).where(Hold.checkout_id == checkout.id, Hold.code == code)
        )
        if hold is None:
            raise _not_found_booking()
    return await _lookup_checkout(session, ctx, checkout, code)


# ------------------------------------------------------------------ tiền về (AC21–AC23)


async def apply_online_payment(
    session: AsyncSession, tenant_id: int, data: OnlinePaymentIn
) -> OnlinePaymentResult:
    """Áp một giao dịch đã xác thực vào lượt thanh toán có ``pay_ref``.

    Khóa dòng checkout (``FOR UPDATE``) -> hai giao dịch đồng thời cộng dồn đúng, chỉ tạo booking
    một lần. Trong hạn (+ ân hạn) và đủ tiền -> mỗi hold thành booking cùng mã, allocation chuyển
    sang booking trong **cùng transaction** (không có khoảnh khắc khung trống).
    """
    checkout = await session.scalar(
        select(Checkout)
        .where(Checkout.tenant_id == tenant_id, Checkout.pay_ref == data.pay_ref.upper())
        .with_for_update()
    )
    if checkout is None:
        return OnlinePaymentResult(outcome="unmatched")
    in_time = data.transaction_at <= checkout.expires_at + grace()
    if checkout.status != "pending" or not in_time:
        # Đã thanh toán (tiền thừa) / hết hạn / quá ân hạn: không tạo booking, cần hoàn.
        # ``paid_amount`` chỉ ghi tiền đã áp vào lượt thanh toán – không cộng tiền cần hoàn.
        return OnlinePaymentResult(
            outcome="refund_needed",
            refund_amount=data.amount,
            checkout_closed_unpaid=checkout.status != "paid",
        )

    checkout.paid_amount += data.amount
    if checkout.paid_amount < checkout.amount:
        await session.flush()
        return OnlinePaymentResult(outcome="partial")
    if checkout.kind == "ticket":  # T-023: ghế đã giữ -> vé
        return await ticket_online.apply_ticket_payment(session, checkout, data)

    holds = list(
        await session.scalars(
            select(Hold).where(Hold.checkout_id == checkout.id).order_by(Hold.code)
        )
    )
    order = new_order(
        tenant_id,
        checkout.order_code,
        checkout.play_date,
        "online",
        {
            "customer_ref": checkout.customer_ref,
            "customer_kind": checkout.customer_kind,
            "customer_name": checkout.customer_name,
            "customer_phone": checkout.customer_phone,
            "member_code": checkout.member_code,
            "member_tier": checkout.member_tier,
        },
        ONLINE_ACTOR.label,
        checkout_id=checkout.id,
    )
    session.add(order)
    await session.flush()
    codes = []
    created: list[Booking] = []
    for n, hold in enumerate(holds, start=1):
        alloc = await session.scalar(select(Allocation).where(Allocation.hold_id == hold.id))
        if alloc is None:  # hold của checkout luôn có allocation (tạo cùng transaction)
            raise RuntimeError(f"Hold {hold.code} has no allocation")
        booking = Booking(
            tenant_id=tenant_id,
            order_id=order.id,
            seq=n,
            code=hold.code,
            source="online",
            resource_id=alloc.resource_id,
            play_date=checkout.play_date,
            start_at=alloc.time_range.lower,
            end_at=alloc.time_range.upper,
            amount=hold.amount or 0,
            price_breakdown=hold.price_breakdown or [],
            payment_status="paid",
            payment_method="online_transfer",
            paid_at=data.transaction_at,
            collected_by_type=ONLINE_ACTOR.type,
            collected_by_label=ONLINE_ACTOR.label,
            gateway_ref=f"{data.reference}:{n}",
            note=checkout.note,
            created_by_type=ONLINE_ACTOR.type,
            created_by_label=ONLINE_ACTOR.label,
            checkout_id=checkout.id,
            version=1,
            customer_ref=checkout.customer_ref,
            customer_kind=checkout.customer_kind,
            customer_name=checkout.customer_name,
            customer_phone=checkout.customer_phone,
            member_code=checkout.member_code,
            member_tier=checkout.member_tier,
        )
        session.add(booking)
        await session.flush()
        # Một câu UPDATE: đổi chủ hold -> booking (CHECK one_owner thỏa sau câu lệnh)
        await session.execute(
            update(Allocation)
            .where(Allocation.id == alloc.id)
            .values(kind="booking", hold_id=None, booking_id=booking.id, active=True)
        )
        hold.status = "converted"
        codes.append(hold.code)
        created.append(booking)
    checkout.status = "paid"
    checkout.paid_at = data.transaction_at
    # Thu tiền QR: tiền về xác nhận qua bên thứ 3 -> người làm là Hệ thống (SRS Lịch sử thao tác
    # BR-009); 1 lần thanh toán = 1 dòng dù nhiều booking
    audit(
        session,
        SYSTEM_ACTOR,
        "booking.online.paid",
        "checkout",
        checkout.pay_ref,
        audit_detail(
            order.code,
            checkout.customer_name,
            paid_changes("QR"),
            order_code=order.code,
            codes=codes,
            amount=checkout.amount,
            paid_amount=checkout.paid_amount,
        ),
    )
    for booking in created:
        await emit_created(session, tenant_id, order, booking)
    outbox.add_event(
        session,
        tenant_id,
        "booking.online_paid",
        {
            "order_code": order.code,
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

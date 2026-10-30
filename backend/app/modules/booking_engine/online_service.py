"""Đặt sân online (T-008, ADR-007): lịch cho khách, lượt thanh toán (checkout), tra cứu, tiền về.

Hàm ở đây **không commit** – lớp gọi sở hữu transaction. Chống trùng vẫn chỉ bằng exclusion
constraint của ``allocation`` (giữ chỗ và booking dùng chung): ``23P01`` -> ``E-WEB-3``.
"""

import hashlib
import secrets
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import SYSTEM_ACTOR, audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.booking_service import calendar, snapshot_values
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    Ctx,
    audit_actor,
    context,
    sqlstate,
)
from app.modules.booking_engine.config_service import price_slots
from app.modules.booking_engine.dto import (
    Actor,
    CheckoutCreate,
    CheckoutCreated,
    CheckoutItem,
    CheckoutView,
    CustomerSnapshot,
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
    Checkout,
    Hold,
    PriceRule,
    Resource,
)
from app.modules.booking_engine.pricing import day_type_of, slot_price, special_day_on
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

MAX_SLOTS = 16
ONLINE_ACTOR = Actor(type="web", id=None, label="Khách đặt online")
PENDING_PHONE_INDEX = "uq_checkout_pending_phone"


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _web_error(code: str, message: str, status: int, **extra) -> AppError:
    return AppError(code, message, status, **extra)


def _past_day() -> AppError:
    return _web_error("E-WEB-2", "Không đặt được ngày đã qua.", 422)


# ------------------------------------------------------------------ lịch cho khách (AC1–AC2)


async def _prices_for_day(session: AsyncSession, tenant_id: int, day: date) -> dict[int, dict]:
    """{resource_type_id: {"offpeak": giá, "peak": giá}} theo loại ngày."""
    special = await special_day_on(session, tenant_id, day)
    day_type = day_type_of(day, special is not None)
    prices: dict[int, dict] = defaultdict(dict)
    for p in await session.scalars(
        select(PriceRule).where(PriceRule.tenant_id == tenant_id, PriceRule.day_type == day_type)
    ):
        prices[p.resource_type_id][p.band] = p.price_per_hour
    return prices


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
    prices = await _prices_for_day(session, tenant_id, day)

    occupied: dict[tuple[str, int], PublicSlot] = {}
    for b in cal.blocks:
        for code in b.resource_codes:
            for h in range(b.start_hour, b.end_hour):
                if b.type == "session":
                    occupied[(code, h)] = PublicSlot(
                        start_hour=h, state="event", taken=b.taken, capacity=b.capacity
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
            needed = (
                {"peak" if hours.is_peak(m) else "offpeak" for m in (h * 60, h * 60 + 30)}
                if hours
                else set()
            )
            if started or h in cr.off_hours or hours is None or not needed <= type_prices.keys():
                slots.append(PublicSlot(start_hour=h, state="closed"))
                continue
            band, price = slot_price(hours, h * 60, type_prices)
            slots.append(PublicSlot(start_hour=h, state="free", price=price, band=band))
        out.append(PublicCalendarResource(code=r.code, name=r.name, slots=slots))
    return PublicCalendar(date=day, server_now=ctx.now, columns=cal.columns, resources=out)


# ------------------------------------------------------------------ lượt thanh toán (AC10–AC14)


def _ranges(hours: list[int]) -> list[tuple[int, int]]:
    """[19, 20, 22] -> [(19, 21), (22, 23)]."""
    result: list[list[int]] = []
    for h in sorted(set(hours)):
        if result and result[-1][1] == h:
            result[-1][1] = h + 1
        else:
            result.append([h, h + 1])
    return [(a, b) for a, b in result]


def _slot_error(name: str, hour: int) -> AppError:
    return _web_error(
        "E-WEB-2",
        f"Khung {name} {hour:02d}:00 không đặt được "
        "(đã qua, ngoài giờ mở cửa hoặc sân ngừng hoạt động).",
        422,
    )


async def _validated_ranges(
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
        (r, a, b) for r in ordered if r.code in by_resource for a, b in _ranges(by_resource[r.code])
    ]


async def _conflicts(
    session: AsyncSession, ctx: Ctx, day: date, ranges: list[tuple[Resource, int, int]]
) -> list[dict]:
    result = []
    for r, a, b in ranges:
        for h in range(a, b):
            taken = await session.scalar(
                select(Allocation.id)
                .where(
                    Allocation.tenant_id == ctx.tenant.id,
                    Allocation.resource_id == r.id,
                    Allocation.active.is_(True),
                    Allocation.time_range.overlaps(
                        Range(ctx.at(day, h * 60), ctx.at(day, h * 60 + 60), bounds="[)")
                    ),
                )
                .limit(1)
            )
            if taken is not None:
                result.append({"resource_code": r.code, "start_hour": h})
    return result


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
    ranges = await _validated_ranges(session, ctx, data)
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

    codes = [await next_code(session, tenant_id, ctx.code_prefix, data.date) for _ in priced]
    token = secrets.token_urlsafe(32)
    expires_at = ctx.now + timedelta(minutes=hold_minutes)
    total = sum(i.price for _, _, _, items in priced for i in items)
    checkout = Checkout(
        tenant_id=tenant_id,
        token_hash=token_hash(token),
        pay_ref=codes[0].replace("-", ""),
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
            conflicts = await _conflicts(
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
        {"codes": codes, "amount": total, "date": data.date.isoformat()},
    )
    outbox.add_event(
        session, tenant_id, "checkout.created", {"pay_ref": checkout.pay_ref, "codes": codes}
    )
    await session.flush()
    view = await checkout_view(session, ctx, checkout)
    return CheckoutCreated(**view.model_dump(), token=token)


async def checkout_view(session: AsyncSession, ctx: Ctx, checkout: Checkout) -> CheckoutView:
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


async def lookup(session: AsyncSession, tenant_id: int, code: str, phone: str) -> LookupResult:
    """Mã + SĐT (đã chuẩn hóa ở lớp gọi). Sai mã hay sai SĐT -> cùng một lỗi E-WEB-7."""
    ctx = await context(session, tenant_id)
    row = (
        await session.execute(
            select(Booking, Resource)
            .join(Resource, Resource.id == Booking.resource_id)
            .where(Booking.tenant_id == tenant_id, Booking.code == code)
        )
    ).first()
    if row is not None:
        b, r = row
        if not _same_phone(b.customer_phone, phone):
            raise _not_found_booking()
        s_min, e_min = ctx.minute_of(b.play_date, b.start_at), ctx.minute_of(b.play_date, b.end_at)
        return LookupResult(
            code=b.code,
            status=b.payment_status,
            resource_name=r.name,
            play_date=b.play_date,
            start_time=to_hhmm(s_min),
            end_time=to_hhmm(e_min),
            hours=(e_min - s_min) // 60,
            customer_name=b.customer_name,
            customer_phone=b.customer_phone,
            amount=b.amount,
            payment_method=b.payment_method,
            paid_at=b.paid_at,
        )
    row = (
        await session.execute(
            select(Hold, Checkout)
            .join(Checkout, Checkout.id == Hold.checkout_id)
            .where(Hold.tenant_id == tenant_id, Hold.code == code)
        )
    ).first()
    if row is None:
        raise _not_found_booking()
    hold, checkout = row
    if not _same_phone(checkout.customer_phone, phone):
        raise _not_found_booking()
    view = await checkout_view(session, ctx, checkout)
    item = next(i for i in view.items if i.code == code)
    pending = checkout.status == "pending" and hold.status == "active"
    return LookupResult(
        code=code,
        status="pending" if pending else "expired",
        resource_name=item.resource_name,
        play_date=item.play_date,
        start_time=item.start_time,
        end_time=item.end_time,
        hours=item.hours,
        customer_name=checkout.customer_name,
        customer_phone=checkout.customer_phone,
        amount=item.amount,
        payment_method=None,
        paid_at=None,
        pending=LookupPending(
            expires_at=checkout.expires_at,
            server_now=ctx.now,
            pay_ref=checkout.pay_ref,
            amount=checkout.amount,
        )
        if pending
        else None,
    )


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

    holds = list(
        await session.scalars(
            select(Hold).where(Hold.checkout_id == checkout.id).order_by(Hold.code)
        )
    )
    codes = []
    for n, hold in enumerate(holds, start=1):
        alloc = await session.scalar(select(Allocation).where(Allocation.hold_id == hold.id))
        if alloc is None:  # hold của checkout luôn có allocation (tạo cùng transaction)
            raise RuntimeError(f"Hold {hold.code} has no allocation")
        booking = Booking(
            tenant_id=tenant_id,
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
            ", ".join(codes),
            checkout.customer_name,
            paid_changes("QR"),
            codes=codes,
            amount=checkout.amount,
            paid_amount=checkout.paid_amount,
        ),
    )
    outbox.add_event(
        session,
        tenant_id,
        "booking.online_paid",
        {
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

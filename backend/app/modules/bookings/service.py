import secrets
import string
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import settings
from app.core.errors import BadRequest, Conflict, Forbidden, NotFound
from app.modules.auth.models import Role, User
from app.modules.bookings.models import (
    ACTIVE_STATUSES,
    Booking,
    BookingSlot,
    BookingSource,
    BookingStatus,
)
from app.modules.bookings.schemas import (
    AvailabilityOut,
    BusyRange,
    CourtAvailability,
    QuoteOut,
    SlotIn,
    SlotOut,
)
from app.modules.courts import service as courts_service

EXCLUSION_VIOLATION = "23P01"


def _now() -> datetime:
    return datetime.now(UTC)


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "CL" + "".join(secrets.choice(alphabet) for _ in range(8))


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=settings.tz)
    return start, start + timedelta(days=1)


def validate_slot(slot: SlotIn, now: datetime, *, allow_past: bool = False) -> None:
    start = slot.start.astimezone(settings.tz)
    end = slot.end.astimezone(settings.tz)
    if start >= end:
        raise BadRequest("Giờ kết thúc phải sau giờ bắt đầu")
    for t in (start, end):
        if t.second or t.microsecond or t.minute % settings.SLOT_MINUTES:
            raise BadRequest(f"Thời gian phải theo bước {settings.SLOT_MINUTES} phút")
    if (end - start) < timedelta(minutes=settings.MIN_BOOKING_MINUTES):
        raise BadRequest(f"Đặt tối thiểu {settings.MIN_BOOKING_MINUTES} phút")
    day_start = datetime.combine(start.date(), time.min, tzinfo=settings.tz)
    open_at = datetime.combine(start.date(), settings.OPEN_TIME, tzinfo=settings.tz)
    # CLOSE_TIME = 00:00 nghĩa là mở tới nửa đêm
    close_at = (
        day_start + timedelta(days=1)
        if settings.CLOSE_TIME == time.min
        else datetime.combine(start.date(), settings.CLOSE_TIME, tzinfo=settings.tz)
    )
    if start < open_at or end > close_at:
        raise BadRequest(f"Sân mở cửa {settings.OPEN_TIME:%H:%M} - {settings.CLOSE_TIME:%H:%M}")
    if not allow_past and start <= now:
        raise BadRequest("Không thể đặt khung giờ đã qua")
    if start.date() > (now.astimezone(settings.tz).date() + timedelta(settings.MAX_ADVANCE_DAYS)):
        raise BadRequest(f"Chỉ được đặt trước tối đa {settings.MAX_ADVANCE_DAYS} ngày")


async def quote(
    session: AsyncSession, slots: list[SlotIn], *, allow_past: bool = False
) -> QuoteOut:
    now = _now()
    for s in slots:
        validate_slot(s, now, allow_past=allow_past)
    court_ids = {s.court_id for s in slots}
    courts = await courts_service.get_active_courts_by_ids(session, court_ids)
    missing = court_ids - courts.keys()
    if missing:
        raise BadRequest(f"Sân không tồn tại hoặc đang tạm ngưng: {sorted(missing)}")
    calc = courts_service.PriceCalculator(await courts_service.list_price_rules(session))
    out = [
        SlotOut(
            court_id=s.court_id,
            start=s.start,
            end=s.end,
            price=calc.price(s.court_id, s.start, s.end),
        )
        for s in slots
    ]
    return QuoteOut(total_amount=sum(s.price for s in out), slots=out)


async def create_booking(
    session: AsyncSession,
    slots: list[SlotIn],
    *,
    customer_name: str,
    customer_phone: str | None,
    customer_id: int | None,
    created_by: User,
    source: BookingSource,
    confirm: bool = False,
    note: str | None = None,
) -> Booking:
    q = await quote(session, slots)
    status = BookingStatus.CONFIRMED if confirm else BookingStatus.PENDING
    # Đơn online chờ thanh toán sẽ hết hạn; đơn giữ chỗ tại quầy do nhân viên tự xử lý
    expires_at = (
        _now() + timedelta(minutes=settings.HOLD_MINUTES)
        if status == BookingStatus.PENDING and source == BookingSource.ONLINE
        else None
    )
    booking = Booking(
        code=_generate_code(),
        customer_id=customer_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        status=status,
        source=source,
        total_amount=q.total_amount,
        note=note,
        expires_at=expires_at,
        created_by_id=created_by.id,
        slots=[
            BookingSlot(
                court_id=s.court_id,
                time_range=Range(s.start, s.end, bounds="[)"),
                price=s.price,
                is_active=True,
            )
            for s in q.slots
        ],
    )
    session.add(booking)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        if getattr(e.orig, "sqlstate", None) == EXCLUSION_VIOLATION:
            raise Conflict("Khung giờ đã có người đặt, vui lòng chọn giờ khác") from None
        raise
    await session.refresh(booking)
    await events.publish(
        events.BOOKING_CONFIRMED if confirm else events.BOOKING_CREATED,
        {"booking_id": booking.id},
    )
    return booking


async def get_booking(session: AsyncSession, booking_id: int, *, lock: bool = False) -> Booking:
    stmt = select(Booking).where(Booking.id == booking_id)
    if lock:
        stmt = stmt.with_for_update()
    booking = await session.scalar(stmt)
    if not booking:
        raise NotFound("Không tìm thấy đơn đặt sân")
    return booking


def ensure_can_view(booking: Booking, user: User) -> None:
    if user.role in (Role.ADMIN, Role.STAFF):
        return
    if booking.customer_id != user.id:
        raise NotFound("Không tìm thấy đơn đặt sân")


async def _close(session: AsyncSession, booking: Booking, status: BookingStatus) -> None:
    booking.status = status
    booking.expires_at = None
    for slot in booking.slots:
        slot.is_active = False
    await session.commit()


async def cancel_booking(session: AsyncSession, booking_id: int, user: User) -> Booking:
    booking = await get_booking(session, booking_id, lock=True)
    ensure_can_view(booking, user)
    if booking.status not in ACTIVE_STATUSES:
        raise BadRequest("Đơn không thể hủy ở trạng thái hiện tại")
    is_staff = user.role in (Role.ADMIN, Role.STAFF)
    if not is_staff and booking.status != BookingStatus.PENDING:
        # Đơn đã thanh toán cần liên hệ sân để xử lý hoàn tiền
        raise Forbidden("Đơn đã xác nhận, vui lòng liên hệ sân để hủy")
    await _close(session, booking, BookingStatus.CANCELLED)
    await events.publish(events.BOOKING_CANCELLED, {"booking_id": booking.id})
    return booking


def mark_confirmed(booking: Booking) -> None:
    """Chuyển đơn sang CONFIRMED, KHÔNG commit (để gộp chung transaction với caller)."""
    if booking.status != BookingStatus.PENDING:
        raise BadRequest("Chỉ xác nhận được đơn đang chờ")
    booking.status = BookingStatus.CONFIRMED
    booking.expires_at = None


async def confirm_booking(session: AsyncSession, booking_id: int) -> Booking:
    booking = await get_booking(session, booking_id, lock=True)
    if booking.status == BookingStatus.CONFIRMED:
        return booking
    mark_confirmed(booking)
    await session.commit()
    await events.publish(events.BOOKING_CONFIRMED, {"booking_id": booking.id})
    return booking


async def expire_pending(session: AsyncSession) -> int:
    """Giải phóng các đơn giữ chỗ quá hạn. Được worker gọi định kỳ."""
    ids = list(
        await session.scalars(
            update(Booking)
            .where(Booking.status == BookingStatus.PENDING, Booking.expires_at < _now())
            .values(status=BookingStatus.EXPIRED, expires_at=None)
            .returning(Booking.id)
        )
    )
    if ids:
        await session.execute(
            update(BookingSlot).where(BookingSlot.booking_id.in_(ids)).values(is_active=False)
        )
    await session.commit()
    return len(ids)


async def availability(session: AsyncSession, day: date) -> AvailabilityOut:
    day_start, day_end = _day_bounds(day)
    courts = await courts_service.list_courts(session)
    rows = await session.scalars(
        select(BookingSlot).where(
            BookingSlot.is_active.is_(True),
            BookingSlot.time_range.overlaps(Range(day_start, day_end, bounds="[)")),
        )
    )
    busy: dict[int, list[BusyRange]] = {c.id: [] for c in courts}
    for slot in rows:
        if slot.court_id in busy:
            busy[slot.court_id].append(BusyRange(start=slot.start, end=slot.end))
    return AvailabilityOut(
        date=day,
        open_time=settings.OPEN_TIME,
        close_time=settings.CLOSE_TIME,
        slot_minutes=settings.SLOT_MINUTES,
        courts=[
            CourtAvailability(
                court_id=c.id, name=c.name, busy=sorted(busy[c.id], key=lambda b: b.start)
            )
            for c in courts
        ],
    )


async def list_bookings(
    session: AsyncSession,
    *,
    customer_id: int | None = None,
    day: date | None = None,
    status: BookingStatus | None = None,
    limit: int = 100,
) -> list[Booking]:
    stmt = select(Booking).order_by(Booking.created_at.desc()).limit(limit)
    if customer_id is not None:
        stmt = stmt.where(Booking.customer_id == customer_id)
    if status is not None:
        stmt = stmt.where(Booking.status == status)
    if day is not None:
        day_start, day_end = _day_bounds(day)
        stmt = stmt.where(
            Booking.slots.any(
                BookingSlot.time_range.overlaps(Range(day_start, day_end, bounds="[)"))
            )
        )
    return list((await session.scalars(stmt)).all())

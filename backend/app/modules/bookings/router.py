from datetime import date

from fastapi import APIRouter, Query, status

from app.modules.auth.deps import CurrentUser, SessionDep, StaffUser
from app.modules.bookings import service
from app.modules.bookings.models import BookingSource, BookingStatus
from app.modules.bookings.schemas import (
    AvailabilityOut,
    BookingCreateIn,
    BookingOut,
    CounterBookingIn,
    QuoteOut,
    SlotIn,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("/availability", response_model=AvailabilityOut)
async def availability(session: SessionDep, day: date = Query(alias="date")):
    return await service.availability(session, day)


@router.post("/quote", response_model=QuoteOut)
async def quote(slots: list[SlotIn], session: SessionDep):
    return await service.quote(session, slots)


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(data: BookingCreateIn, user: CurrentUser, session: SessionDep):
    return await service.create_booking(
        session,
        data.slots,
        customer_name=user.full_name,
        customer_phone=user.phone,
        customer_id=user.id,
        created_by=user,
        source=BookingSource.ONLINE,
        note=data.note,
    )


@router.get("/me", response_model=list[BookingOut])
async def my_bookings(user: CurrentUser, session: SessionDep):
    return await service.list_bookings(session, customer_id=user.id)


@router.get("/{booking_id}", response_model=BookingOut)
async def get_booking(booking_id: int, user: CurrentUser, session: SessionDep):
    booking = await service.get_booking(session, booking_id)
    service.ensure_can_view(booking, user)
    return booking


@router.post("/{booking_id}/cancel", response_model=BookingOut)
async def cancel_booking(booking_id: int, user: CurrentUser, session: SessionDep):
    return await service.cancel_booking(session, booking_id, user)


# --- Nhân viên / chủ sân ---
admin_router = APIRouter(prefix="/admin/bookings", tags=["admin: bookings"])


@admin_router.get("", response_model=list[BookingOut])
async def admin_list_bookings(
    _: StaffUser,
    session: SessionDep,
    day: date | None = Query(default=None, alias="date"),
    status: BookingStatus | None = None,
):
    return await service.list_bookings(session, day=day, status=status, limit=500)


@admin_router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_counter_booking(data: CounterBookingIn, staff: StaffUser, session: SessionDep):
    return await service.create_booking(
        session,
        data.slots,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_id=data.customer_id,
        created_by=staff,
        source=BookingSource.COUNTER,
        confirm=data.confirm,
        note=data.note,
    )


@admin_router.post("/{booking_id}/confirm", response_model=BookingOut)
async def confirm_booking(booking_id: int, _: StaffUser, session: SessionDep):
    return await service.confirm_booking(session, booking_id)

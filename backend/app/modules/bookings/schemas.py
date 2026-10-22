from datetime import date, datetime, time

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.modules.bookings.models import BookingSource, BookingStatus


class SlotIn(BaseModel):
    court_id: int
    start: AwareDatetime
    end: AwareDatetime


class BookingCreateIn(BaseModel):
    slots: list[SlotIn] = Field(min_length=1, max_length=10)
    note: str | None = Field(default=None, max_length=1000)


class CounterBookingIn(BookingCreateIn):
    """Nhân viên đặt hộ khách tại quầy / qua điện thoại."""

    customer_name: str = Field(min_length=1, max_length=255)
    customer_phone: str | None = Field(default=None, max_length=20)
    customer_id: int | None = None
    confirm: bool = True  # False = chỉ giữ chỗ, chưa xác nhận


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    court_id: int
    start: datetime
    end: datetime
    price: int


class QuoteOut(BaseModel):
    total_amount: int
    slots: list[SlotOut]


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    status: BookingStatus
    source: BookingSource
    customer_id: int | None
    customer_name: str
    customer_phone: str | None
    total_amount: int
    note: str | None
    expires_at: datetime | None
    created_at: datetime
    slots: list[SlotOut]


class BusyRange(BaseModel):
    start: datetime
    end: datetime


class CourtAvailability(BaseModel):
    court_id: int
    name: str
    busy: list[BusyRange]


class AvailabilityOut(BaseModel):
    date: date
    open_time: time
    close_time: time
    slot_minutes: int
    courts: list[CourtAvailability]

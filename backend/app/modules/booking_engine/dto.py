"""DTO vào/ra của booking engine.

Dùng chung cho ``api.py`` (gọi trong tiến trình) và ``router.py`` (HTTP).

Không lộ ORM, không lộ id nội bộ của tài nguyên (dùng ``code``).
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.schemas import StrictIn

# "HH:MM", bội 30 phút; "24:00" = nửa đêm cuối ngày (chỉ có nghĩa với giờ đóng cửa)
HHMM = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):(00|30)|24:00)$")]
DayType = Literal["weekday", "weekend", "holiday"]
Band = Literal["offpeak", "peak"]
ActorType = Literal["admin", "staff", "customer", "system", "web"]


class Actor(BaseModel):
    """Người thao tác do lớp gọi (router/BFF) truyền vào – engine không biết về đăng nhập."""

    type: ActorType
    id: int | None = None
    label: str


# ---------- Tài nguyên (sân) ----------


class ScheduleOut(BaseModel):
    effective_from: dt.date
    open_time: str
    close_time: str
    peak_bands: list[tuple[str, str]]


class ResourceTypeOut(BaseModel):
    code: str
    name: str


class ResourceOut(BaseModel):
    code: str
    name: str
    resource_type_code: str
    resource_type_name: str
    sort_order: int
    is_active: bool
    version: int
    schedule: ScheduleOut | None = Field(description="Lịch đang áp dụng hôm nay")
    pending_schedule: ScheduleOut | None = Field(
        description="Lịch đã lưu, áp dụng từ ngày sau (effective_from > hôm nay)"
    )


class ResourceList(BaseModel):
    items: list[ResourceOut]
    resource_types: list[ResourceTypeOut]


class ResourceCreate(StrictIn):
    name: str = Field(max_length=200)
    resource_type_code: str = Field(max_length=20)
    open_time: HHMM
    close_time: HHMM
    peak_bands: list[tuple[HHMM, HHMM]] = Field(default_factory=list, max_length=12)


class ResourceUpdate(StrictIn):
    """Chỉ gửi trường muốn đổi. Giờ / cao điểm áp dụng từ ngày mai (D4)."""

    version: int
    name: str | None = Field(default=None, max_length=200)
    resource_type_code: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    open_time: HHMM | None = None
    close_time: HHMM | None = None
    peak_bands: list[tuple[HHMM, HHMM]] | None = Field(default=None, max_length=12)


class OccupiedSlot(BaseModel):
    """Một chỗ chiếm (booking / sự kiện / giữ chỗ) – dùng trong lỗi E-CFG-3 / E-CFG-4."""

    code: str | None
    date: dt.date
    start_time: str
    end_time: str


# ---------- Bảng giá ----------


class PriceCellIn(StrictIn):
    resource_type_code: str = Field(max_length=20)
    day_type: DayType
    band: Band
    price_per_hour: int = Field(strict=True)


class PriceCellOut(BaseModel):
    resource_type_code: str
    day_type: DayType
    band: Band
    price_per_hour: int


class PriceTable(BaseModel):
    version: int
    updated_at: dt.datetime | None
    updated_by: str | None
    resource_types: list[ResourceTypeOut]
    prices: list[PriceCellOut]


class PriceTableUpdate(StrictIn):
    version: int
    prices: list[PriceCellIn] = Field(max_length=200)


# ---------- Ngày Lễ / Tết ----------


class SpecialDayIn(StrictIn):
    date_from: dt.date
    date_to: dt.date | None = Field(default=None, description="Bỏ trống = 1 ngày")
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_range(self) -> "SpecialDayIn":
        if self.date_to is not None:
            if self.date_to < self.date_from:
                raise ValueError("Đến ngày phải bằng hoặc sau Từ ngày.")
            if self.date_to.year != self.date_from.year:
                raise ValueError("Từ ngày và Đến ngày phải trong cùng một năm.")
        return self


class SpecialDayOut(BaseModel):
    id: int
    date_from: dt.date
    date_to: dt.date
    name: str
    day_type: Literal["holiday"]


# ---------- Báo giá ----------


class QuoteIn(StrictIn):
    resource_code: str = Field(max_length=10)
    date: dt.date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)


class QuoteItem(BaseModel):
    start_time: str
    end_time: str
    band: Literal["offpeak", "partial", "peak"]
    label: str  # "Thấp điểm" / "Một phần cao điểm" / "Cao điểm"
    price: int


class QuoteOut(BaseModel):
    resource_code: str
    resource_name: str
    date: dt.date
    day_type: DayType
    price_version: int
    items: list[QuoteItem]
    total_amount: int


# ---------- Khách (snapshot do server dựng) ----------

CustomerKind = Literal["member", "temp"]
PaymentStatus = Literal["unpaid", "paid", "uncollectible"]
PaymentMethod = Literal["cash", "transfer", "online_transfer"]
Source = Literal["counter", "online"]


class CustomerSnapshot(BaseModel):
    """Khách tại thời điểm đặt – lớp gọi dựng từ hồ sơ của nó; client không bao giờ gửi."""

    ref_id: str
    kind: CustomerKind
    display_name: str
    phone: str
    member_code: str | None = None
    tier: str | None = None


class CustomerStats(BaseModel):
    """Thống kê đặt sân của một ``customer_ref`` (không tính vé)."""

    bookings: int
    minutes: int


class CustomerBookingRow(BaseModel):
    code: str
    play_date: dt.date
    start_time: str
    end_time: str
    resource_name: str
    amount: int
    payment_status: PaymentStatus


# ---------- Lịch ngày ----------


class CalendarResource(BaseModel):
    code: str
    name: str
    type: str
    is_active: bool
    off_hours: list[int] = Field(description="Giờ bắt đầu các ô Xám (không bán) của sân này")


class CalendarBlock(BaseModel):
    type: Literal["booking", "session", "hold"]
    code: str | None
    resource_codes: list[str]
    start_time: str
    end_time: str
    start_hour: int
    end_hour: int
    # booking
    payment_status: PaymentStatus | None = None
    customer_name: str | None = None
    phone_masked: str | None = None
    source: Source | None = None
    # session
    name: str | None = None
    taken: int | None = None
    capacity: int | None = None
    is_full: bool | None = None
    unpaid_tickets: int | None = None
    # hold
    expires_at: dt.datetime | None = None


class CalendarCan(BaseModel):
    counter_book: bool
    create_session: bool


class CalendarOut(BaseModel):
    date: dt.date
    now: dt.datetime
    is_past: bool = Field(description="Ngày đã qua – chỉ xem")
    columns: list[int] = Field(description="Giờ bắt đầu từng cột (khung 1 giờ)")
    resources: list[CalendarResource]
    blocks: list[CalendarBlock]
    unpaid_count: int
    can: CalendarCan


class SearchResult(BaseModel):
    kind: Literal["booking", "ticket", "session"]
    code: str
    play_date: dt.date


# ---------- Booking / vé ----------


class CounterBookingIn(StrictIn):
    resource_code: str = Field(max_length=10)
    date: dt.date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)


class ItemCustomer(BaseModel):
    name: str
    phone_masked: str | None
    profile_label: str = Field(description='"Hồ sơ tạm" hoặc "Hội viên (HV0087 · Hạng Khá)"')
    kind: CustomerKind
    member_code: str | None
    tier: str | None


class ItemSessionRef(BaseModel):
    code: str
    name: str


class ItemSchedule(BaseModel):
    resource_codes: list[str]
    resource_names: list[str]
    play_date: dt.date
    start_time: str
    end_time: str
    session: ItemSessionRef | None = None


class ItemPayment(BaseModel):
    amount: int
    payment_status: PaymentStatus
    payment_method: PaymentMethod | None = None
    paid_at: dt.datetime | None = None
    collected_by: str | None = None
    uncollectible_reason: str | None = None
    marked_by: str | None = None
    marked_at: dt.datetime | None = None


class ItemOut(BaseModel):
    """Thông tin booking / vé (SRS IV.5) – không SĐT đầy đủ, không id nội bộ."""

    kind: Literal["booking", "ticket"]
    code: str
    version: int
    source: Source
    customer: ItemCustomer
    schedule: ItemSchedule
    payment: ItemPayment
    price_breakdown: list[QuoteItem] = Field(default_factory=list)
    note: str | None = None
    created_by: str
    created_at: dt.datetime
    actions: list[Literal["collect", "uncollectible"]]


class CollectIn(StrictIn):
    method: Literal["cash", "transfer"]
    version: int


class UncollectibleIn(StrictIn):
    reason: str = Field(default="", max_length=500)
    version: int


# ---------- Sự kiện ----------


class SessionCreate(StrictIn):
    resource_codes: list[str] = Field(min_length=1, max_length=50)
    date: dt.date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    # Kiểm ở service để trả mã SRS (E-001, E-009, E-013)
    name: str = Field(default="", max_length=300)
    capacity: int | float | None = None
    ticket_price: int | float | None = None


class SessionDelete(StrictIn):
    version: int


class ResourceRef(BaseModel):
    code: str
    name: str


class SessionTicket(BaseModel):
    code: str
    customer_name: str
    phone_masked: str | None
    source: Source
    payment_status: PaymentStatus
    amount: int
    created_at: dt.datetime


class SessionHold(BaseModel):
    seats: int
    expires_at: dt.datetime


class SessionCan(BaseModel):
    # "register" trùng tên thuộc tính của BaseModel -> dùng alias, JSON vẫn là "register"
    model_config = ConfigDict(populate_by_name=True)

    can_register: bool = Field(alias="register")
    delete: bool


class SessionOut(BaseModel):
    code: str
    name: str
    status: Literal["active", "deleted"]
    play_date: dt.date
    start_time: str
    end_time: str
    resources: list[ResourceRef]
    ticket_price: int
    capacity: int
    taken: int
    is_full: bool
    created_by: str
    created_at: dt.datetime
    version: int
    tickets: list[SessionTicket]
    active_holds: list[SessionHold]
    can: SessionCan


# ---------- Lịch sử giao dịch ----------


class TransactionsQuery(BaseModel):
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    resource: str | None = None
    status: PaymentStatus | None = None
    method: Literal["cash", "transfer"] | None = None
    q: str | None = None
    page: int = 1


class TransactionRow(BaseModel):
    kind: Literal["booking", "ticket"]
    code: str
    play_date: dt.date
    start_time: str
    end_time: str
    resource_codes: list[str]
    customer_name: str
    phone_masked: str | None
    amount: int
    payment_status: PaymentStatus
    payment_method: PaymentMethod | None
    source: Source


class TransactionCard(BaseModel):
    amount: int
    count: int


class TransactionCards(BaseModel):
    paid: TransactionCard
    unpaid: TransactionCard
    uncollectible: TransactionCard


class TransactionsOut(BaseModel):
    date_from: dt.date
    date_to: dt.date
    rows: list[TransactionRow]
    page: int
    page_size: int
    total: int
    cards: TransactionCards


# ---------- Bảng giá công khai (trang chủ) ----------


class PublicResourceType(BaseModel):
    code: str
    name: str
    resource_count: int


class PublicPeakBands(BaseModel):
    resource_type_code: str
    bands: list[tuple[str, str]]


class PublicOpeningHours(BaseModel):
    earliest_open: str | None
    latest_close: str | None


class PublicSpecialDay(BaseModel):
    date_from: dt.date
    date_to: dt.date
    name: str


class PublicPrices(BaseModel):
    """Bản rút gọn cho trang public – không lộ version, người sửa, id nội bộ."""

    currency: Literal["VND"] = "VND"
    unit: Literal["hour"] = "hour"
    updated_at: dt.datetime | None
    resource_types: list[PublicResourceType]
    prices: list[PriceCellOut]
    opening_hours: PublicOpeningHours
    peak_bands: list[PublicPeakBands]
    special_days: list[PublicSpecialDay]


# ---------- Đặt online (T-008, ADR-007) ----------


class PublicSlot(BaseModel):
    start_hour: int
    state: Literal["free", "booked", "event", "closed"]
    price: int | None = None
    band: Literal["offpeak", "partial", "peak"] | None = None
    taken: int | None = None
    capacity: int | None = None


class PublicCalendarResource(BaseModel):
    code: str
    name: str
    slots: list[PublicSlot]


class PublicCalendar(BaseModel):
    """Lịch cho khách: không tên, SĐT, mã của ai."""

    date: dt.date
    server_now: dt.datetime
    columns: list[int]
    resources: list[PublicCalendarResource]


class OnlineSlotIn(StrictIn):
    resource_code: str = Field(max_length=10)
    start_hour: int = Field(ge=0, le=23)


class CheckoutCreate(StrictIn):
    """Phần engine của lượt đặt online – khách (snapshot) do lớp gọi dựng."""

    date: dt.date
    slots: list[OnlineSlotIn] = Field(max_length=200)
    note: str | None = Field(default=None, max_length=200)


class CheckoutItem(BaseModel):
    code: str
    resource_code: str
    resource_name: str
    play_date: dt.date
    start_time: str
    end_time: str
    start_hour: int
    end_hour: int
    hours: int
    amount: int


class CheckoutView(BaseModel):
    """Trạng thái lượt thanh toán (engine) – lớp gọi che SĐT và thêm thông tin ngân hàng."""

    status: Literal["pending", "paid", "expired"]
    expires_at: dt.datetime
    server_now: dt.datetime
    amount: int
    paid_amount: int
    paid_at: dt.datetime | None
    pay_ref: str
    customer_name: str
    customer_phone: str
    play_date: dt.date
    items: list[CheckoutItem]


class CheckoutCreated(CheckoutView):
    token: str = Field(description="Chuỗi truy cập – chỉ trả ở lần tạo; DB chỉ lưu SHA-256")


class LookupPending(BaseModel):
    expires_at: dt.datetime
    server_now: dt.datetime
    pay_ref: str
    amount: int


class LookupResult(BaseModel):
    code: str
    status: Literal["paid", "unpaid", "uncollectible", "pending", "expired"]
    resource_name: str
    play_date: dt.date
    start_time: str
    end_time: str
    hours: int
    customer_name: str
    customer_phone: str
    amount: int
    payment_method: PaymentMethod | None
    paid_at: dt.datetime | None
    pending: LookupPending | None = None


class OnlinePaymentIn(BaseModel):
    pay_ref: str
    amount: int
    transaction_at: dt.datetime
    reference: str = Field(description="Mã giao dịch cổng (vd 'sepay:123') – gắn vào gateway_ref")


class OnlinePaymentResult(BaseModel):
    outcome: Literal["applied", "partial", "refund_needed", "unmatched"]
    refund_amount: int = 0
    booking_codes: list[str] = Field(default_factory=list)
    checkout_closed_unpaid: bool = Field(
        default=False,
        description="Lượt thanh toán hết hạn khi chưa đủ tiền -> tiền đã nhận cần hoàn",
    )

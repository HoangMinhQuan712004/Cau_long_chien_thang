"""DTO vào/ra của booking engine.

Dùng chung cho ``api.py`` (gọi trong tiến trình) và ``router.py`` (HTTP).

Không lộ ORM, không lộ id nội bộ của tài nguyên (dùng ``code``).
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.schemas import StrictIn
from app.modules.booking_engine.report_dto import (  # noqa: F401 – mặt tiền DTO báo cáo
    CourtRevenue,
    DailyRevenue,
    OccupancyCell,
    OccupancyGrid,
    ReportFigures,
    RevenueTotals,
)

# "HH:MM"; "24:00" = nửa đêm cuối ngày (chỉ có nghĩa với giờ đóng cửa). Vẫn nhận :30 ở đây: form gửi
# lại nguyên giá trị cũ không được lỗi; giá trị MỚI phải tròn giờ, xem ``ensure_whole_hours``
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
    """Một chỗ chiếm (booking / sự kiện / giữ chỗ) – dùng trong lỗi E-CFG-3 / 4 / 11."""

    code: str | None
    date: dt.date
    start_time: str
    end_time: str
    kind: Literal["booking", "session", "hold"] | None = None


class MoveIn(StrictIn):
    """Đổi sân: cùng ngày, cùng giờ; giá + tiền + mã giữ nguyên."""

    resource_code: str = Field(max_length=10)
    version: int


class MoveTarget(BaseModel):
    code: str
    name: str
    type_name: str = Field(description="Loại sân – đổi khác loại vẫn giữ giá đã chốt")


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
PaymentStatus = Literal["unpaid", "paid", "uncollectible", "cancelled"]
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

    bookings: int = Field(description="Số lượt, không tính lượt đã hủy (T-051)")
    minutes: int
    listed: int = Field(default=0, description="Số dòng lịch sử, gồm cả lượt đã hủy")


class PaidItem(BaseModel):
    """Khoản đã thanh toán của một khách (khu hội viên, T-018) – không SĐT."""

    kind: Literal["booking", "ticket"]
    code: str = Field(description="Booking: mã con (id nội bộ) · vé: mã vé")
    order_code: str | None = Field(description="Booking: mã đơn – mã khách thấy (ADR-010)")
    event_name: str | None
    resource_names: list[str]
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    amount: int
    paid_at: dt.datetime
    payment_method: PaymentMethod | None
    channel: Source
    cancelled: bool = Field(default=False, description="Đã từng thu rồi bị hủy (T-051)")
    refund_amount: int = 0


class UpcomingBooking(BaseModel):
    """Khối booking chưa kết thúc của một khách (Tổng quan khu hội viên, T-018)."""

    code: str
    order_code: str
    resource_name: str
    resource_type_name: str
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime


class RoomSource(BaseModel):
    """Khối booking cho phòng chơi (T-017) – nội bộ, không trả ra API."""

    code: str
    customer_ref: str
    resource_code: str
    resource_name: str
    resource_type_name: str
    start_at: dt.datetime
    end_at: dt.datetime
    min_tier: str | None = Field(default=None, description="Khoảng hạng của đơn (T-031)")
    max_tier: str | None = None


class CustomerBookingRow(BaseModel):
    code: str = Field(description="Mã con của khối")
    order_code: str = Field(description="Mã đơn – khu hội viên chỉ hiện mã này (T-019 AC7)")
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
    hour_prices: dict[int, int] = Field(
        default_factory=dict,
        description="Giá/giờ từng ô bán được theo bảng giá của ngày (giờ bắt đầu -> VND), cùng "
        "cách tính với lịch khách – chỉ để xem trước, giá chốt lúc đặt (T-025 AC9)",
    )


class CalendarBlock(BaseModel):
    type: Literal["booking", "session", "hold"]
    code: str | None = Field(description="Booking: mã con (mở chi tiết); sự kiện: mã sự kiện")
    order_code: str | None = Field(default=None, description="Booking: mã đơn (hiện trên khối)")
    resource_codes: list[str]
    start_time: str
    end_time: str
    start_hour: int
    end_hour: int
    # booking
    payment_status: PaymentStatus | None = None
    customer_name: str | None = None
    phone: str | None = None
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
    kind: Literal["order", "booking", "ticket", "session"]
    code: str = Field(description="order: mã đơn · booking: mã con · ticket / session: mã")
    play_date: dt.date
    order_code: str | None = Field(default=None, description="order / booking: mã đơn")
    codes: list[str] = Field(
        default_factory=list, description="order: mã con các khối (theo thứ tự -01, -02…)"
    )


# ---------- Booking / vé ----------


class CounterBlockIn(StrictIn):
    resource_code: str = Field(max_length=10)
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)


class CounterOrderIn(StrictIn):
    """Một lần bấm Đặt sân ở quầy = một đơn (T-019 phương án A): 1–20 khối cùng ngày."""

    date: dt.date
    blocks: list[CounterBlockIn] = Field(min_length=1, max_length=20)


class ItemCustomer(BaseModel):
    name: str
    phone: str | None
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
    cancel_reason: str | None = None
    cancelled_at: dt.datetime | None = None
    cancelled_by_label: str | None = None
    refund_amount: int = Field(default=0, description="Số Admin xác nhận hoàn tay (T-051)")


class ItemOut(BaseModel):
    """Thông tin booking / vé (SRS IV.5) – không SĐT đầy đủ, không id nội bộ."""

    kind: Literal["booking", "ticket"]
    code: str = Field(description="Booking: mã con {mã đơn}-NN · vé: mã vé")
    order_code: str | None = Field(default=None, description="Booking: mã đơn")
    version: int
    source: Source
    customer: ItemCustomer
    schedule: ItemSchedule
    payment: ItemPayment
    price_breakdown: list[QuoteItem] = Field(default_factory=list)
    note: str | None = None
    created_by: str
    created_at: dt.datetime
    actions: list[Literal["collect", "uncollectible", "cancel", "move"]]
    cancel_phase: Literal["before", "playing", "past"] | None = Field(
        default=None,
        description="Lúc này so với giờ chơi, để popup chọn câu cảnh báo (T-052); null: không hủy "
        "được",
    )


class CollectIn(StrictIn):
    method: Literal["cash", "transfer"]
    version: int


class UncollectibleIn(StrictIn):
    reason: str = Field(default="", max_length=500)
    version: int


# ---------- Hủy booking / vé (T-051) ----------

CancelSkipReason = Literal["started", "played", "cancelled", "uncollectible"]


class CancelIn(StrictIn):
    reason: str = Field(default="", max_length=500, description="Bắt buộc, tối đa 200 ký tự")
    version: int
    refund_confirmed: bool = Field(
        default=False, description="Khoản đã thu: Admin xác nhận đã / sẽ tự hoàn tiền"
    )


class OrderCancelIn(StrictIn):
    reason: str = Field(default="", max_length=500, description="Bắt buộc, tối đa 200 ký tự")
    refund_confirmed: bool = False
    codes: list[str] = Field(max_length=99, description="Mã con lấy từ xem trước")


class CancelPreviewItem(BaseModel):
    code: str
    play_date: dt.date
    start_at: dt.datetime
    resource_name: str
    amount: int
    payment_status: PaymentStatus


class CancelSkipped(BaseModel):
    code: str
    reason: CancelSkipReason


class CancelPreview(BaseModel):
    cancellable: list[CancelPreviewItem]
    skipped: list[CancelSkipped]
    refund_total: int = Field(description="Tổng các khối đã thu sẽ hủy (trừ khỏi doanh thu)")
    unpaid_total: int = Field(description="Tổng các khối chưa thu sẽ hủy")


class OrderCancelOut(BaseModel):
    cancelled: list[str]
    skipped: list[CancelSkipped]
    refund_total: int


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
    phone: str | None
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
    method: Literal["cash", "transfer"] | None = None
    kind: Literal["in", "refund"] | None = None
    q: str | None = None
    page: int = 1


class TransactionEntryItem(BaseModel):
    code: str = Field(description="Booking: mã con · vé: mã vé")
    kind: Literal["booking", "ticket"]
    resource_name: str = Field(description="Tên sân; vé: các sân của sự kiện, cách bằng dấu phẩy")
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    amount: int = Field(description="Phần tiền của mục trong dòng (dương)")


class TransactionEntry(BaseModel):
    """Một lần nhận tiền (``in``) hoặc hoàn tiền (``refund``) – sổ tiền vào (T-057, ADR-014).

    Không có id số nội bộ (T-006 SEC4): FE dùng vị trí dòng trong trang làm key."""

    kind: Literal["in", "refund"]
    method: Literal["cash", "transfer"] = Field(description="transfer gồm cả chuyển khoản online")
    source: Literal["counter", "counter_qr", "online"]
    amount: int = Field(description="Luôn dương; hoàn tiền FE hiện dấu −")
    occurred_at: dt.datetime
    order_code: str | None = Field(description="Mã đơn; vé: mã sự kiện")
    customer_name: str
    customer_phone: str | None = Field(
        description="SĐT đầy đủ (T-061): ai có quyền xem lịch sử giao dịch đều thấy"
    )
    member_code: str | None = None
    actor_label: str = Field(description='Người thu / hủy; tiền về qua cổng: "Hệ thống"')
    items: list[TransactionEntryItem]


class TransactionCards(BaseModel):
    """VND, theo bộ lọc ngày + sân (không theo phương thức / loại / tìm kiếm)."""

    net: int = Field(description="cash + transfer − refund")
    cash: int
    transfer: int
    refund: int


class TransactionsOut(BaseModel):
    date_from: dt.date
    date_to: dt.date
    cards: TransactionCards
    items: list[TransactionEntry] = Field(description="Mới nhất trước (theo occurred_at)")
    total: int
    page: int
    size: int


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
    event_code: str | None = Field(
        default=None, description="Ô sự kiện: mã sự kiện (mở chi tiết / mua vé, T-023)"
    )


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
    # Khoảng hạng phòng chơi (T-031) – lớp gọi đã kiểm (tên hạng, thứ tự); engine chỉ lưu
    min_tier: str | None = Field(default=None, max_length=20)
    max_tier: str | None = Field(default=None, max_length=20)


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
    cancelled: bool = Field(default=False, description="Khối đã bị sân hủy sau khi trả (T-051)")


class CheckoutEvent(BaseModel):
    """Lượt thanh toán mua vé (T-023): sự kiện + số vé; mã vé có khi đã thanh toán."""

    code: str = Field(description="Mã sự kiện")
    name: str
    play_date: dt.date
    start_time: str
    end_time: str
    resource_names: list[str]
    seats: int = Field(description="Số vé của lượt")
    ticket_price: int = Field(description="Giá một vé, chốt lúc giữ chỗ")
    ticket_codes: list[str] = Field(description="Mã vé ``{mã sự kiện}-Vnn`` – rỗng khi chưa trả")
    cancelled_ticket_codes: list[str] = Field(
        default_factory=list, description="Vé trong ``ticket_codes`` đã bị sân hủy (T-051)"
    )


class CheckoutView(BaseModel):
    """Trạng thái lượt thanh toán (engine) – lớp gọi che SĐT và thêm thông tin ngân hàng."""

    kind: Literal["court", "ticket"] = "court"
    status: Literal["pending", "paid", "expired"]
    expires_at: dt.datetime
    server_now: dt.datetime
    amount: int
    paid_amount: int
    paid_at: dt.datetime | None
    order_code: str = Field(description="Mã đơn – khách chỉ thấy mã này (ADR-010)")
    pay_ref: str = Field(description="= mã đơn bỏ dấu gạch (nội dung chuyển khoản)")
    customer_name: str
    customer_phone: str
    play_date: dt.date
    items: list[CheckoutItem] = Field(description="Khung sân – rỗng với lượt mua vé")
    event: CheckoutEvent | None = Field(default=None, description="Chỉ có với lượt mua vé")


class CheckoutCreated(CheckoutView):
    token: str = Field(description="Chuỗi truy cập – chỉ trả ở lần tạo; DB chỉ lưu SHA-256")


class LookupPending(BaseModel):
    expires_at: dt.datetime
    server_now: dt.datetime
    pay_ref: str
    amount: int


class LookupItem(BaseModel):
    code: str = Field(description="Mã con – FE không hiện cho khách")
    resource_name: str
    start_time: str
    end_time: str
    hours: int
    amount: int
    status: Literal["paid", "unpaid", "uncollectible", "cancelled", "pending", "expired"]
    matched: bool = Field(description="Khối có mã con đúng mã khách nhập")


class LookupTicket(BaseModel):
    code: str
    pay_status: PaymentStatus


class LookupEvent(BaseModel):
    """Tra cứu đơn vé (T-023 AC21): sự kiện + vé (rỗng khi chưa thanh toán)."""

    code: str
    name: str
    start_time: str
    end_time: str
    resource_names: list[str]
    seats: int
    ticket_price: int
    tickets: list[LookupTicket]


class LookupResult(BaseModel):
    """Tra cứu theo mã đơn **hoặc** mã con + SĐT -> cả đơn (T-019 AC3); đơn vé: mã đơn vé hoặc
    mã vé (T-023 AC21)."""

    kind: Literal["court", "ticket"] = "court"
    order_code: str
    status: Literal["paid", "unpaid", "uncollectible", "cancelled", "pending", "expired"]
    play_date: dt.date
    hours: int
    customer_name: str
    customer_phone: str
    amount: int
    payment_method: PaymentMethod | None
    paid_at: dt.datetime | None
    items: list[LookupItem] = Field(description="Khối sân – rỗng với đơn vé")
    pending: LookupPending | None = None
    event: LookupEvent | None = Field(default=None, description="Chỉ có với đơn vé")


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


# ---------- Đơn đặt (T-019, ADR-010) ----------


class CounterOrderOut(BaseModel):
    order_code: str
    bookings: list[ItemOut]


class OrderCollectIn(StrictIn):
    method: Literal["cash", "transfer"]


class OrderCollectOut(BaseModel):
    order_code: str
    collected: list[str] = Field(description="Mã con vừa thu")
    amount: int = Field(description="Tổng tiền vừa thu")
    bookings: list[ItemOut] = Field(description="Mọi khối của đơn sau khi thu")


class CollectQrInfo(BaseModel):
    """Thu cả đơn bằng QR (T-058): số tiền + nội dung chuyển khoản; lớp gọi ghép thông tin NH."""

    order_code: str
    pay_ref: str = Field(description="Nội dung chuyển khoản = mã đơn bỏ gạch, vd BK20261106001")
    amount: int = Field(description="Tổng các khối Chưa thanh toán hiện tại; 0 khi đã thu hết")
    status: Literal["unpaid", "paid"] = Field(description="paid: không còn khối chưa thu")
    blocks: int = Field(description="Số khối chưa thu")


# ---------- Khu hội viên: lịch, đơn của mình, sự kiện + mua vé (T-023) ----------


class MemberSlot(PublicSlot):
    """Ô lịch hội viên: thêm đánh dấu của chính mình. Không có thông tin của người khác."""

    mine: bool = Field(default=False, description="Ô thuộc booking của chính hội viên")
    order_code: str | None = Field(default=None, description="Mã đơn – chỉ khi ``mine``")
    has_ticket: bool = Field(default=False, description="Ô sự kiện mà hội viên đã có vé")


class MemberCalendarResource(BaseModel):
    code: str
    name: str
    slots: list[MemberSlot]


class MemberCalendar(BaseModel):
    date: dt.date
    server_now: dt.datetime
    columns: list[int]
    resources: list[MemberCalendarResource]


class MemberOrderItem(BaseModel):
    code: str = Field(description="Mã con – không hiện; dùng gọi /member-area/payments/{code}")
    resource_name: str
    start_time: str
    end_time: str
    hours: int
    amount: int
    pay_status: PaymentStatus


class MemberOrder(BaseModel):
    """Đơn đặt sân của chính hội viên (T-023 AC2) – không SĐT."""

    order_code: str
    play_date: dt.date
    source: Source
    pay_status: PaymentStatus = Field(
        description="Chung của đơn, bỏ qua khối đã hủy: còn khối chưa thu -> unpaid; tất cả đã "
        "thu -> paid; còn lại -> uncollectible; hủy hết -> cancelled"
    )
    amount: int
    items: list[MemberOrderItem]


class MyTicket(BaseModel):
    code: str
    pay_status: PaymentStatus


EventBuyBlock = Literal["started", "full", "free", "deleted"]


class EventInfo(BaseModel):
    """Sự kiện cho hội viên (T-023 AC5) – không có danh sách người mua."""

    code: str
    name: str
    play_date: dt.date
    start_time: str
    end_time: str
    resource_names: list[str]
    ticket_price: int
    capacity: int
    taken: int = Field(description="Vé đã có + ghế đang giữ online")
    max_seats: int = Field(description="Số vé tối đa mua được lúc này: min(còn lại, 10)")
    can_buy: bool
    reason: EventBuyBlock | None = Field(description="Lý do không mua được (engine)")
    my_tickets: list[MyTicket] | None = Field(
        default=None, description="Vé của tôi – chỉ khi lớp gọi truyền refs của hội viên"
    )


# ---------- Đặt sân định kỳ (T-035) ----------

RecurringReason = Literal["booked", "event", "hold", "closed", "inactive", "past", "no_price"]


class RecurringSessionIn(StrictIn):
    """Một buổi tường minh (T-043): FE sinh từ lịch chung rồi áp chỉnh sửa / gợi ý; bỏ buổi = không
    gửi buổi đó."""

    date: dt.date
    resource_code: str = Field(max_length=10)
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)


class RecurringIn(StrictIn):
    """Các thứ trong tuần + khung giờ, từ ngày -> đến ngày (khách do lớp gọi dựng).

    ``sessions`` (T-043): danh sách buổi tường minh, mỗi buổi một sân / giờ riêng – có thì dùng
    thay cho lịch chung; không gửi thì sinh từ thứ + giờ + khoảng ngày trên ``resource_code``.
    """

    resource_code: str = Field(max_length=10)
    weekdays: list[int] = Field(max_length=7, description="ISO: 1 = Thứ 2 … 7 = Chủ nhật")
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
    date_from: dt.date
    date_to: dt.date
    discount_pct: int = Field(default=0, ge=0, le=100, description="% giảm cho cả đơn, 0–100")
    sessions: list[RecurringSessionIn] | None = Field(
        default=None,
        max_length=100,
        description="Buổi tường minh (T-043); tối đa 60 buổi, trong 92 ngày, mỗi buổi một sân",
    )


class RecurringSuggestion(BaseModel):
    """Gợi ý cho buổi trùng (T-043): ``shift`` = cùng sân lệch giờ gần nhất, ``court`` = cùng giờ
    sân khác (ưu tiên cùng loại sân). Đã kiểm giờ mở cửa, giá và chỗ trống của ngày đó."""

    kind: Literal["shift", "court"]
    resource_code: str
    resource_name: str
    start_hour: int
    end_hour: int
    price: int


class RecurringSession(BaseModel):
    date: dt.date
    weekday: int = Field(description="ISO 1–7")
    resource_code: str
    resource_name: str
    start_hour: int
    end_hour: int
    start_time: str
    end_time: str
    start_at: dt.datetime
    end_at: dt.datetime
    price: int | None = Field(description="Giá gốc theo bảng giá ngày đó; null khi không định giá")
    price_after_discount: int | None
    ok: bool
    reason: RecurringReason | None = None
    reason_text: str | None = None
    suggestions: list[RecurringSuggestion] = Field(
        default_factory=list,
        description="Tối đa 2 – chỉ buổi lỗi booked / event / hold (T-043)",
    )


class RecurringPreview(BaseModel):
    sessions: list[RecurringSession]
    count: int = Field(description="Số buổi")
    original_amount: int = Field(description="Tổng giá gốc các buổi định giá được")
    discount_pct: int
    discount_amount: int
    total: int = Field(description="Phải thu = gốc − giảm")
    conflicts_count: int = Field(description="Số buổi không đặt được")


class RecurringCreated(BaseModel):
    order_code: str
    bookings: list[ItemOut]
    original_amount: int
    discount_pct: int
    discount_amount: int
    total: int


RecurringStatus = Literal["unpaid", "paid", "uncollectible", "cancelled"]


class RecurringOrderRow(BaseModel):
    """Một đơn định kỳ (T-039). Lịch suy từ các buổi: giờ của buổi đầu, khoảng ngày buổi đầu –
    buổi cuối, thứ = các thứ có buổi. ``customer_phone`` đầy đủ – lớp gọi phải che."""

    order_code: str
    customer_name: str
    customer_phone: str
    resource_code: str
    resource_name: str
    weekdays: list[int] = Field(description="ISO 1–7, các thứ có buổi")
    start_hour: int
    end_hour: int
    date_from: dt.date = Field(description="Ngày buổi đầu")
    date_to: dt.date = Field(description="Ngày buổi cuối")
    sessions: int
    original_amount: int
    discount_pct: int
    discount_amount: int
    total: int = Field(description="Phải thu = tổng các buổi (sau giảm)")
    status: RecurringStatus = Field(
        description="unpaid: còn buổi chưa thu · paid: mọi buổi đã thu · uncollectible: không còn "
        "buổi chưa thu và có buổi Không thu được · cancelled: mọi buổi đã hủy. Chỉ xét buổi "
        "chưa hủy"
    )
    created_at: dt.datetime
    created_by: str


class RecurringCounts(BaseModel):
    all: int
    unpaid: int
    paid: int
    uncollectible: int
    cancelled: int = 0


class RecurringOrderList(BaseModel):
    items: list[RecurringOrderRow]
    counts: RecurringCounts = Field(description="Theo ``q``, bỏ qua ``status``")
    page: int
    size: int
    total: int = Field(description="Số đơn khớp ``status`` + ``q``")


# ---------- Đơn đặt sân (T-041) ----------

OrderKind = Literal["single", "recurring"]


class OrderRow(RecurringOrderRow):
    """Một đơn đặt sân bất kỳ (quầy / online / định kỳ) – không gồm vé. ``customer_phone`` đầy
    đủ – lớp gọi phải che. Lịch suy từ các khối (``date_from`` / ``date_to`` = khối đầu / cuối)."""

    kind: OrderKind = Field(description="single = đơn ngày (quầy / online) · recurring = định kỳ")
    source: Source = Field(description="counter = tại quầy · online")
    member_code: str | None = Field(description="Mã HV khi khách là hội viên")
    resource_codes: list[str] = Field(description="Mọi sân của đơn (đơn ngày có thể nhiều sân)")
    resource_names: list[str]
    play_date: dt.date = Field(description="Ngày chơi của đơn (định kỳ: ngày buổi đầu)")
    blocks: int = Field(description="Số khối (đơn ngày) / số buổi (định kỳ)")


class OrderCounts(BaseModel):
    all: RecurringCounts
    single: RecurringCounts
    recurring: RecurringCounts


class OrderList(BaseModel):
    items: list[OrderRow]
    counts: OrderCounts = Field(description="Loại × trạng thái, theo q + ngày (bỏ qua kind/status)")
    page: int
    size: int
    total: int = Field(description="Số đơn khớp kind + status + q + ngày")


# ---------- Sự kiện sắp tới trong khu hội viên (T-045) ----------


class UpcomingEvent(BaseModel):
    """Sự kiện chưa bắt đầu – không có danh sách người mua."""

    code: str
    name: str
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    start_time: str
    end_time: str
    resource_names: list[str]
    ticket_price: int
    capacity: int
    taken: int = Field(description="Vé đã có + ghế đang giữ online")
    remaining: int
    can_buy: bool
    reason: EventBuyBlock | None = Field(description="full / free (engine); online_off do lớp gọi")
    my_ticket_count: int = Field(description="Số vé của hội viên trong sự kiện (mọi trạng thái)")

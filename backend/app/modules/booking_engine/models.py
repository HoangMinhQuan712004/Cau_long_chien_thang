"""ORM của booking engine – mọi bảng nằm trong Postgres schema ``booking`` (ADR-003).

Quy ước: mọi bảng có ``tenant_id`` (NOT NULL) và nằm trong khóa unique/exclusion;
**không FK ra ngoài schema ``booking``** (test kiến trúc kiểm).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "booking"

DEFAULT_TENANT_SETTINGS: dict[str, Any] = {
    "slot_minutes": 60,
    "half_step_minutes": 30,
    "hold_minutes": 5,
    "max_advance_days": None,  # không giới hạn (người dùng chốt 28/10, T-008 AC31b)
    "counter_same_day_only": True,
    "code_prefix": "BK",
    "session_capacity_max": 99,
    "resource_code_prefix": "S",
    # Nhãn hiển thị của tài nguyên trong thông báo lỗi (engine không gắn cứng tên miền nghiệp vụ)
    "resource_label": "sân",
}

DAY_TYPES = ("weekday", "weekend", "holiday")
BANDS = ("offpeak", "peak")


def _tenant_fk() -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.tenant.id", ondelete="RESTRICT")


class Tenant(Base):
    __tablename__ = "tenant"
    __table_args__ = (UniqueConstraint("code"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(50), server_default=text("'Asia/Ho_Chi_Minh'"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Phiên bản bảng giá (optimistic lock cho PUT /booking/prices)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    prices_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prices_updated_by: Mapped[str | None] = mapped_column(String(100))


class ResourceType(Base):
    __tablename__ = "resource_type"
    __table_args__ = (UniqueConstraint("tenant_id", "code"), {"schema": SCHEMA})

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(50))
    sort: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class Resource(Base):
    __tablename__ = "resource"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index(
            "uq_resource_tenant_id_lower_name", "tenant_id", func.lower(text("name")), unique=True
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    resource_type_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource_type.id", ondelete="RESTRICT"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourceSchedule(Base):
    """Giờ mở cửa + khung cao điểm theo phiên bản có ngày hiệu lực.

    Lịch của ngày D = bản có ``effective_from`` lớn nhất ≤ D. Giờ lưu bằng **phút từ 0h**
    (cho phép đóng cửa lúc 24:00); bội 30 phút.
    """

    __tablename__ = "resource_schedule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "resource_id", "effective_from"),
        CheckConstraint("open_minute >= 0 AND open_minute % 30 = 0", name="open_minute"),
        CheckConstraint("close_minute <= 1440 AND close_minute % 30 = 0", name="close_minute"),
        CheckConstraint("open_minute < close_minute", name="open_before_close"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    resource_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource.id", ondelete="CASCADE"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    open_minute: Mapped[int] = mapped_column(SmallInteger)
    close_minute: Mapped[int] = mapped_column(SmallInteger)
    # [["05:00","07:00"], ["17:00","21:00"]] – đã sắp xếp, không chồng nhau
    peak_bands: Mapped[list[list[str]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_by_label: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpecialDay(Base):
    """Ngày đặc biệt (Lễ/Tết) – loại ngày ``holiday``; các khoảng không chồng nhau."""

    __tablename__ = "special_day"
    __table_args__ = (
        ExcludeConstraint(
            ("tenant_id", "="),
            (text("daterange(date_from, date_to, '[]')"), "&&"),
            name="ex_special_day_no_overlap",
            using="gist",
        ),
        CheckConstraint("date_from <= date_to", name="range"),
        CheckConstraint(
            "extract(year FROM date_from) = extract(year FROM date_to)", name="same_year"
        ),
        CheckConstraint("day_type = 'holiday'", name="day_type"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(100))
    day_type: Mapped[str] = mapped_column(String(20), server_default=text("'holiday'"))


class PriceRule(Base):
    """Giá theo loại tài nguyên × loại ngày × band (VND/giờ)."""

    __tablename__ = "price_rule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "resource_type_id", "day_type", "band"),
        CheckConstraint("day_type IN ('weekday', 'weekend', 'holiday')", name="day_type"),
        CheckConstraint("band IN ('offpeak', 'peak')", name="band"),
        CheckConstraint("price_per_hour > 0", name="price_positive"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    resource_type_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource_type.id", ondelete="CASCADE")
    )
    day_type: Mapped[str] = mapped_column(String(20))
    band: Mapped[str] = mapped_column(String(20))
    price_per_hour: Mapped[int] = mapped_column(Integer)


class CodeSequence(Base):
    """Bộ đếm mã theo (tenant, tiền tố, ngày chơi) – ``BK-YYYYMMDD-NNN``."""

    __tablename__ = "code_sequence"
    __table_args__ = {"schema": SCHEMA}

    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk(), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(10), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer)


class _CustomerSnapshot:
    """Khách tại thời điểm đặt – do server dựng (ADR-004 S8); engine không biết "hội viên"."""

    customer_ref: Mapped[str] = mapped_column(String(40))
    customer_kind: Mapped[str] = mapped_column(String(10))
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(15))  # đầy đủ – chỉ để tìm, không trả ra
    member_code: Mapped[str | None] = mapped_column(String(10))
    member_tier: Mapped[str | None] = mapped_column(String(20))


class _Payment:
    """Tiền + trạng thái thanh toán một chiều: unpaid -> paid | uncollectible (BR-013)."""

    amount: Mapped[int] = mapped_column(Integer)
    payment_status: Mapped[str] = mapped_column(String(15), server_default=text("'unpaid'"))
    payment_method: Mapped[str | None] = mapped_column(String(20))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_by_type: Mapped[str | None] = mapped_column(String(20))
    collected_by_id: Mapped[int | None] = mapped_column(BigInteger)
    collected_by_label: Mapped[str | None] = mapped_column(String(100))
    gateway_ref: Mapped[str | None] = mapped_column(String(100), unique=True)
    uncollectible_reason: Mapped[str | None] = mapped_column(String(200))
    marked_by_type: Mapped[str | None] = mapped_column(String(20))
    marked_by_id: Mapped[int | None] = mapped_column(BigInteger)
    marked_by_label: Mapped[str | None] = mapped_column(String(100))
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(500))
    created_by_type: Mapped[str] = mapped_column(String(20))
    created_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_label: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


def _payment_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("source IN ('counter', 'online')", name="source"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint(
            "payment_status IN ('unpaid', 'paid', 'uncollectible')", name="payment_status"
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('cash', 'transfer', 'online_transfer')",
            name="payment_method",
        ),
        CheckConstraint(
            "payment_status <> 'paid' OR (payment_method IS NOT NULL AND paid_at IS NOT NULL)",
            name="paid_has_method",
        ),
        CheckConstraint(
            "payment_status <> 'uncollectible' OR "
            "(uncollectible_reason IS NOT NULL AND source = 'counter')",
            name="uncollectible_reason",
        ),
        CheckConstraint("customer_kind IN ('member', 'temp')", name="customer_kind"),
    )


class Checkout(_CustomerSnapshot, Base):
    """Một lần khách bấm "Xác nhận & thanh toán" (ADR-007): giữ chỗ 5 phút, chung một QR.

    ``pending -> paid | expired``. Mỗi dải giờ liền nhau trên một sân = một ``hold`` mang sẵn mã
    booking + giá; tiền về đủ -> mỗi hold thành một booking cùng mã. Token truy cập chỉ lưu SHA-256.
    """

    __tablename__ = "checkout"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pay_ref"),
        CheckConstraint("status IN ('pending', 'paid', 'expired')", name="status"),
        CheckConstraint("amount >= 0 AND paid_amount >= 0", name="amounts"),
        CheckConstraint("customer_kind IN ('member', 'temp')", name="customer_kind"),
        Index("ix_checkout_status_expires_at", "status", "expires_at"),
        # Mỗi SĐT chỉ một lượt đang chờ thanh toán (T-008 AC13) – chống đua bằng unique một phần
        Index(
            "uq_checkout_pending_phone",
            "tenant_id",
            "customer_phone",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    pay_ref: Mapped[str] = mapped_column(String(20))
    play_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Integer)
    paid_amount: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    note: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'pending'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Hold(Base):
    """Giữ chỗ online 5 phút (BR-002; người dùng đổi 7 -> 5 ngày 28/10).

    ``court``: giữ khung sân (có allocation ``kind='hold'``); hold của checkout mang mã booking,
    giá, bảng giá chi tiết. ``seat``: giữ chỗ trong sự kiện (chưa bán vé online).
    """

    __tablename__ = "hold"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("kind IN ('court', 'seat')", name="kind"),
        CheckConstraint("status IN ('active', 'converted', 'expired', 'released')", name="status"),
        CheckConstraint("seats >= 1", name="seats_positive"),
        CheckConstraint("(kind = 'seat') = (session_id IS NOT NULL)", name="seat_has_session"),
        CheckConstraint(
            "kind <> 'court' OR checkout_id IS NULL OR code IS NOT NULL", name="checkout_has_code"
        ),
        Index("ix_hold_status_expires_at", "status", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    kind: Mapped[str] = mapped_column(String(10))
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.session.id", ondelete="RESTRICT"), index=True
    )
    checkout_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.checkout.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(30))
    amount: Mapped[int | None] = mapped_column(Integer)
    price_breakdown: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    seats: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Booking(_CustomerSnapshot, _Payment, Base):
    """Một lượt đặt trên **một** tài nguyên, các khung liền nhau; tiền chốt lúc đặt (BR-009)."""

    __tablename__ = "booking"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        *_payment_checks(),
        CheckConstraint("start_at < end_at", name="range"),
        Index("ix_booking_tenant_play_date", "tenant_id", "play_date"),
        Index("ix_booking_tenant_status_play_date", "tenant_id", "payment_status", "play_date"),
        Index("ix_booking_tenant_customer_ref", "tenant_id", "customer_ref"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    code: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(10))
    resource_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource.id", ondelete="RESTRICT"), index=True
    )
    play_date: Mapped[date] = mapped_column(Date)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # [{"start_time": "17:00", "end_time": "18:00", "band": "peak", "price": 180000}, …]
    price_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    # Booking online: lượt thanh toán đã tạo ra booking này (ADR-007)
    checkout_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.checkout.id", ondelete="RESTRICT"), index=True
    )


class EventSession(Base):
    """Sự kiện (buổi bán vé): chiếm 1..n tài nguyên liền nhau; tiền nằm ở vé (BR-017)."""

    __tablename__ = "session"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("capacity BETWEEN 1 AND 99", name="capacity"),
        CheckConstraint("ticket_price >= 0", name="ticket_price"),
        CheckConstraint("status IN ('active', 'deleted')", name="status"),
        CheckConstraint("start_at < end_at", name="range"),
        Index("ix_session_tenant_play_date", "tenant_id", "play_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    play_date: Mapped[date] = mapped_column(Date)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(SmallInteger)
    ticket_price: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), server_default=text("'active'"))
    created_by_type: Mapped[str] = mapped_column(String(20))
    created_by_id: Mapped[int | None] = mapped_column(BigInteger)
    created_by_label: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_type: Mapped[str | None] = mapped_column(String(20))
    deleted_by_id: Mapped[int | None] = mapped_column(BigInteger)
    deleted_by_label: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class Ticket(_CustomerSnapshot, _Payment, Base):
    """Vé = 1 chỗ của 1 khách trong sự kiện; mã ``{mã sự kiện}-V{nn}`` (BR-012, BR-024)."""

    __tablename__ = "ticket"
    __table_args__ = (
        UniqueConstraint("session_id", "seq"),
        UniqueConstraint("tenant_id", "code"),
        *_payment_checks(),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    session_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.session.id", ondelete="RESTRICT"), index=True
    )
    seq: Mapped[int] = mapped_column(SmallInteger)
    code: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(10))


class Allocation(Base):
    """Chỗ chiếm nguyên tử trên một tài nguyên – chống trùng lịch **chỉ** bằng exclusion constraint.

    Đúng một cột chủ (``hold_id`` / ``booking_id`` / ``session_id``) khớp ``kind``; biên giờ tròn.
    Không thu được: allocation **giữ active** (khung không bán lại, BR-015).
    """

    __tablename__ = "allocation"
    __table_args__ = (
        ExcludeConstraint(
            ("tenant_id", "="),
            ("resource_id", "="),
            ("time_range", "&&"),
            name="ex_allocation_no_overlap",
            using="gist",
            where=text("active"),
        ),
        CheckConstraint("kind IN ('hold', 'booking', 'session')", name="kind"),
        CheckConstraint(
            "NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)",
            name="time_range_bounds",
        ),
        CheckConstraint(
            # Múi giờ tenant lệch UTC số giờ tròn (Asia/Ho_Chi_Minh = +7) -> giờ tròn theo epoch
            "extract(epoch FROM lower(time_range)) % 3600 = 0 "
            "AND extract(epoch FROM upper(time_range)) % 3600 = 0",
            name="whole_hours",
        ),
        CheckConstraint(
            "(kind = 'hold' AND hold_id IS NOT NULL AND booking_id IS NULL AND session_id IS NULL)"
            " OR (kind = 'booking' AND booking_id IS NOT NULL AND hold_id IS NULL"
            " AND session_id IS NULL)"
            " OR (kind = 'session' AND session_id IS NOT NULL AND hold_id IS NULL"
            " AND booking_id IS NULL)",
            name="one_owner",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    resource_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource.id", ondelete="RESTRICT"), index=True
    )
    time_range: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    kind: Mapped[str] = mapped_column(String(10))
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.hold.id", ondelete="RESTRICT"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.booking.id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.session.id", ondelete="RESTRICT"), index=True
    )
    # Mã đối tượng chiếm chỗ (BK-…) – hiện trong thông báo E-CFG-3/4
    owner_code: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class OutboxEvent(Base):
    """Sự kiện ghi cùng transaction nghiệp vụ; worker phát qua ``core.events`` sau commit."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

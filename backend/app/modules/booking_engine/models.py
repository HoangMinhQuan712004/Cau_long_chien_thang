"""ORM của booking engine – mọi bảng nằm trong Postgres schema ``booking`` (ADR-003).

Quy ước: mọi bảng có ``tenant_id`` (NOT NULL) và nằm trong khóa unique/exclusion;
**không FK ra ngoài schema ``booking``** (test kiến trúc kiểm).
"""

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
    SmallInteger,
    String,
    UniqueConstraint,
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
    "hold_minutes": 7,
    "max_advance_days": "end_of_next_month",
    "code_prefix": "BK",
    "counter_same_day_only": True,
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


class Allocation(Base):
    """Chỗ chiếm nguyên tử trên một tài nguyên – chống trùng lịch **chỉ** bằng exclusion constraint.

    T-005 tạo bảng ở dạng tối thiểu để kiểm D4/D5; T-006 thêm cột chủ sở hữu
    (``hold_id`` / ``booking_id`` / ``session_id``) và các CHECK liên quan.
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
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(SmallInteger, _tenant_fk())
    resource_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.resource.id", ondelete="RESTRICT"), index=True
    )
    time_range: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    kind: Mapped[str] = mapped_column(String(10))
    # Mã đối tượng chiếm chỗ (BK-…) để hiện trong thông báo E-CFG-3/4
    owner_code: Mapped[str | None] = mapped_column(String(30))
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

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import TSTZRANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class BookingStatus(enum.StrEnum):
    PENDING = "pending"  # đang giữ chỗ / chờ thanh toán
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"  # quá hạn giữ chỗ mà chưa thanh toán


ACTIVE_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


class BookingSource(enum.StrEnum):
    ONLINE = "online"
    COUNTER = "counter"  # nhân viên đặt tại quầy / qua điện thoại


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    customer_name: Mapped[str] = mapped_column(String(255))
    customer_phone: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[BookingStatus] = mapped_column(
        _enum(BookingStatus, "booking_status"), default=BookingStatus.PENDING, index=True
    )
    source: Mapped[BookingSource] = mapped_column(
        _enum(BookingSource, "booking_source"), default=BookingSource.ONLINE
    )
    total_amount: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    slots: Mapped[list["BookingSlot"]] = relationship(
        back_populates="booking",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BookingSlot.time_range",
    )


class BookingSlot(Base):
    """Một khoảng thời gian trên một sân.

    Exclusion constraint đảm bảo ở tầng DB: hai slot đang active trên cùng một sân
    không bao giờ chồng lấn thời gian, kể cả khi có nhiều request đồng thời.
    """

    __tablename__ = "booking_slots"
    __table_args__ = (
        ExcludeConstraint(
            ("court_id", "="),
            ("time_range", "&&"),
            name="ex_booking_slots_no_overlap",
            using="gist",
            where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id", ondelete="RESTRICT"))
    time_range: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    price: Mapped[int] = mapped_column(Integer)
    # Bản sao trạng thái để dùng trong WHERE của exclusion constraint
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    booking: Mapped[Booking] = relationship(back_populates="slots")

    @property
    def start(self) -> datetime:
        return self.time_range.lower

    @property
    def end(self) -> datetime:
        return self.time_range.upper

import enum

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class PaymentMethod(enum.StrEnum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    PAYOS = "payos"
    VNPAY = "vnpay"
    MOMO = "momo"


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod, "payment_method"))
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"), default=PaymentStatus.PENDING
    )
    amount: Mapped[int] = mapped_column(Integer)
    provider_ref: Mapped[str | None] = mapped_column(String(255), unique=True)
    raw: Mapped[dict | None] = mapped_column(JSONB)  # payload webhook để đối soát
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

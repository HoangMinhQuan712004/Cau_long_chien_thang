"""Hồ sơ khách: hội viên + hồ sơ tạm (T-006 §2.1) – bản tối thiểu cho đặt sân.

Màn Hội viên đầy đủ (hạng, gia hạn…) chờ SRS Hội viên.
"""

from sqlalchemy import BigInteger, Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

KINDS = ("member", "temp")
TIERS = ("Vàng", "Bạc", "Đồng")


class Customer(TimestampMixin, Base):
    __tablename__ = "customer"
    __table_args__ = (
        CheckConstraint("kind IN ('member', 'temp')", name="kind"),
        CheckConstraint("phone ~ '^0[0-9]{9}$'", name="phone_format"),
        CheckConstraint(
            "(kind = 'member') = (member_code IS NOT NULL)", name="member_code_iff_member"
        ),
        CheckConstraint("tier IS NULL OR tier IN ('Vàng', 'Bạc', 'Đồng')", name="tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    member_code: Mapped[str | None] = mapped_column(String(6), unique=True)  # HV0031
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(10), unique=True)  # đã chuẩn hóa
    tier: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500))

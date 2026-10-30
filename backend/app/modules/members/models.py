"""Hồ sơ khách: hội viên + hồ sơ tạm (T-006 §2.1, T-014 màn Hội viên)."""

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

KINDS = ("member", "temp")
# Hạng = trình độ chơi (thấp -> cao, cũng là thứ tự hiển thị); NULL = chưa xếp hạng
TIERS = (
    "Yếu",
    "Trung bình yếu",
    "Trung bình -",
    "Trung bình",
    "Trung bình +",
    "Khá",
    "Bán chuyên",
    "Chuyên nghiệp",
)


class Customer(TimestampMixin, Base):
    __tablename__ = "customer"
    __table_args__ = (
        CheckConstraint("kind IN ('member', 'temp')", name="kind"),
        CheckConstraint("phone ~ '^0[0-9]{9}$'", name="phone_format"),
        CheckConstraint(
            "(kind = 'member') = (member_code IS NOT NULL)", name="member_code_iff_member"
        ),
        CheckConstraint(
            "tier IS NULL OR tier IN ('Yếu', 'Trung bình yếu', 'Trung bình -', 'Trung bình', "
            "'Trung bình +', 'Khá', 'Bán chuyên', 'Chuyên nghiệp')",
            name="tier",
        ),
        CheckConstraint("gender IS NULL OR gender IN ('male', 'female')", name="gender"),
        Index("ix_customer_kind_is_active", "kind", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Mã tham chiếu của hồ sơ tạm trong API (hội viên dùng mã HV) – không lộ id
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(String(10))
    member_code: Mapped[str | None] = mapped_column(String(6), unique=True)  # HV0031
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(10), unique=True)  # đã chuẩn hóa
    tier: Mapped[str | None] = mapped_column(String(20))  # trình độ; NULL = chưa xếp hạng
    gender: Mapped[str | None] = mapped_column(String(6))
    racket: Mapped[str | None] = mapped_column(String(100))  # vợt đang dùng
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500))


class Racket(TimestampMixin, Base):
    """Danh mục vợt (T-014): Admin quản lý, hoặc tự thêm khi lưu hội viên (chọn "Khác…")."""

    __tablename__ = "racket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # Tên chuẩn hóa (gộp khoảng trắng, casefold) – chống trùng "yonex  astrox" / "Yonex Astrox"
    name_key: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

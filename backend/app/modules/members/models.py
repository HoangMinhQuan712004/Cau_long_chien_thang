"""Hồ sơ khách: hội viên + hồ sơ tạm (T-006 §2.1, T-014 màn Hội viên)."""

import uuid
from datetime import date, datetime

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
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin

KINDS = ("member", "temp")
# Nguồn hồ sơ hội viên: quầy / Admin thêm, hoặc khách tự xác minh SĐT trên web (T-021 R1)
SOURCES = ("counter", "self_register")
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
        CheckConstraint("birth_date IS NULL OR birth_date >= '1900-01-01'", name="birth_date"),
        CheckConstraint("source IN ('counter', 'self_register')", name="source"),
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
    birth_date: Mapped[date | None] = mapped_column(Date)  # ngày sinh; NULL = chưa nhập
    racket: Mapped[str | None] = mapped_column(String(100))  # vợt đang dùng
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500))
    # Khu hội viên (T-016, ADR-009 §2): hội viên tự sửa
    nickname: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(254))  # chỉ để liên hệ, không đăng nhập
    show_on_records: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Khóa lạc quan cho Hồ sơ của tôi (E-HV-12) – tăng khi hội viên tự sửa
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Ai tạo / nâng thành hội viên: "counter" (quầy, Admin) | "self_register" ("Tự đăng ký online")
    source: Mapped[str] = mapped_column(String(20), server_default=text("'counter'"))


# Email không trùng giữa các hồ sơ, không phân biệt hoa thường (ADR-009 §6)
Index(
    "uq_customer_email_lower",
    func.lower(Customer.email),
    unique=True,
    postgresql_where=Customer.email.isnot(None),
)


class CustomerAvatar(Base):
    """Ảnh đại diện đã giải mã + mã hóa lại (WebP vuông ≤ 512 px, không EXIF) – ADR-009 §5."""

    __tablename__ = "customer_avatar"

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customer.id", ondelete="CASCADE"), primary_key=True
    )
    content_type: Mapped[str] = mapped_column(String(30))
    bytes: Mapped[bytes] = mapped_column(LargeBinary)
    etag: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Racket(TimestampMixin, Base):
    """Danh mục vợt (T-014): Admin quản lý, hoặc tự thêm khi lưu hội viên (chọn "Khác…")."""

    __tablename__ = "racket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # Tên chuẩn hóa (gộp khoảng trắng, casefold) – chống trùng "yonex  astrox" / "Yonex Astrox"
    name_key: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))

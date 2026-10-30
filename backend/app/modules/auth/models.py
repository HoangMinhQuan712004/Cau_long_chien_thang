"""Tài khoản, phiên quản trị, mã OTP (T-013, ADR-008; port PR #17 lên nền dev).

Đăng nhập: Admin bằng SĐT, nhân viên bằng tên đăng nhập, khách bằng SĐT / tên đăng nhập / Google.
Cột ``email`` giữ lại (cho phép NULL, thôi dùng để đăng nhập) để downgrade không mất dữ liệu.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Role(enum.StrEnum):
    ADMIN = "admin"  # chủ sân – đăng nhập bằng SĐT
    STAFF = "staff"  # nhân viên (mỗi người một tài khoản, mã NV001…) – tên đăng nhập
    MEMBER = "member"  # khách hàng = hội viên (T-015; trước là "customer")


# Mã nhân viên NV001…, không dùng lại
STAFF_CODE_SEQ = Sequence("staff_code_seq", metadata=Base.metadata)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "phone IS NOT NULL OR username IS NOT NULL OR google_sub IS NOT NULL", name="login_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Thôi dùng để đăng nhập (T-013); giữ để downgrade không mất dữ liệu – xóa ở việc sau
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)  # 0xxxxxxxxx
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    username: Mapped[str | None] = mapped_column(String(50), unique=True)
    staff_code: Mapped[str | None] = mapped_column(String(20), unique=True)  # NV007
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    google_email: Mapped[str | None] = mapped_column(String(255))  # chỉ để hiện
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str | None] = mapped_column(String(255))  # NULL = chỉ Google
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=Role.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Claim ``ver`` của JWT khách; đổi / đặt lại mật khẩu tăng -> JWT cũ hết hiệu lực
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Tài khoản hội viên do sân tạo (mật khẩu ban đầu = SĐT): bắt đổi trước khi dùng (T-015)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    member_account_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionEndReason(enum.StrEnum):
    LOGOUT = "logout"
    EXPIRED = "expired"
    PASSWORD_CHANGED = "password_changed"
    ACCOUNT_DISABLED = "account_disabled"
    REVOKED_BY_ADMIN = "revoked_by_admin"


class AdminSession(Base):
    """Phiên khu quản trị (Admin / nhân viên): cookie giữ token ngẫu nhiên, DB lưu SHA-256."""

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # cứng, không gia hạn
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[SessionEndReason | None] = mapped_column(
        Enum(
            SessionEndReason,
            name="session_end_reason",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(45))


class OtpPurpose(enum.StrEnum):
    PASSWORD_RESET = "password_reset"  # quên mật khẩu (chưa đăng nhập)
    PHONE_VERIFY = "phone_verify"  # khách đã đăng nhập gắn / xác minh SĐT
    BOOKING_PHONE = "booking_phone"  # đặt online: xác minh SĐT trước khi giữ chỗ


class OtpCode(Base):
    """Mã OTP (chỉ lưu HMAC); xác minh đúng -> token dùng tiếp (chỉ lưu SHA-256).

    ``user_id`` NULL: SĐT không có tài khoản (quên mật khẩu – để trả lời y hệt) hoặc đặt online.
    """

    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("ix_otp_codes_phone_purpose_created_at", "phone", "purpose", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[OtpPurpose] = mapped_column(
        Enum(OtpPurpose, name="otp_purpose", values_callable=lambda e: [m.value for m in e])
    )
    phone: Mapped[str] = mapped_column(String(20), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256(SECRET_KEY, mã)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String(45))

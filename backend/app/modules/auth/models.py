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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Role(enum.StrEnum):
    ADMIN = "admin"  # chủ sân – đăng nhập bằng SĐT
    STAFF = "staff"  # nhân viên do Admin cấp – đăng nhập bằng tên đăng nhập
    CUSTOMER = "customer"


# Mã nhân viên NV001…, không dùng lại
STAFF_CODE_SEQ = Sequence("staff_code_seq", metadata=Base.metadata)


class User(TimestampMixin, Base):
    """Tài khoản đăng nhập bằng SĐT, tên đăng nhập hoặc Google (không dùng email)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "phone IS NOT NULL OR username IS NOT NULL OR google_sub IS NOT NULL", name="login_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 0xxxxxxxxx
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    # nhân viên, tự sinh `<tên>.<mã>`
    username: Mapped[str | None] = mapped_column(String(50), unique=True)
    # NV007 – chỉ nhân viên
    staff_code: Mapped[str | None] = mapped_column(String(20), unique=True)
    # sub Google – chỉ khách
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    # email Google đã xác minh, chỉ để hiện
    google_email: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    # NULL = không mật khẩu (Google)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=Role.CUSTOMER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # lần sai liên tiếp + hạn tạm khóa
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # claim `ver` của JWT khách; đổi mật khẩu tăng ⇒ JWT cũ hết hiệu lực
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class SessionEndReason(enum.StrEnum):
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"  # Admin đặt lại mật khẩu nhân viên (BR-012)
    ACCOUNT_DISABLED = "account_disabled"  # Admin khóa tài khoản nhân viên
    REVOKED_BY_ADMIN = "revoked_by_admin"  # Admin đăng xuất từ xa một phiên


class AdminSession(Base):
    """Phiên đăng nhập khu quản trị. Cookie chỉ giữ token ngẫu nhiên, DB lưu hash."""

    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # hết hạn cứng, không gia hạn
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
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


class AuditAction(enum.StrEnum):
    """Hành động ghi lịch sử thao tác (BR-010, BR-013)."""

    LOGIN_SUCCESS = "login_success"  # Đăng nhập thành công
    LOGIN_LOCKED = "login_locked"  # Tạm khóa đăng nhập
    LOGIN_BLOCKED = "login_blocked"  # không dùng nữa, giữ vì DB còn dữ liệu cũ
    LOGOUT = "logout"  # Đăng xuất
    STAFF_CREATED = "staff_created"  # Tạo tài khoản nhân viên
    STAFF_UPDATED = "staff_updated"  # Sửa tên nhân viên
    STAFF_DISABLED = "staff_disabled"  # Khóa tài khoản nhân viên
    STAFF_ENABLED = "staff_enabled"  # Mở khóa tài khoản nhân viên
    STAFF_PASSWORD_RESET = "staff_password_reset"  # Đặt lại mật khẩu nhân viên
    SESSION_REVOKED = "session_revoked"  # Đăng xuất từ xa một phiên
    PASSWORD_RESET_REQUESTED = "password_reset_requested"  # Gửi mã quên mật khẩu
    PASSWORD_RESET_DONE = "password_reset_done"  # Đặt lại mật khẩu bằng mã
    PHONE_VERIFIED = "phone_verified"  # Khách Google xác minh SĐT, gắn vào tài khoản
    ACCOUNT_MERGED = "account_merged"  # SĐT đã có tài khoản ⇒ gắn Google vào tài khoản đó


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # NULL = Hệ thống
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", values_callable=lambda e: [m.value for m in e])
    )
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    detail: Mapped[str | None] = mapped_column(String(255))  # vd "Khóa đến 14:35"


class LoginFailure(Base):
    """Một lần đăng nhập sai theo IP (giới hạn theo IP)."""

    __tablename__ = "login_failures"
    __table_args__ = (Index("ix_login_failures_ip_created_at", "ip", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45))  # đủ cho IPv6
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class RegisterRequest(Base):
    """Một lần gọi đăng ký theo IP (giới hạn theo IP, cả lần 409)."""

    __tablename__ = "register_requests"
    __table_args__ = (Index("ix_register_requests_ip_created_at", "ip", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ip: Mapped[str] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class OtpPurpose(enum.StrEnum):
    PASSWORD_RESET = "password_reset"  # quên mật khẩu (chưa đăng nhập)
    PHONE_VERIFY = "phone_verify"  # khách đã đăng nhập gắn SĐT vào tài khoản


class PasswordResetCode(Base):
    """Mã OTP (hash): quên mật khẩu ⇒ reset token; xác minh SĐT ⇒ gắn `phone`."""

    __tablename__ = "password_reset_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(
        Enum(OtpPurpose, name="otp_purpose", values_callable=lambda e: [m.value for m in e]),
        default=OtpPurpose.PASSWORD_RESET,
        server_default=OtpPurpose.PASSWORD_RESET.value,
    )
    # SĐT nhận mã
    phone: Mapped[str] = mapped_column(String(20))
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256(SECRET_KEY, mã)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reset_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip: Mapped[str | None] = mapped_column(String(45))


class PasswordResetRequest(Base):
    """Một lần yêu cầu gửi mã theo SĐT/IP (giới hạn gửi + lượt nhập mã giả)."""

    __tablename__ = "password_reset_requests"
    __table_args__ = (
        Index("ix_password_reset_requests_phone_created_at", "phone", "created_at"),
        Index("ix_password_reset_requests_ip_created_at", "ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20))
    ip: Mapped[str | None] = mapped_column(String(45))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

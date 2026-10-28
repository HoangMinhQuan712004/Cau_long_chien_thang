"""auth accounts: đăng nhập SĐT/tên/Google, phiên quản trị, audit, OTP, nhân viên, giới hạn IP

Revision ID: f1daccdae98d
Revises: b0a6ee0cf64c
Create Date: 2026-10-28 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1daccdae98d"
down_revision: str | None = "b0a6ee0cf64c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENUMS = {
    "session_end_reason": ("logout", "password_changed", "account_disabled", "revoked_by_admin"),
    "audit_action": (
        "login_success",
        "login_locked",
        "login_blocked",
        "logout",
        "staff_created",
        "staff_updated",
        "staff_disabled",
        "staff_enabled",
        "staff_password_reset",
        "session_revoked",
        "password_reset_requested",
        "password_reset_done",
        "phone_verified",
        "account_merged",
    ),
    "otp_purpose": ("password_reset", "phone_verify"),
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*_ENUMS[name], name=name, create_type=False)


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _ip_table(name: str) -> None:
    """Bảng đếm theo IP (lần đăng nhập sai / lần gọi đăng ký)."""
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
    )
    op.create_index(op.f(f"ix_{name}_created_at"), name, ["created_at"], unique=False)
    op.create_index(f"ix_{name}_ip_created_at", name, ["ip", "created_at"], unique=False)


def _upgrade_users() -> None:
    """users: bỏ email, thêm tên đăng nhập / khóa / Google / mã nhân viên; chuyển dữ liệu cũ."""
    op.add_column("users", sa.Column("username", sa.String(length=50), nullable=True))
    op.add_column(
        "users", sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_phone"), table_name="users")
    # SĐT cũ lưu tự do ⇒ chuẩn hóa 0xxxxxxxxx; không chuẩn hóa được ⇒ bỏ
    op.execute(
        r"""
        UPDATE users u SET phone = CASE
            WHEN u.phone !~ '^\+?[0-9\s.\-]+$' THEN NULL
            WHEN n.digits ~ '^0[0-9]{9}$' THEN n.digits
            WHEN n.digits ~ '^84[0-9]{9}$' THEN '0' || substr(n.digits, 3)
            ELSE NULL
        END
        FROM (
            SELECT id, regexp_replace(phone, '[^0-9]', '', 'g') AS digits
            FROM users WHERE phone IS NOT NULL
        ) n
        WHERE u.id = n.id
        """
    )
    # SĐT trùng chỉ giữ ở tài khoản cũ nhất; không còn SĐT ⇒ tên đăng nhập từ email + id
    op.execute(
        """
        UPDATE users u SET phone = NULL
        WHERE phone IS NOT NULL
          AND EXISTS (SELECT 1 FROM users o WHERE o.phone = u.phone AND o.id < u.id)
        """
    )
    op.execute(
        """
        UPDATE users
        SET username = left(lower(split_part(email, '@', 1)), 49 - length(id::text)) || '_' || id
        WHERE phone IS NULL AND username IS NULL
        """
    )
    op.create_unique_constraint(op.f("uq_users_phone"), "users", ["phone"])
    op.create_unique_constraint(op.f("uq_users_username"), "users", ["username"])
    op.drop_column("users", "email")
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("google_email", sa.String(length=255), nullable=True))
    op.alter_column("users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])
    op.create_check_constraint(
        op.f("ck_users_login_id"),
        "users",
        "phone IS NOT NULL OR username IS NOT NULL OR google_sub IS NOT NULL",
    )
    # Mã nhân viên NV001… theo id; mã kế tiếp = số nhân viên + 1
    op.execute("CREATE SEQUENCE staff_code_seq")
    op.add_column("users", sa.Column("staff_code", sa.String(length=20), nullable=True))
    op.create_unique_constraint(op.f("uq_users_staff_code"), "users", ["staff_code"])
    op.execute(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY id) AS n FROM users WHERE role = 'staff'
        )
        UPDATE users u
        SET staff_code = 'NV' || CASE WHEN n < 1000 THEN lpad(n::text, 3, '0') ELSE n::text END
        FROM numbered WHERE u.id = numbered.id
        """
    )
    op.execute(
        "SELECT setval('staff_code_seq', GREATEST(count(*), 1), count(*) > 0) "
        "FROM users WHERE role = 'staff'"
    )
    # Nhân viên cũ đăng nhập bằng SĐT (chưa có tên) ⇒ tên đăng nhập = mã (`nv001`)
    op.execute(
        "UPDATE users SET username = lower(staff_code) WHERE role = 'staff' AND username IS NULL"
    )


def upgrade() -> None:
    for name, values in _ENUMS.items():
        postgresql.ENUM(*values, name=name).create(op.get_bind())
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", _enum("session_end_reason"), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_admin_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_sessions_token_hash")),
    )
    op.create_index(op.f("ix_admin_sessions_user_id"), "admin_sessions", ["user_id"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        _created_at(),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("action", _enum("audit_action"), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_target_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    _upgrade_users()
    _ip_table("login_failures")
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_requests")),
    )
    op.create_index(
        op.f("ix_password_reset_requests_created_at"),
        "password_reset_requests",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_ip_created_at",
        "password_reset_requests",
        ["ip", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_phone_created_at",
        "password_reset_requests",
        ["phone", "created_at"],
        unique=False,
    )
    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_token_hash", sa.String(length=64), nullable=True),
        sa.Column("reset_expires_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("purpose", _enum("otp_purpose"), server_default="password_reset", nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_codes")),
        sa.UniqueConstraint(
            "reset_token_hash", name=op.f("uq_password_reset_codes_reset_token_hash")
        ),
    )
    op.create_index(
        op.f("ix_password_reset_codes_user_id"), "password_reset_codes", ["user_id"], unique=False
    )
    _ip_table("register_requests")


def downgrade() -> None:
    for name in ("register_requests", "password_reset_codes", "password_reset_requests"):
        op.drop_table(name)
    op.drop_table("login_failures")
    # Tài khoản không mật khẩu (Google) không có ở schema cũ ⇒ xóa (đơn giữ, customer_id NULL)
    op.execute("DELETE FROM users WHERE hashed_password IS NULL")
    op.drop_constraint(op.f("ck_users_login_id"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_staff_code"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_username"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_phone"), "users", type_="unique")
    for column in (
        "staff_code",
        "google_email",
        "google_sub",
        "token_version",
        "locked_until",
        "failed_login_count",
        "username",
    ):
        op.drop_column("users", column)
    op.execute("DROP SEQUENCE staff_code_seq")
    op.alter_column(
        "users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=False
    )
    # Email không khôi phục được: giá trị giả duy nhất cho NOT NULL + unique
    op.add_column("users", sa.Column("email", sa.VARCHAR(length=255), nullable=True))
    op.execute("UPDATE users SET email = 'user' || id || '@khong-co-email.invalid'")
    op.alter_column("users", "email", nullable=False)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=False)
    op.drop_table("audit_logs")
    op.drop_table("admin_sessions")
    for name in _ENUMS:
        op.execute(f"DROP TYPE {name}")

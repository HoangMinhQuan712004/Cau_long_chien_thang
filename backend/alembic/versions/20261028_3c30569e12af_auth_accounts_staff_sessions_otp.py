"""auth accounts staff sessions otp

T-013 (ADR-008, port PR #17): đăng nhập SĐT / tên đăng nhập / Google, phiên quản trị phía server,
mã OTP, nhiều tài khoản nhân viên (NV001…). Thứ tự chuyển dữ liệu theo T-013 AC32:
1. chuẩn hóa ``phone`` (không hợp lệ -> NULL; trùng -> giữ id nhỏ nhất);
2. Admin chưa có SĐT -> ``FIRST_ADMIN_PHONE`` (thiếu / sai / đã có chủ -> DỪNG, không đổi gì);
3. user không có SĐT -> ``username`` từ email + id;
4. nhân viên -> ``NV001``… theo id, ``username = lower(staff_code)``;
5. ``email`` cho phép NULL (giữ dữ liệu); 6. Admin / nhân viên có SĐT coi như đã xác minh.

Revision ID: 3c30569e12af
Revises: cc9af0a8c694
Create Date: 2026-10-28 22:47:53.248237

"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision: str = "3c30569e12af"
down_revision: str | None = "cc9af0a8c694"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _normalize_phone(raw: str) -> str | None:
    """Như app: bỏ khoảng trắng / chấm / gạch, ``+84`` -> ``0``; phải là ``0`` + 9 số."""
    if not raw or not re.fullmatch(r"\+?[\d\s.\-]+", raw.strip()):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if re.fullmatch(r"0\d{9}", digits) else None


def _upgrade_users() -> None:
    conn = op.get_bind()
    for name, column in (
        ("phone_verified_at", sa.DateTime(timezone=True)),
        ("username", sa.String(length=50)),
        ("staff_code", sa.String(length=20)),
        ("google_sub", sa.String(length=255)),
        ("google_email", sa.String(length=255)),
        ("locked_until", sa.DateTime(timezone=True)),
    ):
        op.add_column("users", sa.Column(name, column, nullable=True))
    op.add_column(
        "users", sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.alter_column("users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=True)
    op.drop_index(op.f("ix_users_phone"), table_name="users")

    # 1. SĐT cũ lưu tự do -> 0xxxxxxxxx; không chuẩn hóa được -> NULL; trùng -> giữ id nhỏ nhất
    op.execute(
        """
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
    op.execute(
        """
        UPDATE users u SET phone = NULL
        WHERE phone IS NOT NULL
          AND EXISTS (SELECT 1 FROM users o WHERE o.phone = u.phone AND o.id < u.id)
        """
    )

    # 2. Admin cũ (đăng nhập email) -> FIRST_ADMIN_PHONE cho Admin id nhỏ nhất chưa có SĐT.
    #    Lỗi -> raise: cả migration rollback (DDL có transaction), dữ liệu không đổi.
    admin_id = conn.scalar(
        sa.text("SELECT min(id) FROM users WHERE role = 'admin' AND phone IS NULL")
    )
    if admin_id is not None:
        phone = _normalize_phone(settings.FIRST_ADMIN_PHONE or "")
        if phone is None:
            raise RuntimeError(
                "Migration dừng: biến FIRST_ADMIN_PHONE thiếu hoặc không phải SĐT di động "
                "Việt Nam 10 số – cần để gán cho tài khoản Admin chưa có SĐT. "
                "Đặt biến trong .env rồi chạy lại."
            )
        owner = conn.scalar(sa.text("SELECT id FROM users WHERE phone = :p"), {"p": phone})
        if owner is not None:
            raise RuntimeError(
                "Migration dừng: SĐT trong FIRST_ADMIN_PHONE đã thuộc một tài khoản khác. "
                "Dùng SĐT khác cho Admin rồi chạy lại."
            )
        conn.execute(
            sa.text("UPDATE users SET phone = :p WHERE id = :id"), {"p": phone, "id": admin_id}
        )

    # 3. Không có SĐT (không phải nhân viên) -> tên đăng nhập từ email + id
    op.execute(
        """
        UPDATE users
        SET username = left(lower(split_part(email, '@', 1)), 49 - length(id::text)) || '_' || id
        WHERE phone IS NULL AND username IS NULL AND role <> 'staff'
        """
    )

    # 4. Nhân viên hiện có ("Tài khoản tại máy") -> NV001… theo id; tên đăng nhập = mã chữ thường
    op.execute("CREATE SEQUENCE staff_code_seq")
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
    op.execute("UPDATE users SET username = lower(staff_code) WHERE role = 'staff'")

    # 6. Admin / nhân viên có SĐT: coi như đã xác minh (không cần OTP để đăng nhập)
    op.execute(
        "UPDATE users SET phone_verified_at = now() "
        "WHERE phone IS NOT NULL AND role IN ('admin', 'staff')"
    )

    op.create_unique_constraint(op.f("uq_users_phone"), "users", ["phone"])
    op.create_unique_constraint(op.f("uq_users_username"), "users", ["username"])
    op.create_unique_constraint(op.f("uq_users_staff_code"), "users", ["staff_code"])
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])
    op.create_check_constraint(
        op.f("ck_users_login_id"),
        "users",
        "phone IS NOT NULL OR username IS NOT NULL OR google_sub IS NOT NULL",
    )


def upgrade() -> None:
    _upgrade_users()
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked_reason",
            sa.Enum(
                "logout",
                "expired",
                "password_changed",
                "account_disabled",
                "revoked_by_admin",
                name="session_end_reason",
            ),
            nullable=True,
        ),
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
        "otp_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("password_reset", "phone_verify", "booking_phone", name="otp_purpose"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_otp_codes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_codes")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_otp_codes_token_hash")),
    )
    op.create_index(op.f("ix_otp_codes_phone"), "otp_codes", ["phone"], unique=False)
    op.create_index(
        "ix_otp_codes_phone_purpose_created_at",
        "otp_codes",
        ["phone", "purpose", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_otp_codes_phone_purpose_created_at", table_name="otp_codes")
    op.drop_index(op.f("ix_otp_codes_phone"), table_name="otp_codes")
    op.drop_table("otp_codes")
    op.drop_index(op.f("ix_admin_sessions_user_id"), table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.execute("DROP TYPE IF EXISTS otp_purpose")
    op.execute("DROP TYPE IF EXISTS session_end_reason")

    # Tài khoản chỉ có Google (không mật khẩu) không có trong schema cũ -> xóa
    op.execute("DELETE FROM users WHERE hashed_password IS NULL")
    # Tài khoản tạo sau migration không có email -> email giả để trả NOT NULL
    op.execute(
        "UPDATE users SET email = 'user' || id || '@khong-co-email.invalid' WHERE email IS NULL"
    )
    op.drop_constraint(op.f("ck_users_login_id"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_staff_code"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_username"), "users", type_="unique")
    op.drop_constraint(op.f("uq_users_phone"), "users", type_="unique")
    op.create_index(op.f("ix_users_phone"), "users", ["phone"], unique=False)
    op.alter_column(
        "users", "hashed_password", existing_type=sa.VARCHAR(length=255), nullable=False
    )
    op.alter_column("users", "email", existing_type=sa.VARCHAR(length=255), nullable=False)
    for name in (
        "token_version",
        "locked_until",
        "failed_login_count",
        "google_email",
        "google_sub",
        "staff_code",
        "username",
        "phone_verified_at",
    ):
        op.drop_column("users", name)
    op.execute("DROP SEQUENCE IF EXISTS staff_code_seq")

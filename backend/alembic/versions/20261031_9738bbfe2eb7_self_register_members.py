"""self register members

T-021 (ADR-009 sửa đổi 31/10): tài khoản web có SĐT đã xác minh OTP = hội viên.

- ``otp_purpose`` thêm ``register``; bảng ``registration_requests`` giữ dữ liệu đăng ký chờ OTP
  (họ tên, mật khẩu đã băm) – chưa tạo tài khoản cho tới khi nhập mã đúng.
- ``ck_users_login_id`` cho phép tài khoản **vô hiệu** không còn cách đăng nhập: tài khoản chưa
  xác minh đời cũ bị gỡ SĐT khi người khác xác minh OTP số đó (AC3).
- ``customer.source``: ``counter`` (quầy / Admin) | ``self_register`` ("Tự đăng ký online").
- Backfill một lần (AC7): mọi tài khoản ``member`` đang hoạt động có SĐT đã xác minh mà chưa có
  hồ sơ hội viên -> tạo hội viên mới hoặc nâng hồ sơ tạm cùng SĐT (giữ lịch sử), ghi nhật ký.

Downgrade: bỏ cột / bảng / giá trị enum; hội viên đã tạo / nâng bởi backfill **giữ nguyên** (là
dữ liệu nghiệp vụ hợp lệ), ràng buộc ``login_id`` cũ khôi phục ở dạng ``NOT VALID`` để không
phải xóa tài khoản đã vô hiệu.

Revision ID: 9738bbfe2eb7
Revises: 5b98d354dd77
Create Date: 2026-10-31 11:02:56.081151

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9738bbfe2eb7"
down_revision: str | None = "5b98d354dd77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_LOGIN_ID = "phone IS NOT NULL OR username IS NOT NULL OR google_sub IS NOT NULL"
NEW_LOGIN_ID = f"{OLD_LOGIN_ID} OR NOT is_active"
CODE_MAX = 9999
NAME_MAX = 100


def _detail(code: str, name: str, phone: str, upgraded: bool) -> str:
    """Định dạng Lịch sử thao tác (PR #22): đối tượng + các ô "trước → sau"."""
    first = (
        {"field": "Loại hồ sơ", "before": "Hồ sơ tạm", "after": "Hội viên"}
        if upgraded
        else {"field": "Họ tên", "before": None, "after": name}
    )
    return json.dumps(
        {
            "target": {"code": code, "name": name},
            "changes": [first, {"field": "Mã HV", "before": None, "after": code}],
            "member_code": code,
            "phone": f"{phone[:4]} xxx {phone[-3:]}",  # SĐT che (T-021 AC10)
            "source": "self_register",
            "backfill": True,
        },
        ensure_ascii=False,
    )


def _backfill() -> None:
    conn = op.get_bind()
    users = conn.execute(
        sa.text(
            "SELECT u.id, u.phone, u.full_name, c.id AS customer_id, c.kind, c.full_name AS cname"
            " FROM users u LEFT JOIN customer c ON c.phone = u.phone"
            " WHERE u.role = 'member' AND u.is_active AND u.phone IS NOT NULL"
            " AND u.phone_verified_at IS NOT NULL AND u.phone ~ '^0[0-9]{9}$'"
            " AND (c.id IS NULL OR c.kind = 'temp')"
            " ORDER BY u.phone_verified_at, u.id"
        )
    ).all()
    if not users:
        return
    last = conn.scalar(sa.text("SELECT max(member_code) FROM customer"))
    number = int(last[2:]) if last else 0
    for u in users:
        number += 1
        if number > CODE_MAX:
            raise RuntimeError("Hết mã hội viên (HV9999) khi backfill T-021")
        code = f"HV{number:04d}"
        if u.customer_id is not None:
            conn.execute(
                sa.text(
                    "UPDATE customer SET kind = 'member', member_code = :code,"
                    " source = 'self_register', created_at = now(), version = version + 1"
                    " WHERE id = :id"
                ),
                {"code": code, "id": u.customer_id},
            )
            action, name, upgraded = "member.auto_upgrade_temp", u.cname, True
        else:
            name = " ".join((u.full_name or "").split())[:NAME_MAX] or "Hội viên"
            conn.execute(
                sa.text(
                    "INSERT INTO customer (kind, member_code, full_name, phone, is_active, source)"
                    " VALUES ('member', :code, :name, :phone, true, 'self_register')"
                ),
                {"code": code, "name": name, "phone": u.phone},
            )
            action, upgraded = "member.self_register", False
        conn.execute(
            sa.text(
                "INSERT INTO audit_log (actor_type, actor_id, actor_label, action, entity_type,"
                " entity_code, detail)"
                " VALUES ('system', NULL, 'Hệ thống', :action, 'customer', :code,"
                " CAST(:detail AS jsonb))"
            ),
            {
                "action": action,
                "code": code,
                "detail": _detail(code, name, u.phone, upgraded),
            },
        )


def upgrade() -> None:
    # ADD VALUE không chạy được trong transaction khi giá trị được dùng ngay -> autocommit block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE otp_purpose ADD VALUE IF NOT EXISTS 'register'")
    op.create_table(
        "registration_requests",
        sa.Column("otp_code_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["otp_code_id"],
            ["otp_codes.id"],
            name=op.f("fk_registration_requests_otp_code_id_otp_codes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("otp_code_id", name=op.f("pk_registration_requests")),
    )
    op.drop_constraint(op.f("ck_users_login_id"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_login_id"), "users", NEW_LOGIN_ID)
    op.add_column(
        "customer",
        sa.Column(
            "source", sa.String(length=20), server_default=sa.text("'counter'"), nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_customer_source"), "customer", "source IN ('counter', 'self_register')"
    )
    _backfill()


def downgrade() -> None:
    op.drop_constraint(op.f("ck_customer_source"), "customer", type_="check")
    op.drop_column("customer", "source")
    op.drop_constraint(op.f("ck_users_login_id"), "users", type_="check")
    # Tài khoản đã vô hiệu vì bị gỡ SĐT (AC3) không thỏa ràng buộc cũ -> NOT VALID, không xóa
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT ck_users_login_id CHECK ({OLD_LOGIN_ID}) NOT VALID"
    )
    op.drop_table("registration_requests")
    # Bỏ giá trị enum: dựng lại kiểu không có 'register' (mã đăng ký chờ xóa luôn)
    op.execute("DELETE FROM otp_codes WHERE purpose = 'register'")
    op.execute("ALTER TYPE otp_purpose RENAME TO otp_purpose_old")
    op.execute(
        "CREATE TYPE otp_purpose AS ENUM ('password_reset', 'phone_verify', 'booking_phone')"
    )
    op.execute(
        "ALTER TABLE otp_codes ALTER COLUMN purpose TYPE otp_purpose"
        " USING purpose::text::otp_purpose"
    )
    op.execute("DROP TYPE otp_purpose_old")

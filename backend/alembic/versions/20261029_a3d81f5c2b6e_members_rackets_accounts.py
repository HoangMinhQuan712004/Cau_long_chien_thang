"""members rackets accounts

T-014 (màn Hội viên) + T-015 (tài khoản hội viên), gộp 5 migration của nhánh ``future/hoivien``:

- ``customer``: ``gender``, ``racket`` (tên vợt dạng chữ), ``public_id`` (mã tham chiếu mờ của hồ
  sơ tạm – API không lộ id); "Hạng" thành trình độ chơi (Yếu … Chuyên nghiệp, NULL = chưa xếp
  hạng) – hạng ưu đãi cũ Vàng/Bạc/Đồng -> NULL; index lọc ``(kind, is_active)``.
- ``booking``: index đếm lượt ``(tenant_id, customer_ref)``; snapshot ``member_tier`` (booking /
  checkout / ticket) nới 20 ký tự – snapshot cũ giữ nguyên.
- ``racket``: danh mục vợt, ``name_key`` = tên gộp khoảng trắng + chữ thường (duy nhất).
- ``users``: ``must_change_password`` (tài khoản hội viên do sân tạo, mật khẩu ban đầu = SĐT),
  ``member_account_at``; vai ``customer`` đổi tên thành ``member`` (``audit_log.actor_type`` vẫn
  ghi ``customer`` – map ở ``auth.sessions.actor_type_of``).

Revision ID: a3d81f5c2b6e
Revises: 3c30569e12af
Create Date: 2026-10-29 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3d81f5c2b6e"
down_revision: str | None = "3c30569e12af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TIERS = (
    "tier IS NULL OR tier IN ('Yếu', 'Trung bình yếu', 'Trung bình -', 'Trung bình', "
    "'Trung bình +', 'Khá', 'Bán chuyên', 'Chuyên nghiệp')"
)
OLD_TIERS = "tier IS NULL OR tier IN ('Vàng', 'Bạc', 'Đồng')"
SNAPSHOT_TABLES = ("booking", "checkout", "ticket")


def _resize_member_tier(length: int, using: str | None = None) -> None:
    for table in SNAPSHOT_TABLES:
        op.alter_column(
            table,
            "member_tier",
            type_=sa.String(length=length),
            existing_nullable=True,
            postgresql_using=using,
            schema="booking",
        )


def upgrade() -> None:
    # ---- customer (hồ sơ hội viên / tạm)
    op.add_column("customer", sa.Column("gender", sa.String(length=6), nullable=True))
    op.add_column("customer", sa.Column("racket", sa.String(length=100), nullable=True))
    op.add_column(
        "customer",
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(op.f("uq_customer_public_id"), "customer", ["public_id"])
    op.drop_constraint(op.f("ck_customer_tier"), "customer", type_="check")
    op.execute("UPDATE customer SET tier = NULL WHERE tier IS NOT NULL")  # hạng ưu đãi cũ
    op.alter_column("customer", "tier", type_=sa.String(length=20), existing_nullable=True)
    op.create_check_constraint(op.f("ck_customer_tier"), "customer", NEW_TIERS)
    op.create_check_constraint(
        op.f("ck_customer_gender"), "customer", "gender IS NULL OR gender IN ('male', 'female')"
    )
    op.create_index("ix_customer_kind_is_active", "customer", ["kind", "is_active"])

    # ---- booking engine
    op.create_index(
        "ix_booking_tenant_customer_ref", "booking", ["tenant_id", "customer_ref"], schema="booking"
    )
    _resize_member_tier(20)

    # ---- danh mục vợt
    op.create_table(
        "racket",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("name_key", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_racket")),
        sa.UniqueConstraint("name_key", name=op.f("uq_racket_name_key")),
    )

    # ---- tài khoản
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )
    op.add_column(
        "users", sa.Column("member_account_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("ALTER TYPE user_role RENAME VALUE 'customer' TO 'member'")


def downgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'member' TO 'customer'")
    op.drop_column("users", "member_account_at")
    op.drop_column("users", "must_change_password")

    op.drop_table("racket")

    _resize_member_tier(10, using="left(member_tier, 10)")
    op.drop_index("ix_booking_tenant_customer_ref", table_name="booking", schema="booking")

    op.drop_index("ix_customer_kind_is_active", table_name="customer")
    op.drop_constraint(op.f("ck_customer_gender"), "customer", type_="check")
    op.drop_constraint(op.f("ck_customer_tier"), "customer", type_="check")
    op.execute("UPDATE customer SET tier = NULL WHERE tier IS NOT NULL")  # trình độ -> không có
    op.alter_column("customer", "tier", type_=sa.String(length=10), existing_nullable=True)
    op.create_check_constraint(op.f("ck_customer_tier"), "customer", OLD_TIERS)
    op.drop_constraint(op.f("uq_customer_public_id"), "customer", type_="unique")
    op.drop_column("customer", "public_id")
    op.drop_column("customer", "racket")
    op.drop_column("customer", "gender")

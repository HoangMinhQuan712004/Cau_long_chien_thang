"""member area profile avatar

T-016 (ADR-009, sửa đổi 30/10 – nền PR #21): khu hội viên trên web. Chỉ thêm phần dev chưa có:
``customer.nickname`` (≤ 20), ``email`` (≤ 254, unique theo ``lower(email)`` khi có),
``show_on_records`` (mặc định Tắt), ``version`` (khóa lạc quan Hồ sơ của tôi) và bảng
``customer_avatar`` (ảnh đã mã hóa lại, lưu trong DB). Liên kết tài khoản theo SĐT như dev.

Revision ID: dad220bfc992
Revises: a3d81f5c2b6e
Create Date: 2026-10-30 14:23:23.862942

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dad220bfc992"
down_revision: str | None = "a3d81f5c2b6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("nickname", sa.String(length=20), nullable=True))
    op.add_column("customer", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column(
        "customer",
        sa.Column("show_on_records", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "customer", sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )
    op.create_index(
        "uq_customer_email_lower",
        "customer",
        [sa.literal_column("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_table(
        "customer_avatar",
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=30), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("etag", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customer.id"],
            name=op.f("fk_customer_avatar_customer_id_customer"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("customer_id", name=op.f("pk_customer_avatar")),
    )


def downgrade() -> None:
    op.drop_table("customer_avatar")
    op.drop_index("uq_customer_email_lower", table_name="customer")
    op.drop_column("customer", "version")
    op.drop_column("customer", "show_on_records")
    op.drop_column("customer", "email")
    op.drop_column("customer", "nickname")

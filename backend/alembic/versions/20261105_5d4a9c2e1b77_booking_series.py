"""booking_series: gói đặt theo tháng (quầy) + booking_order.series_id

Mỗi ngày của gói là một đơn bình thường (một booking); ``series_id`` NULL = đơn lẻ.

Revision ID: 5d4a9c2e1b77
Revises: 8b2e5d1c7f63
Create Date: 2026-11-05 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5d4a9c2e1b77"
down_revision: str | None = "8b2e5d1c7f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
S = "booking"


def upgrade() -> None:
    op.create_table(
        "booking_series",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("start_hour", sa.SmallInteger(), nullable=False),
        sa.Column("end_hour", sa.SmallInteger(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_by_type", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_label", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("customer_ref", sa.String(length=40), nullable=False),
        sa.Column("customer_kind", sa.String(length=10), nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=15), nullable=False),
        sa.Column("member_code", sa.String(length=10), nullable=True),
        sa.Column("member_tier", sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled', 'completed')", name=op.f("ck_booking_series_status")
        ),
        sa.CheckConstraint(
            "start_hour >= 0 AND start_hour < end_hour AND end_hour <= 24",
            name=op.f("ck_booking_series_hours"),
        ),
        sa.CheckConstraint("total >= 0", name=op.f("ck_booking_series_total_non_negative")),
        sa.CheckConstraint(
            "customer_kind IN ('member', 'temp')", name=op.f("ck_booking_series_customer_kind")
        ),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            [f"{S}.resource.id"],
            name=op.f("fk_booking_series_resource_id_resource"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{S}.tenant.id"],
            name=op.f("fk_booking_series_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_series")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_booking_series_tenant_id")),
        schema=S,
    )
    op.create_index(
        op.f("ix_booking_booking_series_resource_id"), "booking_series", ["resource_id"], schema=S
    )
    op.add_column("booking_order", sa.Column("series_id", sa.BigInteger(), nullable=True), schema=S)
    op.create_index(
        op.f("ix_booking_booking_order_series_id"), "booking_order", ["series_id"], schema=S
    )
    op.create_foreign_key(
        op.f("fk_booking_order_series_id_booking_series"),
        "booking_order",
        "booking_series",
        ["series_id"],
        ["id"],
        source_schema=S,
        referent_schema=S,
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_booking_order_series_id_booking_series"),
        "booking_order",
        schema=S,
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_booking_booking_order_series_id"), table_name="booking_order", schema=S)
    op.drop_column("booking_order", "series_id", schema=S)
    op.drop_index(
        op.f("ix_booking_booking_series_resource_id"), table_name="booking_series", schema=S
    )
    op.drop_table("booking_series", schema=S)

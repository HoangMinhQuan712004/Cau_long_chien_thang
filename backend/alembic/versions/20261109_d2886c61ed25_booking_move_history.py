"""Lịch sử đổi sân của booking: bảng ``booking.booking_move`` (lịch cũ -> mới, ai, lúc nào)

Revision ID: d2886c61ed25
Revises: e3a17c9b5d24
Create Date: 2026-11-09 15:28:35.013649

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2886c61ed25"
down_revision: str | None = "e3a17c9b5d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "booking_move",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.SmallInteger(), nullable=False),
        sa.Column("booking_id", sa.BigInteger(), nullable=False),
        sa.Column("from_resource_id", sa.Integer(), nullable=False),
        sa.Column("to_resource_id", sa.Integer(), nullable=False),
        sa.Column("from_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("to_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "moved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("moved_by_type", sa.String(length=20), nullable=False),
        sa.Column("moved_by_id", sa.BigInteger(), nullable=True),
        sa.Column("moved_by_label", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["booking.booking.id"],
            name=op.f("fk_booking_move_booking_id_booking"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_resource_id"],
            ["booking.resource.id"],
            name=op.f("fk_booking_move_from_resource_id_resource"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["booking.tenant.id"],
            name=op.f("fk_booking_move_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_resource_id"],
            ["booking.resource.id"],
            name=op.f("fk_booking_move_to_resource_id_resource"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_move")),
        schema="booking",
    )
    op.create_index(
        op.f("ix_booking_booking_move_booking_id"),
        "booking_move",
        ["booking_id"],
        unique=False,
        schema="booking",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_booking_booking_move_booking_id"), table_name="booking_move", schema="booking"
    )
    op.drop_table("booking_move", schema="booking")

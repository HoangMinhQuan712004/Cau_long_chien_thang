"""speed records (T-030)

Module Kỷ lục: bảng ``speed_record`` (số đo tốc độ cú đập, 50–500 km/h, ``source_ref`` unique).
``customer_id`` không FK chéo module. Giai đoạn A không có dữ liệu thật – không backfill.

Revision ID: ee7aaa89b694
Revises: 9f73fd765c58
Create Date: 2026-11-02 17:40:24.970496

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ee7aaa89b694"
down_revision: str | None = "9f73fd765c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "speed_record",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("speed_kmh", sa.Integer(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("court_code", sa.String(length=10), nullable=True),
        sa.Column("device_id", sa.String(length=50), nullable=True),
        sa.Column("source_ref", sa.String(length=100), nullable=False),
        sa.Column("video_url", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "speed_kmh BETWEEN 50 AND 500", name=op.f("ck_speed_record_speed_range")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_speed_record")),
        sa.UniqueConstraint("source_ref", name=op.f("uq_speed_record_source_ref")),
    )
    op.create_index(
        "ix_speed_record_customer_speed",
        "speed_record",
        ["customer_id", sa.literal_column("speed_kmh DESC")],
        unique=False,
    )
    op.create_index("ix_speed_record_measured_at", "speed_record", ["measured_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_speed_record_measured_at", table_name="speed_record")
    op.drop_index("ix_speed_record_customer_speed", table_name="speed_record")
    op.drop_table("speed_record")

"""speed record source + review (T-047)

Số đo nhập tay: ``source`` (``device`` | ``admin`` | ``member``) + ``status`` (``approved`` |
``pending`` | ``rejected``), người gửi / người duyệt, lý do từ chối, ``updated_at`` + ``version``
(chống ghi đè khi sửa). Bản ghi cũ: ``device`` / ``approved``, ``updated_at = created_at``. Index
``(status, measured_at)`` cho mọi truy vấn chỉ lấy bản đã duyệt.

Revision ID: 5b7e2c9d41a3
Revises: 73296951e195
Create Date: 2026-11-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b7e2c9d41a3"
down_revision: str | None = "73296951e195"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "speed_record"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "source", sa.String(length=10), server_default=sa.text("'device'"), nullable=False
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'approved'"), nullable=False
        ),
    )
    op.add_column(TABLE, sa.Column("submitted_by", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("reject_reason", sa.String(length=200), nullable=True))
    op.add_column(
        TABLE,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        TABLE, sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
    )
    # Bản ghi cũ: lần sửa cuối = lúc tạo
    op.execute(f"UPDATE {TABLE} SET updated_at = created_at")
    op.create_check_constraint(
        op.f("ck_speed_record_speed_source"), TABLE, "source IN ('device', 'admin', 'member')"
    )
    op.create_check_constraint(
        op.f("ck_speed_record_speed_status"), TABLE, "status IN ('approved', 'pending', 'rejected')"
    )
    op.create_check_constraint(
        op.f("ck_speed_record_speed_reject_reason"),
        TABLE,
        "status <> 'rejected' OR reject_reason IS NOT NULL",
    )
    op.create_index(
        "ix_speed_record_status_measured_at", TABLE, ["status", "measured_at"], unique=False
    )


def downgrade() -> None:
    # Bản chờ duyệt / bị từ chối chưa từng được tính – bỏ đi (bảng cũ chỉ có số đo hợp lệ)
    op.execute(f"DELETE FROM {TABLE} WHERE status <> 'approved'")
    op.drop_index("ix_speed_record_status_measured_at", table_name=TABLE)
    op.drop_constraint(op.f("ck_speed_record_speed_reject_reason"), TABLE, type_="check")
    op.drop_constraint(op.f("ck_speed_record_speed_status"), TABLE, type_="check")
    op.drop_constraint(op.f("ck_speed_record_speed_source"), TABLE, type_="check")
    for column in (
        "version",
        "updated_at",
        "reject_reason",
        "reviewed_at",
        "reviewed_by",
        "submitted_by",
        "status",
        "source",
    ):
        op.drop_column(TABLE, column)

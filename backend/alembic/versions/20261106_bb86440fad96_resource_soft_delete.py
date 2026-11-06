"""Xóa sân: ``resource.deleted_at``; tên chỉ unique trong các sân chưa xóa

Revision ID: bb86440fad96
Revises: bf1c6f8fad0d
Create Date: 2026-11-06 14:09:36.534570

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb86440fad96"
down_revision: str | None = "bf1c6f8fad0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resource",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        schema="booking",
    )
    # Sân đã xóa nhường lại tên; mã thì vẫn unique, không dùng lại
    op.drop_index("uq_resource_tenant_id_lower_name", table_name="resource", schema="booking")
    op.create_index(
        "uq_resource_tenant_id_lower_name",
        "resource",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        schema="booking",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Lỗi nếu đã có sân mới trùng tên sân đã xóa: phải đổi tên trước khi hạ
    op.drop_index("uq_resource_tenant_id_lower_name", table_name="resource", schema="booking")
    op.create_index(
        "uq_resource_tenant_id_lower_name",
        "resource",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
        schema="booking",
    )
    op.drop_column("resource", "deleted_at", schema="booking")

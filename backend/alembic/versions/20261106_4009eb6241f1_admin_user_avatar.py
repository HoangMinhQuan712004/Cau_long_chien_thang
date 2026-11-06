"""Ảnh đại diện tài khoản quản trị: bảng ``user_avatar`` (Admin / NV, mẫu ``customer_avatar``)

Revision ID: 4009eb6241f1
Revises: d5cf1587486a
Create Date: 2026-11-06 10:52:55.270251

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4009eb6241f1"
down_revision: str | None = "d5cf1587486a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_avatar",
        sa.Column("user_id", sa.Integer(), nullable=False),
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
            ["user_id"], ["users.id"], name=op.f("fk_user_avatar_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_avatar")),
    )


def downgrade() -> None:
    op.drop_table("user_avatar")

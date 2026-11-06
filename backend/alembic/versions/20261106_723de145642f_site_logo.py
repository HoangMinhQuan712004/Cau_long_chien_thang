"""Logo web: bảng ``site_logo`` (một dòng; WebP + favicon PNG, người sửa)

Revision ID: 723de145642f
Revises: 4009eb6241f1
Create Date: 2026-11-06 11:15:56.229579

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "723de145642f"
down_revision: str | None = "4009eb6241f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_logo",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=30), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("favicon_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("etag", sa.String(length=32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_label", sa.String(length=100), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_site_logo_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_logo")),
    )


def downgrade() -> None:
    op.drop_table("site_logo")

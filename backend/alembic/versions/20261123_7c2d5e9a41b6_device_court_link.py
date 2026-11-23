"""device court link: trạng thái nối máy đo tốc độ theo sân

Bảng mới ``device_court`` (module device_link): lệnh trận gần nhất đã phát cho máy đo và trạng thái
máy đo báo về, mỗi sân một dòng. Không đụng bảng cũ, không cần điền dữ liệu. Downgrade: xóa bảng
(lệnh đã phát sẽ được phát lại ở lần đồng bộ sau).

Revision ID: 7c2d5e9a41b6
Revises: 1a4340b669f8
Create Date: 2026-11-23 16:00:48.846136

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c2d5e9a41b6"
down_revision: str | None = "1a4340b669f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_court",
        sa.Column("court_code", sa.String(length=64), nullable=False),
        sa.Column("match_ref", sa.String(length=96), nullable=True),
        sa.Column("match_state", sa.String(length=10), nullable=True),
        sa.Column("players", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("app_online", sa.Boolean(), nullable=True),
        sa.Column("app_state", sa.String(length=10), nullable=True),
        sa.Column("app_error", sa.String(length=40), nullable=True),
        sa.Column("app_match_ref", sa.String(length=96), nullable=True),
        sa.Column("app_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "match_state IN ('started', 'stopped')", name=op.f("ck_device_court_match_state")
        ),
        sa.CheckConstraint(
            "(match_ref IS NULL) = (match_state IS NULL)",
            name=op.f("ck_device_court_match_pair"),
        ),
        sa.PrimaryKeyConstraint("court_code", name=op.f("pk_device_court")),
    )


def downgrade() -> None:
    op.drop_table("device_court")

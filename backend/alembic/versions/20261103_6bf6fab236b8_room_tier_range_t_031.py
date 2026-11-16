"""room tier range (T-031)

Khoảng hạng phòng chơi do người đặt chọn lúc đặt trong khu hội viên: ``min_tier`` / ``max_tier``
(tên hạng theo ``members.TIERS``, nullable – cả hai NULL = không giới hạn) đi theo
checkout -> đơn (engine) -> phòng (play_rooms). Dữ liệu cũ = NULL (không giới hạn), không backfill.

Revision ID: 6bf6fab236b8
Revises: ee7aaa89b694
Create Date: 2026-11-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6bf6fab236b8"
down_revision: str | None = "ee7aaa89b694"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (("checkout", "booking"), ("booking_order", "booking"), ("play_room", None))


def upgrade() -> None:
    for table, schema in TABLES:
        for column in ("min_tier", "max_tier"):
            op.add_column(
                table, sa.Column(column, sa.String(length=20), nullable=True), schema=schema
            )


def downgrade() -> None:
    for table, schema in reversed(TABLES):
        for column in ("max_tier", "min_tier"):
            op.drop_column(table, column, schema=schema)

"""Bỏ thắng / thua nhập tay của số đo (``speed_record.wins`` / ``losses``): thẻ kỷ lục dùng tổng
thắng / thua trong Lịch sử chơi của hội viên thay cho số nhập tay

Revision ID: a3d9cdb7c461
Revises: 8eb2eb8e8727
Create Date: 2026-11-11 14:45:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3d9cdb7c461"
down_revision: str | None = "8eb2eb8e8727"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_speed_record_speed_play_result"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "speed_record", type_="check")
    op.drop_column("speed_record", "losses")
    op.drop_column("speed_record", "wins")


def downgrade() -> None:
    op.add_column("speed_record", sa.Column("wins", sa.SmallInteger(), nullable=True))
    op.add_column("speed_record", sa.Column("losses", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f(CHECK),
        "speed_record",
        "(wins IS NULL) = (losses IS NULL) AND (wins IS NULL OR (wins BETWEEN 0 AND 99 "
        "AND losses BETWEEN 0 AND 99 AND wins + losses >= 1))",
    )

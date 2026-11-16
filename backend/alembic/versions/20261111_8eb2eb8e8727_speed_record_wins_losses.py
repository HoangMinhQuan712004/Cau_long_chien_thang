"""Thắng / thua trong buổi của số đo: ``speed_record.wins`` / ``losses`` (hội viên tự nhập khi gửi)

Revision ID: 8eb2eb8e8727
Revises: b34da28b29f8
Create Date: 2026-11-11 14:01:27.236528

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8eb2eb8e8727"
down_revision: str | None = "b34da28b29f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("speed_record", sa.Column("wins", sa.SmallInteger(), nullable=True))
    op.add_column("speed_record", sa.Column("losses", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_speed_record_speed_play_result"),
        "speed_record",
        "(wins IS NULL) = (losses IS NULL) AND (wins IS NULL OR (wins BETWEEN 0 AND 99 "
        "AND losses BETWEEN 0 AND 99 AND wins + losses >= 1))",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_speed_record_speed_play_result"), "speed_record", type_="check")
    op.drop_column("speed_record", "losses")
    op.drop_column("speed_record", "wins")

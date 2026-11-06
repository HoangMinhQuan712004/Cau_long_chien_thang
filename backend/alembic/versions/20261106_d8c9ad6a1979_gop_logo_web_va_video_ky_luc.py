"""gộp nhánh migration: logo web (723d…) với dev (video kỷ lục T-048, a4c9…)

Không đổi schema – chỉ nối hai head thành một.

Revision ID: d8c9ad6a1979
Revises: 723de145642f, a4c91e7d2f58
Create Date: 2026-11-06 13:21:04.712576

"""

from collections.abc import Sequence

revision: str = "d8c9ad6a1979"
down_revision: str | tuple[str, ...] | None = ("723de145642f", "a4c91e7d2f58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

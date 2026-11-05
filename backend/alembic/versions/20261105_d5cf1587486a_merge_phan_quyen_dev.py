"""gộp nhánh migration: Phân quyền + menu (8b2e…) với dev (kỷ lục tốc độ T-047, 5b7e…)

Không đổi schema – chỉ nối hai head thành một.

Revision ID: d5cf1587486a
Revises: 8b2e5d1c7f63, 5b7e2c9d41a3
Create Date: 2026-11-05 11:16:17.268777

"""

from collections.abc import Sequence

revision: str = "d5cf1587486a"
down_revision: str | tuple[str, ...] | None = ("8b2e5d1c7f63", "5b7e2c9d41a3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

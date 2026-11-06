"""gộp nhánh migration: logo + thông tin web (d8c9…) với dev (hủy booking / vé T-051, c7e2…)

Không đổi schema – chỉ nối hai head thành một.

Revision ID: bf1c6f8fad0d
Revises: d8c9ad6a1979, c7e2a91f4d36
Create Date: 2026-11-06 13:36:57.855871

"""

from collections.abc import Sequence

revision: str = "bf1c6f8fad0d"
down_revision: str | tuple[str, ...] | None = ("d8c9ad6a1979", "c7e2a91f4d36")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

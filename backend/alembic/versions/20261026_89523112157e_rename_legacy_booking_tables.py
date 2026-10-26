"""rename legacy booking tables

T-006 §8: gỡ luồng đặt sân cũ (module ``bookings`` / ``courts`` / ``payments``). Không xóa dữ liệu:
chỉ đổi tên bảng sang ``legacy_*`` (đảo ngược được); xóa hẳn ở task sau khi người dùng xác nhận.
Alembic bỏ qua bảng ``legacy_*`` (``alembic/env.py``). Kiểu enum cũ giữ nguyên.

Revision ID: 89523112157e
Revises: 085625ed0aca
Create Date: 2026-10-26 20:05:12.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "89523112157e"
down_revision: str | None = "085625ed0aca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("payments", "booking_slots", "bookings", "price_rules", "courts")


def upgrade() -> None:
    for table in TABLES:
        op.rename_table(table, f"legacy_{table}")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.rename_table(f"legacy_{table}", table)

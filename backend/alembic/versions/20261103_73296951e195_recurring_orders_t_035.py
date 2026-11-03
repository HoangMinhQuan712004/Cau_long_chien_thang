"""recurring orders (T-035)

Đặt sân định kỳ: ``booking_order.kind`` (``single`` | ``recurring``, dữ liệu cũ = ``single``),
``discount_pct`` (0–100) + ``discount_amount`` cho cả đơn; ``booking.list_amount`` = giá gốc khi
có giảm (NULL = không giảm, ``amount`` là giá gốc như trước). Exclusion constraint không đổi.

Revision ID: 73296951e195
Revises: 6bf6fab236b8
Create Date: 2026-11-03 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "73296951e195"
down_revision: str | None = "6bf6fab236b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "booking_order",
        sa.Column("kind", sa.String(length=10), server_default=sa.text("'single'"), nullable=False),
        schema="booking",
    )
    op.add_column(
        "booking_order",
        sa.Column("discount_pct", sa.SmallInteger(), nullable=True),
        schema="booking",
    )
    op.add_column(
        "booking_order", sa.Column("discount_amount", sa.Integer(), nullable=True), schema="booking"
    )
    op.create_check_constraint(
        op.f("ck_booking_order_kind"),
        "booking_order",
        "kind IN ('single', 'recurring')",
        schema="booking",
    )
    op.create_check_constraint(
        op.f("ck_booking_order_discount_pct"),
        "booking_order",
        "discount_pct BETWEEN 0 AND 100",
        schema="booking",
    )
    op.add_column(
        "booking", sa.Column("list_amount", sa.Integer(), nullable=True), schema="booking"
    )


def downgrade() -> None:
    op.drop_column("booking", "list_amount", schema="booking")
    op.drop_constraint(
        op.f("ck_booking_order_discount_pct"), "booking_order", schema="booking", type_="check"
    )
    op.drop_constraint(
        op.f("ck_booking_order_kind"), "booking_order", schema="booking", type_="check"
    )
    op.drop_column("booking_order", "discount_amount", schema="booking")
    op.drop_column("booking_order", "discount_pct", schema="booking")
    op.drop_column("booking_order", "kind", schema="booking")

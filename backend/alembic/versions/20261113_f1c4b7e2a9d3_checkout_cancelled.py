"""checkout status cancelled: khách tự hủy giữ chỗ khi chưa thanh toán

``checkout.status`` thêm ``cancelled`` (trạng thái cuối, giống ``expired`` với tiền về sau đó:
``refund_needed``). Hold của lượt hủy dùng ``released`` (đã có sẵn trong CHECK của ``hold``).

Downgrade: lượt ``cancelled`` -> ``expired`` (cùng nghĩa "đóng, chưa thanh toán", chỗ đã nhả).

Revision ID: f1c4b7e2a9d3
Revises: a3d9cdb7c461
Create Date: 2026-11-13 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1c4b7e2a9d3"
down_revision: str | None = "a3d9cdb7c461"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "booking"
CHECK = "ck_checkout_status"


def _replace_check(statuses: str) -> None:
    op.drop_constraint(op.f(CHECK), "checkout", schema=SCHEMA, type_="check")
    op.create_check_constraint(op.f(CHECK), "checkout", f"status IN ({statuses})", schema=SCHEMA)


def upgrade() -> None:
    _replace_check("'pending', 'paid', 'expired', 'cancelled'")


def downgrade() -> None:
    op.execute(
        sa.text(f"UPDATE {SCHEMA}.checkout SET status = 'expired' WHERE status = 'cancelled'")
    )
    _replace_check("'pending', 'paid', 'expired'")

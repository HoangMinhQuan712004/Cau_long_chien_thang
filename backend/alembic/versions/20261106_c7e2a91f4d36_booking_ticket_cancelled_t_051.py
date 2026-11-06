"""booking and ticket cancellation (T-051, ADR-013)

``payment_status`` thêm ``cancelled`` (trạng thái cuối) + lý do, người hủy, số đã hoàn. Không đụng
``ex_allocation_no_overlap``: hủy booking chỉ đặt ``allocation.active = false``.

Downgrade **từ chối chạy** khi đã có dòng ``cancelled``: không có trạng thái cũ nào đúng để trả về,
và booking đã nhả chỗ có thể đã bị người khác đặt lại.

Revision ID: c7e2a91f4d36
Revises: a4c91e7d2f58
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a91f4d36"
down_revision: str | None = "a4c91e7d2f58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "booking"
TABLES = ("booking", "ticket")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("cancel_reason", sa.String(200)), schema=SCHEMA)
        op.add_column(table, sa.Column("cancelled_at", sa.DateTime(timezone=True)), schema=SCHEMA)
        op.add_column(table, sa.Column("cancelled_by_type", sa.String(20)), schema=SCHEMA)
        op.add_column(table, sa.Column("cancelled_by_id", sa.BigInteger()), schema=SCHEMA)
        op.add_column(table, sa.Column("cancelled_by_label", sa.String(100)), schema=SCHEMA)
        op.add_column(
            table,
            sa.Column("refund_amount", sa.Integer(), server_default=sa.text("0"), nullable=False),
            schema=SCHEMA,
        )
        op.drop_constraint(op.f(f"ck_{table}_payment_status"), table, schema=SCHEMA, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_payment_status"),
            table,
            "payment_status IN ('unpaid', 'paid', 'uncollectible', 'cancelled')",
            schema=SCHEMA,
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_cancelled_has_reason"),
            table,
            "payment_status <> 'cancelled' OR "
            "(cancel_reason IS NOT NULL AND cancelled_at IS NOT NULL)",
            schema=SCHEMA,
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_refund_range"),
            table,
            "refund_amount BETWEEN 0 AND amount",
            schema=SCHEMA,
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        found = bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE payment_status = 'cancelled'")
        ).scalar_one()
        if found:
            raise RuntimeError(
                f"Cannot downgrade: {SCHEMA}.{table} has {found} cancelled rows and no earlier "
                "status can represent them (ADR-013)."
            )
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_refund_range"), table, schema=SCHEMA, type_="check")
        op.drop_constraint(
            op.f(f"ck_{table}_cancelled_has_reason"), table, schema=SCHEMA, type_="check"
        )
        op.drop_constraint(op.f(f"ck_{table}_payment_status"), table, schema=SCHEMA, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_payment_status"),
            table,
            "payment_status IN ('unpaid', 'paid', 'uncollectible')",
            schema=SCHEMA,
        )
        for column in (
            "refund_amount",
            "cancelled_by_label",
            "cancelled_by_id",
            "cancelled_by_type",
            "cancelled_at",
            "cancel_reason",
        ):
            op.drop_column(table, column, schema=SCHEMA)

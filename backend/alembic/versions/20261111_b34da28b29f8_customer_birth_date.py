"""Ngày sinh hội viên: cột ``customer.birth_date`` (NULL = chưa nhập, không trước 1900)

Revision ID: b34da28b29f8
Revises: d2886c61ed25
Create Date: 2026-11-11 10:09:50.275668

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b34da28b29f8"
down_revision: str | None = "d2886c61ed25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer", sa.Column("birth_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_customer_birth_date"),
        "customer",
        "birth_date IS NULL OR birth_date >= '1900-01-01'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_customer_birth_date"), "customer", type_="check")
    op.drop_column("customer", "birth_date")

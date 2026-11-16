"""ticket checkouts (T-023)

Mua vé sự kiện online: ``checkout.kind`` (``court`` | ``ticket``, dữ liệu cũ = ``court``) và
``ticket.checkout_id`` (vé sinh ra từ lượt thanh toán nào). Hold ``seat`` đã có sẵn – không đổi
ràng buộc của ``hold``; exclusion constraint ``ex_allocation_no_overlap`` không đổi.

Downgrade bỏ hai cột: lượt thanh toán vé (nếu có) trở thành checkout không có khung sân – code cũ
không hiển thị được các lượt đó, vé đã sinh vẫn là vé bình thường.

Revision ID: 9f73fd765c58
Revises: 0cbf30ad5193
Create Date: 2026-11-02 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f73fd765c58"
down_revision: str | None = "0cbf30ad5193"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "checkout",
        sa.Column("kind", sa.String(length=10), server_default=sa.text("'court'"), nullable=False),
        schema="booking",
    )
    op.create_check_constraint(
        op.f("ck_checkout_kind"), "checkout", "kind IN ('court', 'ticket')", schema="booking"
    )
    op.add_column("ticket", sa.Column("checkout_id", sa.Uuid(), nullable=True), schema="booking")
    op.create_index(
        op.f("ix_booking_ticket_checkout_id"),
        "ticket",
        ["checkout_id"],
        unique=False,
        schema="booking",
    )
    op.create_foreign_key(
        op.f("fk_ticket_checkout_id_checkout"),
        "ticket",
        "checkout",
        ["checkout_id"],
        ["id"],
        source_schema="booking",
        referent_schema="booking",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_ticket_checkout_id_checkout"), "ticket", schema="booking", type_="foreignkey"
    )
    op.drop_index(op.f("ix_booking_ticket_checkout_id"), table_name="ticket", schema="booking")
    op.drop_column("ticket", "checkout_id", schema="booking")
    op.drop_constraint(op.f("ck_checkout_kind"), "checkout", schema="booking", type_="check")
    op.drop_column("checkout", "kind", schema="booking")

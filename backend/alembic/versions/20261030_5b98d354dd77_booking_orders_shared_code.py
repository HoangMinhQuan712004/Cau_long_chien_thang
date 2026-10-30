"""booking orders shared code

T-019 (ADR-010): mã chung cho một lượt đặt.
1. Bảng ``booking.booking_order`` (đơn đặt: mã BK-YYYYMMDD-NNN, kênh, snapshot khách).
2. ``booking``: ``order_id`` (FK, NOT NULL), ``seq`` (01–99), unique ``(order_id, seq)``;
   ``code`` thành mã con ``{mã đơn}-NN``.
3. ``checkout.order_code`` (mã đơn cấp lúc giữ chỗ; ``pay_ref`` = mã này bỏ gạch).
Dữ liệu cũ (dev): mỗi booking -> một đơn, mã đơn = mã cũ, booking nhận ``-01`` (hold +
allocation cùng mã cũng đổi); checkout ``pending`` cho hết hạn (giải phóng khung).
Downgrade: chỉ khi chưa có đơn nào > 1 khối – ngược lại dừng kèm thông báo.
Exclusion constraint không đổi.

Revision ID: 5b98d354dd77
Revises: dad220bfc992
Create Date: 2026-10-30 16:02:54.211214

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5b98d354dd77"
down_revision: str | None = "dad220bfc992"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPIRE_PENDING = """
WITH c AS (
    UPDATE booking.checkout SET status = 'expired', updated_at = now()
    WHERE status = 'pending' RETURNING id
), h AS (
    UPDATE booking.hold SET status = 'expired'
    WHERE status = 'active' AND checkout_id IN (SELECT id FROM c) RETURNING id
)
UPDATE booking.allocation SET active = false WHERE hold_id IN (SELECT id FROM h)
"""

ORDERS_FROM_BOOKINGS = """
INSERT INTO booking.booking_order (
    tenant_id, code, play_date, channel, checkout_id, created_at, created_by_label,
    customer_ref, customer_kind, customer_name, customer_phone, member_code, member_tier
)
SELECT b.tenant_id, b.code, b.play_date, b.source,
       CASE WHEN replace(b.code, '-', '') = co.pay_ref THEN b.checkout_id END,
       b.created_at, b.created_by_label, b.customer_ref, b.customer_kind,
       b.customer_name, b.customer_phone, b.member_code, b.member_tier
FROM booking.booking b LEFT JOIN booking.checkout co ON co.id = b.checkout_id
"""

LINK_BOOKINGS = """
UPDATE booking.booking b SET order_id = o.id, seq = 1, code = b.code || '-01'
FROM booking.booking_order o
WHERE o.tenant_id = b.tenant_id AND o.code = b.code
"""

CHILD_HOLD_CODES = """
UPDATE booking.hold SET code = code || '-01'
WHERE kind = 'court' AND checkout_id IS NOT NULL AND code IS NOT NULL
"""

CHILD_OWNER_CODES = """
UPDATE booking.allocation SET owner_code = owner_code || '-01'
WHERE owner_code IS NOT NULL AND (
    booking_id IS NOT NULL
    OR hold_id IN (SELECT id FROM booking.hold WHERE checkout_id IS NOT NULL)
)
"""

# Mã đơn của checkout cũ = mã hold có dạng không gạch đúng bằng pay_ref (bỏ hậu tố -01)
CHECKOUT_ORDER_CODES = """
UPDATE booking.checkout c SET order_code = left(h.code, length(h.code) - 3)
FROM booking.hold h
WHERE h.checkout_id = c.id
  AND replace(left(h.code, length(h.code) - 3), '-', '') = c.pay_ref
"""


def upgrade() -> None:
    op.create_table(
        "booking_order",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.SmallInteger(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("play_date", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("checkout_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by_label", sa.String(length=100), nullable=False),
        sa.Column("customer_ref", sa.String(length=40), nullable=False),
        sa.Column("customer_kind", sa.String(length=10), nullable=False),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=15), nullable=False),
        sa.Column("member_code", sa.String(length=10), nullable=True),
        sa.Column("member_tier", sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            "channel IN ('online', 'counter')", name=op.f("ck_booking_order_channel")
        ),
        sa.CheckConstraint(
            "customer_kind IN ('member', 'temp')", name=op.f("ck_booking_order_customer_kind")
        ),
        sa.ForeignKeyConstraint(
            ["checkout_id"],
            ["booking.checkout.id"],
            name=op.f("fk_booking_order_checkout_id_checkout"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["booking.tenant.id"],
            name=op.f("fk_booking_order_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_order")),
        sa.UniqueConstraint("checkout_id", name=op.f("uq_booking_order_checkout_id")),
        sa.UniqueConstraint("tenant_id", "code", name=op.f("uq_booking_order_tenant_id")),
        schema="booking",
    )
    op.add_column("booking", sa.Column("order_id", sa.BigInteger()), schema="booking")
    op.add_column("booking", sa.Column("seq", sa.SmallInteger()), schema="booking")
    op.add_column("checkout", sa.Column("order_code", sa.String(length=30)), schema="booking")

    # ---- dữ liệu cũ
    op.execute(EXPIRE_PENDING)
    op.execute(ORDERS_FROM_BOOKINGS)
    op.execute(LINK_BOOKINGS)
    op.execute(CHILD_HOLD_CODES)
    op.execute(CHILD_OWNER_CODES)
    op.execute(CHECKOUT_ORDER_CODES)
    op.execute("UPDATE booking.checkout SET order_code = pay_ref WHERE order_code IS NULL")

    op.alter_column("booking", "order_id", nullable=False, schema="booking")
    op.alter_column("booking", "seq", nullable=False, schema="booking")
    op.alter_column("checkout", "order_code", nullable=False, schema="booking")
    op.create_unique_constraint(
        op.f("uq_checkout_tenant_id_order_code"),
        "checkout",
        ["tenant_id", "order_code"],
        schema="booking",
    )
    op.create_index(
        op.f("ix_booking_booking_order_id"), "booking", ["order_id"], unique=False, schema="booking"
    )
    op.create_unique_constraint(
        op.f("uq_booking_order_id"), "booking", ["order_id", "seq"], schema="booking"
    )
    op.create_check_constraint(
        op.f("ck_booking_seq"), "booking", "seq BETWEEN 1 AND 99", schema="booking"
    )
    op.create_foreign_key(
        op.f("fk_booking_order_id_booking_order"),
        "booking",
        "booking_order",
        ["order_id"],
        ["id"],
        source_schema="booking",
        referent_schema="booking",
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    multi = op.get_bind().scalar(sa.text("SELECT count(*) FROM booking.booking WHERE seq > 1"))
    if multi:
        raise RuntimeError(
            "Downgrade dừng: đã có đơn đặt nhiều khối (mã con -02 trở lên) – không trả được về "
            "mỗi khối một mã. Xóa dữ liệu thử hoặc giữ phiên bản hiện tại."
        )
    op.drop_constraint(
        op.f("fk_booking_order_id_booking_order"), "booking", schema="booking", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_booking_seq"), "booking", schema="booking", type_="check")
    op.drop_constraint(op.f("uq_booking_order_id"), "booking", schema="booking", type_="unique")
    op.drop_index(op.f("ix_booking_booking_order_id"), table_name="booking", schema="booking")
    # Chỉ các dòng upgrade đã thêm -01 (booking, hold của checkout, allocation của chúng)
    op.execute("UPDATE booking.booking SET code = regexp_replace(code, '-01$', '')")
    op.execute(
        "UPDATE booking.hold SET code = regexp_replace(code, '-01$', '') "
        "WHERE kind = 'court' AND checkout_id IS NOT NULL AND code LIKE '%-01'"
    )
    op.execute(
        "UPDATE booking.allocation SET owner_code = regexp_replace(owner_code, '-01$', '') "
        "WHERE owner_code LIKE '%-01' AND (booking_id IS NOT NULL OR hold_id IN ("
        "SELECT id FROM booking.hold WHERE kind = 'court' AND checkout_id IS NOT NULL))"
    )
    op.drop_constraint(
        op.f("uq_checkout_tenant_id_order_code"), "checkout", schema="booking", type_="unique"
    )
    op.drop_column("checkout", "order_code", schema="booking")
    op.drop_column("booking", "seq", schema="booking")
    op.drop_column("booking", "order_id", schema="booking")
    op.drop_table("booking_order", schema="booking")

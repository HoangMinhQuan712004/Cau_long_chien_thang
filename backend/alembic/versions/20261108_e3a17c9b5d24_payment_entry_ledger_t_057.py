"""Sổ tiền vào ``payment_entry`` + ``payment_entry_item`` (T-057, ADR-014) và backfill

Backfill từ booking / vé (SQL thuần):
- ``in``: dòng từng thu (``paid_at`` có, trạng thái ``paid`` hoặc ``cancelled``, ``amount > 0``).
  - Có ``gateway_ref`` (tiền về SePay): gộp theo giao dịch (``gateway_ref`` bỏ đuôi ``:n``) –
    một giao dịch = một dòng; phủ nhiều đơn (dữ liệu trước T-019) -> mã đơn nhỏ nhất (Sửa 09/11).
  - Còn lại, booking gộp theo (đơn, ``paid_at``, phương thức, người thu).
  - Còn lại, vé gộp theo (sự kiện, lượt thanh toán online, khách, ``paid_at``, phương thức,
    người thu).
  - Nguồn ``online`` khi ``online_transfer``, còn lại ``counter``; SePay: người thu "Hệ thống",
    ``reference`` = ``gateway_ref`` bỏ đuôi ``:n``.
- ``refund``: dòng có ``refund_amount > 0``, gộp như trên nhưng theo ``cancelled_at`` + người hủy.

Σ in = Σ ``amount`` đã thu; Σ refund = Σ ``refund_amount``. Downgrade: xóa 2 bảng (sổ suy ra
được từ booking / vé, dữ liệu gốc không mất).

Revision ID: e3a17c9b5d24
Revises: bb86440fad96
Create Date: 2026-11-08 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a17c9b5d24"
down_revision: str | None = "bb86440fad96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ``sepay:{id}:{n}`` -> ``sepay:{id}`` (mã giao dịch = ``reference`` của dòng sổ)
_REF_TAIL = ":[0-9]+$"  # chèn thẳng vào SQL (CREATE TABLE AS không nhận tham số)

# Một dòng nguồn = một mục sổ; ``grp`` = khóa gộp thành một dòng sổ. Có ``gateway_ref`` -> gộp
# theo giao dịch (một giao dịch = một dòng, kể cả khi dữ liệu trước T-019 tách thành nhiều đơn)
_SOURCE_ROWS = """
CREATE TEMP TABLE _pe_src ON COMMIT DROP AS
SELECT 'b'::text AS target, b.id AS item_id, b.tenant_id, 'in'::text AS kind,
       b.payment_method AS method, b.amount AS amount, b.paid_at AS occurred_at,
       o.code AS order_code, b.customer_name, b.customer_phone, b.member_code,
       b.collected_by_type AS actor_type, b.collected_by_id AS actor_id,
       b.collected_by_label AS actor_label, b.gateway_ref,
       CASE WHEN b.gateway_ref IS NOT NULL
            THEN concat_ws('|', 'g', b.tenant_id, regexp_replace(b.gateway_ref, '{tail}', ''))
            ELSE concat_ws('|', 'b', b.order_id, b.paid_at, b.payment_method,
                           b.collected_by_type, b.collected_by_id, b.collected_by_label)
       END AS grp
FROM booking.booking b JOIN booking.booking_order o ON o.id = b.order_id
WHERE b.paid_at IS NOT NULL AND b.payment_status IN ('paid', 'cancelled') AND b.amount > 0
UNION ALL
SELECT 't', t.id, t.tenant_id, 'in', t.payment_method, t.amount, t.paid_at,
       s.code, t.customer_name, t.customer_phone, t.member_code,
       t.collected_by_type, t.collected_by_id, t.collected_by_label, t.gateway_ref,
       CASE WHEN t.gateway_ref IS NOT NULL
            THEN concat_ws('|', 'g', t.tenant_id, regexp_replace(t.gateway_ref, '{tail}', ''))
            ELSE concat_ws('|', 't', t.session_id, t.checkout_id, t.customer_ref, t.paid_at,
                           t.payment_method, t.collected_by_type, t.collected_by_id,
                           t.collected_by_label)
       END
FROM booking.ticket t JOIN booking.session s ON s.id = t.session_id
WHERE t.paid_at IS NOT NULL AND t.payment_status IN ('paid', 'cancelled') AND t.amount > 0
UNION ALL
SELECT 'b', b.id, b.tenant_id, 'refund', b.payment_method, b.refund_amount, b.cancelled_at,
       o.code, b.customer_name, b.customer_phone, b.member_code,
       b.cancelled_by_type, b.cancelled_by_id, b.cancelled_by_label, NULL,
       concat_ws('|', 'rb', b.order_id, b.cancelled_at, b.payment_method,
                 b.cancelled_by_type, b.cancelled_by_id, b.cancelled_by_label)
FROM booking.booking b JOIN booking.booking_order o ON o.id = b.order_id
WHERE b.refund_amount > 0
UNION ALL
SELECT 't', t.id, t.tenant_id, 'refund', t.payment_method, t.refund_amount, t.cancelled_at,
       s.code, t.customer_name, t.customer_phone, t.member_code,
       t.cancelled_by_type, t.cancelled_by_id, t.cancelled_by_label, NULL,
       concat_ws('|', 'rt', t.session_id, t.checkout_id, t.customer_ref, t.cancelled_at,
                 t.payment_method, t.cancelled_by_type, t.cancelled_by_id, t.cancelled_by_label)
FROM booking.ticket t JOIN booking.session s ON s.id = t.session_id
WHERE t.refund_amount > 0
"""

_GROUPS = """
CREATE TEMP TABLE _pe_grp ON COMMIT DROP AS
SELECT nextval(pg_get_serial_sequence('booking.payment_entry', 'id')) AS entry_id, g.*
FROM (
    SELECT grp, min(tenant_id) AS tenant_id, min(kind) AS kind, min(method) AS method,
           sum(amount) AS amount, min(occurred_at) AS occurred_at,
           min(order_code COLLATE "C") AS order_code,
           min(customer_name) AS customer_name, min(customer_phone) AS customer_phone,
           min(member_code) AS member_code, min(actor_type) AS actor_type,
           min(actor_id) AS actor_id, min(actor_label) AS actor_label,
           min(regexp_replace(gateway_ref, '{tail}', '')) AS reference
    FROM _pe_src GROUP BY grp ORDER BY min(occurred_at), grp
) g
"""

_INSERT_ENTRIES = """
INSERT INTO booking.payment_entry (
    id, tenant_id, kind, method, source, amount, occurred_at, order_code,
    customer_name, customer_phone, member_code, actor_type, actor_id, actor_label, reference
)
SELECT entry_id, tenant_id, kind, method,
       CASE WHEN method = 'online_transfer' THEN 'online' ELSE 'counter' END,
       amount, occurred_at, order_code, customer_name, customer_phone, member_code,
       CASE WHEN kind = 'in' AND method = 'online_transfer' THEN 'system'
            ELSE coalesce(actor_type, 'system') END,
       CASE WHEN kind = 'in' AND method = 'online_transfer' THEN NULL ELSE actor_id END,
       CASE WHEN kind = 'in' AND method = 'online_transfer' THEN 'Hệ thống'
            ELSE coalesce(actor_label, 'Hệ thống') END,
       CASE WHEN kind = 'in' THEN reference END
FROM _pe_grp ORDER BY entry_id
"""

_INSERT_ITEMS = """
INSERT INTO booking.payment_entry_item (tenant_id, entry_id, booking_id, ticket_id, amount)
SELECT s.tenant_id, g.entry_id,
       CASE WHEN s.target = 'b' THEN s.item_id END,
       CASE WHEN s.target = 't' THEN s.item_id END,
       s.amount
FROM _pe_src s JOIN _pe_grp g ON g.grp = s.grp
ORDER BY g.entry_id, s.item_id
"""


def upgrade() -> None:
    op.create_table(
        "payment_entry",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_code", sa.String(length=30), nullable=True),
        sa.Column("customer_name", sa.String(length=100), nullable=False),
        sa.Column("customer_phone", sa.String(length=15), nullable=False),
        sa.Column("member_code", sa.String(length=10), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_label", sa.String(length=100), nullable=False),
        sa.Column("reference", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payment_entry_amount_positive")),
        sa.CheckConstraint("kind IN ('in', 'refund')", name=op.f("ck_payment_entry_kind")),
        sa.CheckConstraint(
            "method IN ('cash', 'transfer', 'online_transfer')",
            name=op.f("ck_payment_entry_method"),
        ),
        sa.CheckConstraint(
            "source IN ('counter', 'counter_qr', 'online')", name=op.f("ck_payment_entry_source")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["booking.tenant.id"],
            name=op.f("fk_payment_entry_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_entry")),
        schema="booking",
    )
    op.create_index(
        "ix_payment_entry_tenant_occurred_at",
        "payment_entry",
        ["tenant_id", "occurred_at"],
        unique=False,
        schema="booking",
    )
    op.create_index(
        "uq_payment_entry_tenant_reference",
        "payment_entry",
        ["tenant_id", "reference"],
        unique=True,
        schema="booking",
        postgresql_where=sa.text("reference IS NOT NULL"),
    )
    op.create_table(
        "payment_entry_item",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.SmallInteger(), nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("booking_id", sa.BigInteger(), nullable=True),
        sa.Column("ticket_id", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(booking_id IS NULL) <> (ticket_id IS NULL)",
            name=op.f("ck_payment_entry_item_one_target"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_payment_entry_item_amount_positive")),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["booking.booking.id"],
            name=op.f("fk_payment_entry_item_booking_id_booking"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["booking.payment_entry.id"],
            name=op.f("fk_payment_entry_item_entry_id_payment_entry"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["booking.tenant.id"],
            name=op.f("fk_payment_entry_item_tenant_id_tenant"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["booking.ticket.id"],
            name=op.f("fk_payment_entry_item_ticket_id_ticket"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_entry_item")),
        schema="booking",
    )
    for column in ("booking_id", "entry_id", "ticket_id"):
        op.create_index(
            op.f(f"ix_booking_payment_entry_item_{column}"),
            "payment_entry_item",
            [column],
            unique=False,
            schema="booking",
        )

    for sql in (_SOURCE_ROWS, _GROUPS, _INSERT_ENTRIES, _INSERT_ITEMS):
        op.execute(sql.replace("{tail}", _REF_TAIL))
    op.execute("DROP TABLE _pe_src, _pe_grp")


def downgrade() -> None:
    for column in ("booking_id", "entry_id", "ticket_id"):
        op.drop_index(
            op.f(f"ix_booking_payment_entry_item_{column}"),
            table_name="payment_entry_item",
            schema="booking",
        )
    op.drop_table("payment_entry_item", schema="booking")
    op.drop_index(
        "uq_payment_entry_tenant_reference",
        table_name="payment_entry",
        schema="booking",
        postgresql_where=sa.text("reference IS NOT NULL"),
    )
    op.drop_index(
        "ix_payment_entry_tenant_occurred_at", table_name="payment_entry", schema="booking"
    )
    op.drop_table("payment_entry", schema="booking")

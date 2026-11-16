"""web push subscriptions (T-076, ADR-015)

Schema mới ``push`` + bảng ``push.subscription`` (thiết bị đã bật thông báo đẩy). Không đụng bảng
cũ; ``user_id`` không FK chéo module. Downgrade: xóa bảng + schema (mất các đăng ký thiết bị –
người dùng bật lại).

Revision ID: 1a4340b669f8
Revises: f1c4b7e2a9d3
Create Date: 2026-11-16 13:52:50.614944

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1a4340b669f8"
down_revision: str | None = "f1c4b7e2a9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "push"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "subscription",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(length=200), nullable=False),
        sa.Column("auth", sa.String(length=100), nullable=False),
        sa.Column("device_label", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_subscription_endpoint")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_push_subscription_user_id"), "subscription", ["user_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_push_subscription_user_id"), table_name="subscription", schema=SCHEMA)
    op.drop_table("subscription", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")

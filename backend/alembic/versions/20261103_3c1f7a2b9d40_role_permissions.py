"""role permissions (Phân quyền bước 2)

``role_permission(role, perm)``: quyền của vai **staff** (Nhân viên), đọc mỗi request; Admin luôn
toàn quyền (không có dòng). Cột ``role`` + CHECK chỉ 'staff' để sau mở rộng được. Seed 16 quyền NV
mặc định: 12 quyền cũ + Sân & bảng giá + Lịch sử giao dịch + Tạo / xóa sự kiện + Danh mục vợt
(chuỗi viết cứng – không đổi theo code).

Revision ID: 3c1f7a2b9d40
Revises: ee7aaa89b694
Create Date: 2026-11-03 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c1f7a2b9d40"
down_revision: str | None = "ee7aaa89b694"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STAFF_PERMS = (
    "booking.resources.view",
    "booking.quote",
    "booking.calendar.view",
    "booking.search",
    "booking.counter.create",
    "booking.item.view",
    "booking.ticket.create",
    "booking.session.view",
    "booking.collect",
    "booking.uncollectible",
    "member.search",
    "member.manage",
    "booking.config.manage",  # Sân & bảng giá
    "booking.transactions.view",  # Lịch sử giao dịch
    "booking.session.manage",  # Tạo / xóa sự kiện
    "racket.manage",  # Quản lý danh mục vợt
)


def upgrade() -> None:
    table = op.create_table(
        "role_permission",
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("perm", sa.String(length=60), nullable=False),
        sa.CheckConstraint("role = 'staff'", name=op.f("ck_role_permission_role")),
        sa.PrimaryKeyConstraint("role", "perm", name=op.f("pk_role_permission")),
    )
    op.bulk_insert(table, [{"role": "staff", "perm": p} for p in STAFF_PERMS])


def downgrade() -> None:
    op.drop_table("role_permission")

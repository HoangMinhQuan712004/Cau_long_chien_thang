"""speed record video_set_at (T-048)

Ngày dán link video: nhãn "Kỷ lục ngày dd/mm" của màn Video & kỷ lục đi theo cột này, không theo
ngày đo. Dòng cũ có video lấy lần ``record.video_set`` mới nhất trong nhật ký, không có thì lấy
``created_at`` (Admin nhập / hội viên gửi kèm link không sinh ``record.video_set``). Check thêm sau
bước điền: có link thì có ngày, không link thì không ngày.

Revision ID: a4c91e7d2f58
Revises: d5cf1587486a
Create Date: 2026-11-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c91e7d2f58"
down_revision: str | None = "d5cf1587486a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_speed_record_speed_video_set_at"


def upgrade() -> None:
    op.add_column("speed_record", sa.Column("video_set_at", sa.DateTime(timezone=True)))
    op.execute(
        """
        UPDATE speed_record AS r
        SET video_set_at = COALESCE(
            (
                SELECT max(a.at)
                FROM audit_log AS a
                WHERE a.action = 'record.video_set'
                  AND a.entity_type = 'speed_record'
                  AND a.entity_code = r.id::text
            ),
            r.created_at
        )
        WHERE r.video_url IS NOT NULL
        """
    )
    op.create_check_constraint(
        op.f(CHECK), "speed_record", "(video_url IS NULL) = (video_set_at IS NULL)"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(CHECK), "speed_record", type_="check")
    op.drop_column("speed_record", "video_set_at")

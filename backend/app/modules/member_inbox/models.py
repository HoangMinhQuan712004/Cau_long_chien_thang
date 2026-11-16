"""Thông báo trong web cho hội viên (T-017 AC22) – dùng chung cho T-018."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MemberNotification(Base):
    __tablename__ = "member_notification"
    __table_args__ = (
        Index("ix_member_notification_customer_created", "customer_id", "created_at"),
        Index(
            "ix_member_notification_unread",
            "customer_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Id hồ sơ hội viên (module Hội viên) – không FK chéo module
    customer_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    # {"text": "…", …} – không chứa SĐT
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    link: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

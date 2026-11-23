"""Trạng thái nối máy đo tốc độ theo từng sân.

Một dòng mỗi sân đã từng có lệnh hoặc có tin từ máy đo. ``match_*`` = lệnh trận gần nhất server đã
phát (bản retained trên broker); ``app_*`` = trạng thái gần nhất máy đo báo về.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class DeviceCourt(Base):
    __tablename__ = "device_court"
    __table_args__ = (
        CheckConstraint("match_state IN ('started', 'stopped')", name="match_state"),
        CheckConstraint("(match_ref IS NULL) = (match_state IS NULL)", name="match_pair"),
    )

    court_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    match_ref: Mapped[str | None] = mapped_column(String(96))
    match_state: Mapped[str | None] = mapped_column(String(10))
    # ``players`` của ``match.start`` đã phát – đổi đội hình thì phát lại
    players: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    app_online: Mapped[bool | None] = mapped_column(Boolean)
    app_state: Mapped[str | None] = mapped_column(String(10))
    app_error: Mapped[str | None] = mapped_column(String(40))
    app_match_ref: Mapped[str | None] = mapped_column(String(96))
    app_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

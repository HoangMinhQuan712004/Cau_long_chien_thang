"""Kỷ lục tốc độ cú đập (T-030): số đo do máy đo gửi về (giai đoạn B); giai đoạn A: đọc + seed.

Module riêng (không thuộc Hội viên) vì gắn với thiết bị và sau này là video kỷ lục.
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SPEED_RANGE = (50, 500)


class SpeedRecord(Base):
    __tablename__ = "speed_record"
    __table_args__ = (
        CheckConstraint(
            f"speed_kmh BETWEEN {SPEED_RANGE[0]} AND {SPEED_RANGE[1]}", name="speed_range"
        ),
        Index("ix_speed_record_measured_at", "measured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Id hồ sơ hội viên (module Hội viên) – không FK chéo module. Giai đoạn A: luôn có người
    customer_id: Mapped[int] = mapped_column(Integer)
    speed_kmh: Mapped[int] = mapped_column(Integer)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    court_code: Mapped[str | None] = mapped_column(String(10))
    device_id: Mapped[str | None] = mapped_column(String(50))
    # Mã số đo phía máy (chống ghi trùng khi máy gửi lại)
    source_ref: Mapped[str] = mapped_column(String(100), unique=True)
    video_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Kỷ lục mọi thời gian / số đo cao nhất của một người
Index("ix_speed_record_customer_speed", SpeedRecord.customer_id, SpeedRecord.speed_kmh.desc())

"""Kỷ lục tốc độ cú đập (T-030): số đo do máy đo gửi về (giai đoạn B); giai đoạn A: đọc + seed.

Module riêng (không thuộc Hội viên) vì gắn với thiết bị và sau này là video kỷ lục.
T-047: Admin nhập tay (duyệt ngay) và hội viên tự gửi (chờ Admin duyệt). **Mọi nơi tính hạng /
kỷ lục / video chỉ lấy ``status = 'approved'``.**
"""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SPEED_RANGE = (50, 500)
SOURCES = ("device", "admin", "member")  # máy đo · Admin nhập · hội viên gửi
STATUSES = ("approved", "pending", "rejected")
REJECT_REASON_MAX = 200


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class SpeedRecord(Base):
    __tablename__ = "speed_record"
    __table_args__ = (
        CheckConstraint(
            f"speed_kmh BETWEEN {SPEED_RANGE[0]} AND {SPEED_RANGE[1]}", name="speed_range"
        ),
        CheckConstraint(_in("source", SOURCES), name="speed_source"),
        CheckConstraint(_in("status", STATUSES), name="speed_status"),
        CheckConstraint(
            "status <> 'rejected' OR reject_reason IS NOT NULL", name="speed_reject_reason"
        ),
        Index("ix_speed_record_measured_at", "measured_at"),
        Index("ix_speed_record_status_measured_at", "status", "measured_at"),
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
    # T-047: nguồn + trạng thái duyệt. Bản ghi cũ (máy đo / seed) là device / approved
    source: Mapped[str] = mapped_column(String(10), default="device", server_default="device")
    status: Mapped[str] = mapped_column(String(10), default="approved", server_default="approved")
    # Id tài khoản người nhập / gửi (Admin hoặc khách) – không FK chéo module
    submitted_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_by: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(String(REJECT_REASON_MAX))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Đặt tay mỗi lần đổi (không dùng onupdate); ``version`` +1 mỗi lần đổi – PATCH gửi kèm để
    # chống ghi đè (lệch -> 409 E-REC-3)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


# Kỷ lục mọi thời gian / số đo cao nhất của một người
Index("ix_speed_record_customer_speed", SpeedRecord.customer_id, SpeedRecord.speed_kmh.desc())

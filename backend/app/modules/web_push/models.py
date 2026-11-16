"""Thiết bị đã bật thông báo đẩy (T-076, ADR-015) – schema Postgres ``push``."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "push"


class PushSubscription(Base):
    __tablename__ = "subscription"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Id tài khoản (module Xác thực) – không FK chéo module
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # URL dịch vụ push (đã qua danh sách host, ``endpoints.check``) – bí mật: không log cả URL
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    device_label: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fail_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

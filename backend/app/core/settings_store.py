"""Cài đặt chung dạng key → JSON (bảng ``app_setting``), vd thứ tự menu khu quản trị."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AppSetting(Base):
    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_label: Mapped[str | None] = mapped_column(String(100))


async def get_value(session: AsyncSession, key: str) -> Any | None:
    return await session.scalar(select(AppSetting.value).where(AppSetting.key == key))

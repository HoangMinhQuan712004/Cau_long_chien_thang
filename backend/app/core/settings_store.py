"""Cài đặt chung dạng key → JSON (bảng ``app_setting``), vd thứ tự menu khu quản trị."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, LargeBinary, SmallInteger, String, func, select
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


class SiteLogo(Base):
    """Logo web: một dòng duy nhất (``id = 1``); chưa có logo = không có dòng."""

    __tablename__ = "site_logo"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    content_type: Mapped[str] = mapped_column(String(30))
    bytes: Mapped[bytes] = mapped_column(LargeBinary)
    favicon_bytes: Mapped[bytes] = mapped_column(LargeBinary)  # PNG nhỏ: WebP kém tương thích
    etag: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_label: Mapped[str | None] = mapped_column(String(100))


async def get_value(session: AsyncSession, key: str) -> Any | None:
    return await session.scalar(select(AppSetting.value).where(AppSetting.key == key))

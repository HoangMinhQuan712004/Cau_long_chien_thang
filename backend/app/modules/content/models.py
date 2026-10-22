from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Post(TimestampMixin, Base):
    """Bài viết / tin tức phục vụ SEO."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    excerpt: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)  # HTML hoặc Markdown
    cover_url: Mapped[str | None] = mapped_column(String(500))
    meta_title: Mapped[str | None] = mapped_column(String(255))
    meta_description: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

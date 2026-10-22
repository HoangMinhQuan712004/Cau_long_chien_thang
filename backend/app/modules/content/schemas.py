from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    excerpt: str | None = Field(default=None, max_length=500)
    content: str
    cover_url: str | None = None
    meta_title: str | None = Field(default=None, max_length=255)
    meta_description: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None  # None = bản nháp


class PostSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    slug: str
    excerpt: str | None
    cover_url: str | None
    published_at: datetime | None
    updated_at: datetime


class PostOut(PostSummary):
    content: str
    meta_title: str | None
    meta_description: str | None

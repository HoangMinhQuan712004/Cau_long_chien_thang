from datetime import time

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, String, Text, Time
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class Court(TimestampMixin, Base):
    """Sân con trong cụm sân (Sân 1, Sân 2...)."""

    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    surface: Mapped[str | None] = mapped_column(String(100))  # loại thảm
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class PriceRule(TimestampMixin, Base):
    """Bảng giá theo khung giờ.

    court_id = NULL -> áp dụng cho mọi sân. Rule gắn với sân cụ thể được ưu tiên hơn,
    sau đó tới priority cao hơn (vd: giờ vàng, ngày lễ).
    days_of_week: 0 = Thứ 2 ... 6 = Chủ nhật.
    """

    __tablename__ = "price_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    court_id: Mapped[int | None] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    days_of_week: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    price_per_hour: Mapped[int] = mapped_column(Integer)  # VND
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

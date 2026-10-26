"""DTO vào/ra của booking engine.

Dùng chung cho ``api.py`` (gọi trong tiến trình) và ``router.py`` (HTTP).

Không lộ ORM, không lộ id nội bộ của tài nguyên (dùng ``code``).
"""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.schemas import StrictIn

# "HH:MM", bội 30 phút; "24:00" = nửa đêm cuối ngày (chỉ có nghĩa với giờ đóng cửa)
HHMM = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):(00|30)|24:00)$")]
DayType = Literal["weekday", "weekend", "holiday"]
Band = Literal["offpeak", "peak"]
ActorType = Literal["admin", "staff", "customer", "system", "web"]


class Actor(BaseModel):
    """Người thao tác do lớp gọi (router/BFF) truyền vào – engine không biết về đăng nhập."""

    type: ActorType
    id: int | None = None
    label: str


# ---------- Tài nguyên (sân) ----------


class ScheduleOut(BaseModel):
    effective_from: dt.date
    open_time: str
    close_time: str
    peak_bands: list[tuple[str, str]]


class ResourceTypeOut(BaseModel):
    code: str
    name: str


class ResourceOut(BaseModel):
    code: str
    name: str
    resource_type_code: str
    resource_type_name: str
    sort_order: int
    is_active: bool
    version: int
    schedule: ScheduleOut | None = Field(description="Lịch đang áp dụng hôm nay")
    pending_schedule: ScheduleOut | None = Field(
        description="Lịch đã lưu, áp dụng từ ngày sau (effective_from > hôm nay)"
    )


class ResourceList(BaseModel):
    items: list[ResourceOut]
    resource_types: list[ResourceTypeOut]


class ResourceCreate(StrictIn):
    name: str = Field(max_length=200)
    resource_type_code: str = Field(max_length=20)
    open_time: HHMM
    close_time: HHMM
    peak_bands: list[tuple[HHMM, HHMM]] = Field(default_factory=list, max_length=12)


class ResourceUpdate(StrictIn):
    """Chỉ gửi trường muốn đổi. Giờ / cao điểm áp dụng từ ngày mai (D4)."""

    version: int
    name: str | None = Field(default=None, max_length=200)
    resource_type_code: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None
    open_time: HHMM | None = None
    close_time: HHMM | None = None
    peak_bands: list[tuple[HHMM, HHMM]] | None = Field(default=None, max_length=12)


class OccupiedSlot(BaseModel):
    """Một chỗ chiếm (booking / sự kiện / giữ chỗ) – dùng trong lỗi E-CFG-3 / E-CFG-4."""

    code: str | None
    date: dt.date
    start_time: str
    end_time: str


# ---------- Bảng giá ----------


class PriceCellIn(StrictIn):
    resource_type_code: str = Field(max_length=20)
    day_type: DayType
    band: Band
    price_per_hour: int = Field(strict=True)


class PriceCellOut(BaseModel):
    resource_type_code: str
    day_type: DayType
    band: Band
    price_per_hour: int


class PriceTable(BaseModel):
    version: int
    updated_at: dt.datetime | None
    updated_by: str | None
    resource_types: list[ResourceTypeOut]
    prices: list[PriceCellOut]


class PriceTableUpdate(StrictIn):
    version: int
    prices: list[PriceCellIn] = Field(max_length=200)


# ---------- Ngày Lễ / Tết ----------


class SpecialDayIn(StrictIn):
    date_from: dt.date
    date_to: dt.date | None = Field(default=None, description="Bỏ trống = 1 ngày")
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_range(self) -> "SpecialDayIn":
        if self.date_to is not None:
            if self.date_to < self.date_from:
                raise ValueError("Đến ngày phải bằng hoặc sau Từ ngày.")
            if self.date_to.year != self.date_from.year:
                raise ValueError("Từ ngày và Đến ngày phải trong cùng một năm.")
        return self


class SpecialDayOut(BaseModel):
    id: int
    date_from: dt.date
    date_to: dt.date
    name: str
    day_type: Literal["holiday"]


# ---------- Báo giá ----------


class QuoteIn(StrictIn):
    resource_code: str = Field(max_length=10)
    date: dt.date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)


class QuoteItem(BaseModel):
    start_time: str
    end_time: str
    band: Literal["offpeak", "partial", "peak"]
    label: str  # "Thấp điểm" / "Một phần cao điểm" / "Cao điểm"
    price: int


class QuoteOut(BaseModel):
    resource_code: str
    resource_name: str
    date: dt.date
    day_type: DayType
    price_version: int
    items: list[QuoteItem]
    total_amount: int

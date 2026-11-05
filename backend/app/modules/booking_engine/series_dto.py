"""DTO gói đặt theo tháng (quầy) – re-export ở ``dto.py`` (mặt tiền engine)."""

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.schemas import StrictIn

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SeriesStatus = Literal["active", "cancelled", "completed"]


class SeriesPlanIn(StrictIn):
    """Kế hoạch gói: tháng ``YYYY-MM`` (tháng này hoặc sau), 1 sân, 1 khung giờ, các thứ ISO
    (1 = Thứ Hai … 7 = Chủ nhật)."""

    resource_code: str = Field(max_length=10)
    month: str = Field(description="YYYY-MM", examples=["2026-11"])
    weekdays: list[int] = Field(min_length=1, max_length=7)
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)

    @field_validator("month")
    @classmethod
    def _month(cls, v: str) -> str:
        if not MONTH_RE.match(v):
            raise ValueError("Tháng phải có dạng YYYY-MM.")
        return v

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("Thứ trong tuần phải từ 1 (Thứ Hai) đến 7 (Chủ nhật).")
        return sorted(set(v))

    @property
    def first_day(self) -> dt.date:
        year, month = self.month.split("-")
        return dt.date(int(year), int(month), 1)


class SeriesPreviewDate(BaseModel):
    date: dt.date
    price: int = Field(description="Giá ngày đó theo bảng giá hiện hành (0 nếu không bán)")
    status: Literal["ok", "conflict"]
    reason: str | None = None


class SeriesPreviewOut(BaseModel):
    dates: list[SeriesPreviewDate] = Field(description="Ngày đã qua / khung đã bắt đầu không trả")
    total_ok: int = Field(description="Tổng tiền các ngày ``ok``")


class SeriesCreateIn(SeriesPlanIn):
    dates: list[dt.date] = Field(min_length=1, max_length=31)


class SeriesConflict(BaseModel):
    date: dt.date
    reason: str


class SeriesResource(BaseModel):
    code: str
    name: str


class SeriesCustomer(BaseModel):
    name: str
    phone: str | None
    kind: Literal["member", "temp"]
    member_code: str | None
    tier: str | None


class SeriesItemOut(BaseModel):
    date: dt.date
    booking_code: str
    price: int
    status: Literal["active", "cancelled"]
    payment_status: str


class SeriesOut(BaseModel):
    code: str
    resource: SeriesResource
    month: str
    weekdays: list[int]
    start_hour: int
    end_hour: int
    customer: SeriesCustomer
    total: int = Field(description="Tổng tiền các ngày lúc tạo")
    paid_total: int = Field(description="Tổng tiền các ngày đã thu")
    status: SeriesStatus
    items: list[SeriesItemOut]

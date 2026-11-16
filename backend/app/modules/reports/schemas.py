"""Hợp đồng API Báo cáo & phân tích. FE tự tính %, tô màu, làm tròn (BR-009, BR-010, BR-018)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Aliased(BaseModel):
    # "from" là từ khóa Python: tên trong code là date_from, ra JSON là "from"
    model_config = ConfigDict(populate_by_name=True)


class PeriodOut(_Aliased):
    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")
    days: int


class PreviousOut(_Aliased):
    date_from: dt.date = Field(alias="from")
    date_to: dt.date = Field(alias="to")
    until: dt.datetime | None = Field(
        description="So cùng mốc (BR-005): kỳ có hôm nay ⇒ ngày cuối kỳ trước chỉ tính tới mốc này"
    )


class MetricOut(BaseModel):
    current: int
    previous: int


class BookingsOut(MetricOut):
    tickets: int = Field(description="Số vé xé vé đã gồm trong current")


class DailyOut(BaseModel):
    date: dt.date
    revenue: int


class CourtOut(BaseModel):
    code: str
    name: str
    revenue: int
    is_active: bool


class HeatColumnOut(BaseModel):
    date: dt.date | None = Field(description="null khi mode = weekday")
    weekday: int = Field(ge=0, le=6, description="0 = T2 … 6 = CN")
    is_today: bool


class HeatCellOut(BaseModel):
    booked_hours: float
    open_hours: float = Field(description="0 ⇒ không sân nào mở, ô hiện “–”")


class HeatmapOut(BaseModel):
    mode: Literal["day", "weekday"]
    columns: list[HeatColumnOut]
    hours: list[int] = Field(description="Giờ bắt đầu khung 1 giờ, vd 5 = 05h–06h")
    cells: list[list[HeatCellOut]] = Field(description="cells[hàng giờ][cột]")


class ReportOverviewOut(BaseModel):
    period: PeriodOut
    previous: PreviousOut
    computed_at: dt.datetime
    active_courts: int
    revenue: MetricOut
    bookings: BookingsOut
    new_members: MetricOut
    daily: list[DailyOut]
    courts: list[CourtOut]
    heatmap: HeatmapOut

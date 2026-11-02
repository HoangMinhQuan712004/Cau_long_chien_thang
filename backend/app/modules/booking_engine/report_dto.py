"""DTO số liệu báo cáo của engine (SRS Báo cáo & phân tích) – re-export qua ``dto.py``.

Engine chỉ đưa số thô (tiền, lượt, giờ sân); kỳ, so sánh, gộp theo thứ do module ``reports`` làm.
"""

import datetime as dt

from pydantic import BaseModel


class RevenueTotals(BaseModel):
    """Tổng của một khoảng ngày chơi: doanh thu, lượt đặt (booking + vé), số vé."""

    revenue: int
    bookings: int
    tickets: int


class DailyRevenue(BaseModel):
    date: dt.date
    revenue: int


class CourtRevenue(BaseModel):
    code: str
    name: str
    revenue: int
    is_active: bool


class OccupancyCell(BaseModel):
    """Giờ sân đã đặt / giờ sân mở trong một khung 1 giờ của một ngày (cộng mọi sân)."""

    booked_hours: float
    open_hours: float


class OccupancyGrid(BaseModel):
    """``cells[i][j]``: khung bắt đầu ``hours[i]`` giờ của ngày ``days[j]``."""

    hours: list[int]
    days: list[dt.date]
    cells: list[list[OccupancyCell]]


class ReportFigures(BaseModel):
    """Số liệu kỳ đang xem + kỳ trước, đọc trong cùng một transaction của người gọi."""

    current: RevenueTotals
    previous: RevenueTotals
    daily: list[DailyRevenue]
    courts: list[CourtRevenue]
    active_courts: int
    occupancy: OccupancyGrid

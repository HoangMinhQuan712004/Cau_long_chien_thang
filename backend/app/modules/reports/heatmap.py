"""Dựng heatmap từ lưới giờ × ngày của engine (SRS Báo cáo & phân tích BR-016)."""

from datetime import date

from app.modules.booking_engine.dto import OccupancyGrid
from app.modules.reports.schemas import HeatCellOut, HeatColumnOut, HeatmapOut

MAX_DAY_COLUMNS = 7  # kỳ dài hơn ⇒ 7 cột T2 … CN


def build(grid: OccupancyGrid, today: date) -> HeatmapOut:
    """≤ 7 ngày: mỗi ngày 1 cột. Dài hơn: gộp ngày cùng thứ = tổng giờ đặt ÷ tổng giờ mở."""
    if len(grid.days) <= MAX_DAY_COLUMNS:
        return HeatmapOut(
            mode="day",
            columns=[
                HeatColumnOut(date=d, weekday=d.weekday(), is_today=d == today) for d in grid.days
            ],
            hours=grid.hours,
            cells=[
                [HeatCellOut(booked_hours=c.booked_hours, open_hours=c.open_hours) for c in row]
                for row in grid.cells
            ],
        )
    cells: list[list[HeatCellOut]] = []
    for row in grid.cells:
        booked, opened = [0.0] * 7, [0.0] * 7
        for day, cell in zip(grid.days, row, strict=True):
            booked[day.weekday()] += cell.booked_hours
            opened[day.weekday()] += cell.open_hours
        cells.append(
            [HeatCellOut(booked_hours=b, open_hours=o) for b, o in zip(booked, opened, strict=True)]
        )
    return HeatmapOut(
        mode="weekday",
        columns=[HeatColumnOut(date=None, weekday=w, is_today=False) for w in range(7)],
        hours=grid.hours,
        cells=cells,
    )

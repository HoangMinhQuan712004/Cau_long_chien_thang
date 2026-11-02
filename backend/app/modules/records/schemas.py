import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Period = Literal["week", "month", "year"]


class SpeedRankingRow(BaseModel):
    rank: int
    display_name: str = Field(description="'Hội viên ẩn danh' khi người đó tắt Hiện trên kỷ lục")
    avatar_url: str | None = Field(description="null với người ẩn danh (FE dùng avatar chung)")
    speed_kmh: int
    is_me: bool


class SpeedMe(BaseModel):
    rank: int
    speed_kmh: int = Field(description="Số đo cao nhất của mình trong kỳ")
    measured_at: dt.datetime
    gap_to_top10: int | None = Field(
        description="km/h hạng 10 − của mình; null khi mình đã trong top 10"
    )


class SpeedRanking(BaseModel):
    period: Period
    start: dt.date = Field(description="Ngày đầu kỳ (giờ VN)")
    end: dt.date = Field(description="Ngày cuối kỳ, tính cả ngày này (giờ VN)")
    total_members: int = Field(description="Số hội viên có số đo trong kỳ")
    top: list[SpeedRankingRow] = Field(description="Tối đa 10, hạng 1 trước")
    me: SpeedMe | None = Field(description="null: mình chưa có số đo trong kỳ")
    bar_floor_kmh: int = Field(description="Mốc đầu thanh tốc độ (FE)")

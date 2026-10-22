from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CourtBase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    surface: str | None = None
    image_url: str | None = None
    is_active: bool = True
    sort_order: int = 0


class CourtIn(CourtBase):
    slug: str | None = Field(default=None, max_length=120)


class CourtOut(CourtBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str


class PriceRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    court_id: int | None = None
    days_of_week: list[int] = Field(min_length=1)
    start_time: time
    end_time: time
    price_per_hour: int = Field(gt=0)
    priority: int = 0
    is_active: bool = True

    @model_validator(mode="after")
    def check(self):
        if any(d < 0 or d > 6 for d in self.days_of_week):
            raise ValueError("days_of_week phải trong khoảng 0..6")
        if self.start_time >= self.end_time:
            raise ValueError("start_time phải trước end_time")
        return self


class PriceRuleOut(PriceRuleIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class VenueConfigOut(BaseModel):
    open_time: time
    close_time: time
    slot_minutes: int
    min_booking_minutes: int
    max_advance_days: int
    hold_minutes: int
    timezone: str

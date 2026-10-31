"""Tổng quan + Lịch sử thanh toán khu hội viên (T-018)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.play_rooms.schemas import PersonOut


class UpcomingItem(BaseModel):
    room_id: int | None = Field(description="null: booking chưa có phòng -> ẩn nút Vào phòng")
    booking_code: str = Field(description="Mã con (id nội bộ) – không hiện cho khách")
    order_code: str | None = Field(description="Mã chung để hiện (T-019)")
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    phase: Literal["upcoming", "ongoing"]
    resource_name: str
    resource_type_name: str
    role: Literal["host", "member"]
    host_name: str = Field(description='Role host -> FE hiện "Host: bạn"')
    members_preview: list[PersonOut]
    count: int | None = Field(description="Số người trong phòng (null khi chưa có phòng)")
    capacity: int | None


class Overview(BaseModel):
    greeting_name: str = Field(description="Biệt danh, không có thì tên ngắn")
    today: dt.date = Field(description="Hôm nay (giờ VN)")
    today_count: int = Field(description="Lịch chơi hôm nay chưa kết thúc")
    upcoming: list[UpcomingItem] = Field(description="Tối đa 4: thẻ TIẾP THEO + 3 dòng")
    unread_count: int = Field(description="Thông báo chưa đọc")


Kind = Literal["booking", "ticket"]


class PaymentItem(BaseModel):
    kind: Kind
    code: str = Field(description="Id gọi chi tiết (mã con booking / mã vé) – không in ra")
    display_code: str = Field(description="Mã hiện cho khách: mã chung booking / mã vé")
    title: str = Field(description='"Đặt sân · Sân 1 · 18h–19h" / "Vé sự kiện · {tên} · {sân}"')
    event_name: str | None
    resource_names: list[str]
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    amount: int
    paid_at: dt.datetime
    method: Literal["QR", "Tiền mặt"] = Field(description="Tag hình thức")
    channel: Literal["counter", "online"] = Field(description="Tại quầy / online")


class BookingSummary(BaseModel):
    count: int
    hours: float = Field(description="Tổng giờ chơi các lượt đặt sân")


class TicketSummary(BaseModel):
    count: int
    total: int


class PaymentSummary(BaseModel):
    total: int = Field(description="Đã thanh toán trong tháng (VND)")
    count: int = Field(description="Số giao dịch (lượt đặt sân + vé)")
    bookings: BookingSummary
    tickets: TicketSummary


class PaymentList(BaseModel):
    month: str = Field(description="YYYY-MM đang xem")
    months: list[str] = Field(
        description="Dropdown: tối đa 12 tháng gần nhất có giao dịch, luôn có tháng hiện tại"
    )
    summary: PaymentSummary = Field(description="Cả tháng (không theo bộ lọc)")
    items: list[PaymentItem] = Field(description="Theo bộ lọc ``kind``, mới nhất trước")

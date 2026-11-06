"""Tổng quan + Lịch sử thanh toán khu hội viên (T-018)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.play_rooms.schemas import PersonOut, PlayHistorySummary, RoomCard
from app.modules.records.schemas import SpeedRankingRow, VideoOut


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
    # ---- Tổng quan v2 (T-036)
    month: str = Field(description="Tháng hiện tại YYYY-MM (giờ VN)")
    month_stats: PlayHistorySummary = Field(description="Buổi chơi / số trận / thắng trong tháng")
    month_record_kmh: int | None = Field(description="Số đo cao nhất của mình trong tháng")
    record_kmh: int | None = Field(description="Kỷ lục mọi thời gian của mình")
    open_rooms: list[RoomCard] = Field(
        description="Tối đa 3 phòng hôm nay còn mở, còn chỗ, mình chưa ở trong"
    )
    ranking: "OverviewRanking"
    recent_records: list["RecentRecord"] = Field(
        description="Tối đa 3 lần phá kỷ lục cụm gần nhất (mới nhất trước); rỗng -> ẩn khối"
    )
    upcoming_events: list["EventCard"] = Field(
        default_factory=list,
        description="T-045: tối đa 3 sự kiện chưa bắt đầu trong 14 ngày tới; rỗng -> ẩn khối",
    )


class EventCard(BaseModel):
    """Thẻ sự kiện sắp tới (T-045) – không danh sách người mua."""

    code: str
    name: str
    play_date: dt.date
    start_at: dt.datetime
    end_at: dt.datetime
    start_time: str
    end_time: str
    resource_names: list[str]
    ticket_price: int
    capacity: int
    taken: int = Field(description="Vé đã có + ghế đang giữ online")
    remaining: int
    can_buy: bool
    reason: Literal["full", "free", "online_off"] | None = Field(
        description="full = Đã đủ chỗ · free = Đăng ký tại quầy (giá 0) · online_off = đặt online "
        "tạm ngưng"
    )
    my_ticket_count: int = Field(description='"Bạn có n vé"')


class OverviewRankingMe(BaseModel):
    rank: int
    speed_kmh: int
    gap_to_top10: int | None = Field(description="null khi đã trong top 10")
    top10_kmh: int | None = Field(description="km/h của hạng 10 (null khi chưa đủ 10 người)")


class OverviewRanking(BaseModel):
    """Bảng xếp hạng tốc độ **tháng này**, xếp theo từng cú đập (T-053)."""

    total_members: int
    total_records: int = Field(description="Số cú đập trong tháng – mẫu của “#n / m”")
    me: OverviewRankingMe | None = Field(description="null: mình chưa có số đo trong tháng")
    top3: list[SpeedRankingRow]


class RecentRecord(BaseModel):
    speed_kmh: int
    delta_kmh: int | None = Field(description="+ so với kỷ lục cụm trước đó; null = lần đầu")
    display_name: str = Field(description="'Hội viên ẩn danh' khi người đó ẩn")
    avatar_url: str | None
    racket: str | None = Field(description="Vợt (T-033); null khi ẩn danh / chưa nhập")
    resource_name: str | None = Field(description="Sân đo; null khi số đo không gắn sân")
    measured_at: dt.datetime
    is_current: bool = Field(description="Đang giữ kỷ lục (thẻ viền vàng)")
    video: VideoOut | None = Field(
        default=None, description="T-046: có thì hiện nút ▶ phát tại chỗ (cả khi ẩn danh)"
    )


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
    cancelled: bool = Field(
        default=False, description="Đã thu rồi bị sân hủy: nhãn “Đã hủy · Đã hoàn n đ” (T-051)"
    )
    refund_amount: int = 0


class BookingSummary(BaseModel):
    count: int
    hours: float = Field(description="Tổng giờ chơi các lượt đặt sân")


class TicketSummary(BaseModel):
    count: int
    total: int


class PaymentSummary(BaseModel):
    total: int = Field(description="Đã thanh toán trong tháng (VND), không tính khoản đã hủy")
    count: int = Field(description="Số giao dịch (lượt đặt sân + vé), không tính khoản đã hủy")
    bookings: BookingSummary
    tickets: TicketSummary


class PaymentList(BaseModel):
    month: str = Field(description="YYYY-MM đang xem")
    months: list[str] = Field(
        description="Dropdown: tối đa 12 tháng gần nhất có giao dịch, luôn có tháng hiện tại"
    )
    summary: PaymentSummary = Field(description="Cả tháng (không theo bộ lọc)")
    items: list[PaymentItem] = Field(description="Theo bộ lọc ``kind``, mới nhất trước")


Overview.model_rebuild()

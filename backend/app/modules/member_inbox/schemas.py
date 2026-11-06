from datetime import datetime

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    kind: str = Field(
        description="room.invited · room.join_requested · room.join_approved · "
        "room.join_rejected · room.kicked · room.host_assigned · "
        "record.approved · record.rejected (T-047) · booking.cancelled · room.cancelled (T-051)"
    )
    text: str = Field(description="Câu hiển thị, vd. “Minh mời bạn vào phòng Sân 1 · 18h–19h.”")
    link: str | None = Field(description="Đường dẫn trong web, vd. /hoi-vien/phong/12")
    created_at: datetime
    read: bool


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread_count: int = Field(description="Số chưa đọc (30 ngày) – chấm số ở menu")

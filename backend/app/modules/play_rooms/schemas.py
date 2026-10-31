"""Phòng chơi (T-017). Không trả SĐT của ai (AC7, SEC2); id người = id dòng thành viên phòng."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

from app.modules.auth import api as auth

Format = Literal["2v2", "1v1"]
Phase = Literal["upcoming", "ongoing", "closed"]
Role = Literal["host", "member", "outsider"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionIn(_In):
    version: int = Field(description="``version`` của phòng lúc người dùng bấm (AC21)")


def _phone(value: str) -> str:
    phone = auth.normalize_phone(value)
    if phone is None:
        raise PydanticCustomError("invalid_phone", "Số điện thoại không hợp lệ.")
    return phone


class InviteIn(_In):
    phone: Annotated[str, Field(max_length=20), AfterValidator(_phone)] = Field(
        description="SĐT **đầy đủ** của hội viên được mời (chuẩn hóa như đăng nhập)"
    )
    version: int


class PersonOut(BaseModel):
    display_name: str = Field(description="Biệt danh nếu có, không thì Họ tên")
    avatar_url: str | None = Field(description="Ảnh đại diện; null -> FE hiện chữ cái đầu")


class RoomCard(BaseModel):
    """Thẻ phòng ở Danh sách sân (AC6)."""

    id: int
    resource_name: str = Field(description='"Sân 1"')
    resource_type_name: str = Field(description="Loại sân")
    start_at: dt.datetime
    end_at: dt.datetime
    phase: Literal["upcoming", "ongoing"]
    host: PersonOut
    members: list[PersonOut] = Field(description="Cụm avatar (Host đứng đầu)")
    member_count: int
    capacity: int = Field(description="8 người / sân, tính cả Host")
    is_mine: bool = Field(description='Mình đang trong phòng (tag "Bạn", nút "Vào phòng")')
    my_join_pending: bool = Field(description='Đã "Xin vào", đang chờ Host duyệt')
    my_invite_id: int | None = Field(description='Lời mời đang chờ mình ("Nhận lời mời")')
    version: int


class RoomList(BaseModel):
    date: dt.date = Field(description="Hôm nay (giờ Việt Nam)")
    ongoing_count: int = Field(description="Đang diễn ra")
    upcoming_count: int = Field(description="Sắp diễn ra")
    mine_count: int = Field(description='"Phòng của bạn" / "Sân của tôi (n)"')
    all_count: int = Field(description='"Tất cả (n)"')
    items: list[RoomCard] = Field(description="Theo giờ bắt đầu, rồi tên sân (lọc theo ``scope``)")


class RoomMemberOut(BaseModel):
    id: int = Field(description="Id dòng thành viên phòng – dùng cho mời ra / chuyển Host")
    display_name: str
    avatar_url: str | None
    role: Literal["host", "member"]
    queue_state: Literal["waiting", "playing"] = Field(description="Hàng chờ / Đang chơi")
    waiting_since: dt.datetime
    is_me: bool


class PendingPersonOut(BaseModel):
    id: int = Field(description="Id yêu cầu / lời mời")
    display_name: str
    avatar_url: str | None
    created_at: dt.datetime


class PlayerOut(BaseModel):
    member_id: int | None = Field(description="Id dòng thành viên (null nếu đã rời)")
    display_name: str
    avatar_url: str | None


class CurrentMatchOut(BaseModel):
    """Trận vừa bốc (``drawn``) hoặc đang chơi (``playing``) – mốc 2."""

    no: int
    format: Format
    status: Literal["drawn", "playing"]
    team_a: list[PlayerOut]
    team_b: list[PlayerOut]
    started_at: dt.datetime | None


class RoomDetail(BaseModel):
    id: int
    status: Literal["open", "closed"]
    phase: Phase
    format: Format
    resource_name: str
    resource_type_name: str
    start_at: dt.datetime
    end_at: dt.datetime
    closes_at: dt.datetime = Field(description="Giờ kết thúc + 10 phút: phòng tự khóa (AC3)")
    can_start_from: dt.datetime = Field(description="Bắt đầu trận được từ 15 phút trước giờ")
    capacity: int
    version: int
    my_role: Role
    my_join_pending: bool
    my_invite_id: int | None
    members: list[RoomMemberOut] = Field(description="Host đầu tiên, rồi theo giờ vào")
    join_requests: list[PendingPersonOut] = Field(description="Chỉ Host thấy (người khác: [])")
    invites: list[PendingPersonOut] = Field(description="Lời mời đang chờ – chỉ Host thấy")
    current_match: CurrentMatchOut | None

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.schemas import StrictIn


class MemberSearchItem(BaseModel):
    """Một dòng kết quả tìm hội viên – SĐT đã che (BR-021), không lộ id nội bộ."""

    ref: str = Field(description="Mã tham chiếu để chọn hội viên (= mã hội viên)")
    member_code: str
    name: str
    phone_masked: str
    tier: str | None
    is_active: bool


class TempCustomerIn(StrictIn):
    # Độ dài / định dạng kiểm ở service để trả mã lỗi SRS (E-001, E-002)
    full_name: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=20)
    note: str | None = Field(default=None, max_length=500)


class CustomerIn(StrictIn):
    """Khách của lượt đặt: đúng một trong hai – hội viên (theo mã) hoặc hồ sơ tạm."""

    member_code: str | None = Field(default=None, max_length=10)
    temp: TempCustomerIn | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "CustomerIn":
        if (self.member_code is None) == (self.temp is None):
            raise ValueError("Chọn đúng một: member_code hoặc temp.")
        return self


@dataclass(frozen=True)
class CustomerProfile:
    """Hồ sơ đã xác định – lớp gọi (front_desk) dùng để dựng snapshot cho booking engine."""

    ref: str  # id nội bộ dạng chuỗi – chỉ lưu trong DB, không trả ra API
    kind: str  # member | temp
    full_name: str
    phone: str
    member_code: str | None
    tier: str | None
    created: bool  # vừa tạo hồ sơ tạm mới
    is_active: bool = True


# ---------------------------------------------------------------- màn Hội viên (T-014)

Kind = Literal["member", "temp"]
# Trình độ chơi, thấp -> cao (khớp ``models.TIERS``)
Tier = Literal[
    "Yếu",
    "Trung bình yếu",
    "Trung bình -",
    "Trung bình",
    "Trung bình +",
    "Khá",
    "Bán chuyên",
    "Chuyên nghiệp",
]
Gender = Literal["male", "female"]


class MemberRow(BaseModel):
    """Một dòng danh sách – SĐT đã che (BR-021); ``ref`` = mã HV hoặc mã tham chiếu hồ sơ tạm."""

    ref: str
    kind: Kind
    member_code: str | None
    full_name: str
    phone_masked: str
    gender: Gender | None
    tier: Tier | None
    racket: str | None
    is_active: bool
    bookings: int
    created_at: dt.datetime


class MemberCounts(BaseModel):
    all: int
    member: int
    temp: int


class MemberCan(BaseModel):
    """Quyền của người xem – FE khóa ô Trạng thái khi ``edit_status = False``."""

    edit_status: bool
    manage_rackets: bool = Field(description="Thấy nút Danh mục vợt (thêm / sửa / ẩn)")


class MemberListOut(BaseModel):
    items: list[MemberRow]
    total: int
    page: int
    size: int
    counts: MemberCounts = Field(description="Đếm theo loại (theo q/status/tier, bỏ qua kind)")
    can: MemberCan


class MemberBooking(BaseModel):
    code: str
    play_date: dt.date
    start_time: str
    end_time: str
    resource_name: str
    amount: int


class MemberDetail(MemberRow):
    """Chi tiết – có SĐT đầy đủ (form Sửa), mỗi lần xem ghi nhật ký ``member.view``."""

    phone: str
    note: str | None
    total_minutes: int
    recent_bookings: list[MemberBooking] = Field(description="5 lượt đặt gần nhất")
    can: MemberCan


class NextCodeOut(BaseModel):
    member_code: str = Field(description="Chỉ để hiển thị – mã thật cấp lúc lưu")


class MemberCreateIn(StrictIn):
    """Thêm hội viên. Độ dài, định dạng kiểm ở service (mã lỗi SRS)."""

    full_name: str = Field(max_length=200)
    phone: str = Field(max_length=20)
    gender: Gender | None = None
    tier: Tier | None = Field(default=None, description="Trình độ; bỏ trống = chưa xếp hạng")
    racket: str | None = Field(default=None, max_length=100)
    upgrade_temp: bool = Field(
        default=False,
        description="SĐT đang là hồ sơ tạm (E-MEM-1) -> true: nâng chính hồ sơ đó (giữ lịch sử)",
    )


class MemberUpdateIn(StrictIn):
    """Chỉ gửi trường muốn đổi; không đổi SĐT. Hồ sơ tạm: chỉ ``full_name``, ``gender``.

    ``tier: null`` = bỏ xếp hạng; trạng thái: chỉ Admin.
    """

    full_name: str | None = Field(default=None, max_length=200)
    gender: Gender | None = None
    tier: Tier | None = None
    racket: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class TempCreateIn(StrictIn):
    full_name: str = Field(max_length=200)
    phone: str = Field(max_length=20)
    gender: Gender | None = None


# ---------------------------------------------------------------- danh mục vợt


class RacketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    sort_order: int
    member_count: int = Field(description="Số hồ sơ đang ghi vợt này (khớp tên chuẩn hóa)")


class RacketCreateIn(StrictIn):
    name: str = Field(max_length=200)
    sort_order: int = Field(default=0, ge=0, le=10_000)


class RacketUpdateIn(StrictIn):
    """Chỉ gửi trường muốn đổi; ẩn vợt không làm đổi hồ sơ hội viên đang dùng tên đó."""

    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


# ---------------------------------------------------------------- hội viên của chính khách (T-015)


class MyMemberOut(BaseModel):
    """Thẻ Hội viên ở /tai-khoan – chỉ hồ sơ khớp SĐT của chính người đăng nhập."""

    member_code: str
    full_name: str
    tier: Tier | None
    is_active: bool
    gender: Gender | None
    racket: str | None
    created_at: dt.datetime
    bookings: int
    total_minutes: int


class MyBookingsOut(BaseModel):
    items: list[MemberBooking]
    total: int
    page: int
    size: int

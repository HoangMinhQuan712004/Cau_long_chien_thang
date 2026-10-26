from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

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

import datetime as dt

from pydantic import BaseModel, Field

from app.core.schemas import StrictIn


class MemberMeOut(BaseModel):
    """Hồ sơ của chính hội viên đang đăng nhập (SĐT, email đầy đủ – chỉ chính chủ thấy)."""

    member_code: str
    full_name: str
    short_name: str = Field(description="Từ cuối của Họ tên (nút tài khoản, chữ cái avatar)")
    nickname: str | None
    email: str | None
    phone: str = Field(description="Đầy đủ 0xxxxxxxxx – FE nhóm 4-3-3")
    joined_at: dt.date = Field(description="Ngày tạo hồ sơ hội viên (giờ VN)")
    tier: str | None = Field(description="Trình độ = Hạng (8 bậc); null = chưa xếp hạng")
    racket: str | None = Field(description="Tên vợt đang dùng (danh mục GET /rackets)")
    show_on_records: bool
    avatar_url: str | None = Field(description="Đã gồm ?v={etag}; null -> hiện chữ cái")
    record_kmh: int | None = Field(default=None, description="Đợt 1 chưa có dữ liệu kỷ lục")
    version: int


class MemberMeIn(StrictIn):
    """Độ dài / định dạng kiểm ở server để trả ``fields`` (E-HV-1/10/11) – chuỗi rỗng = null."""

    full_name: str = Field(max_length=300)
    nickname: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=400)
    tier: str | None = Field(
        max_length=50, description="1 trong 8 bậc; null chỉ khi hồ sơ đang chưa xếp hạng"
    )
    racket: str | None = Field(
        default=None,
        max_length=200,
        description="Tên vợt; chưa có trong danh mục -> tự thêm (như màn Hội viên)",
    )
    show_on_records: bool
    version: int


class AvatarOut(BaseModel):
    avatar_url: str

import datetime as dt

from pydantic import BaseModel, Field

from app.core.schemas import StrictIn
from app.modules.members.api import GENDERS, Gender


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
    gender: Gender | None = Field(description="null = Chưa chọn")
    racket: str | None = Field(description="Tên vợt đang dùng (tự nhập)")
    show_on_records: bool
    avatar_url: str | None = Field(description="Đã gồm ?v={etag}; null -> hiện chữ cái")
    record_kmh: int | None = Field(
        default=None, description="Kỷ lục tốc độ cú đập mọi thời gian (km/h); null: chưa có số đo"
    )
    version: int


class MemberMeIn(StrictIn):
    """Độ dài / định dạng kiểm ở server để trả ``fields`` (E-HV-1/10/11) – chuỗi rỗng = null."""

    full_name: str = Field(max_length=300)
    nickname: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=400)
    tier: str | None = Field(
        default=None,
        max_length=50,
        description="Hạng tự chọn (T-042): một trong 8 bậc hoặc null (Chưa xếp hạng); giá trị lạ "
        "-> 422 (fields: tier, E-HV-1). Không gửi = giữ hạng hiện tại",
    )
    gender: str | None = Field(
        default=None,
        max_length=20,
        # Cho FE kiểu "male" | "female" | null; kiểm giá trị ở service để trả ``fields``
        json_schema_extra={"anyOf": [{"type": "string", "enum": list(GENDERS)}, {"type": "null"}]},
        description="Giới tính tự chọn: male / female hoặc null (Chưa chọn); giá trị lạ -> 422 "
        "(fields: gender, E-HV-1). Không gửi = giữ nguyên",
    )
    racket: str | None = Field(
        default=None,
        max_length=300,
        description="Tên vợt tự nhập (T-033): gộp khoảng trắng, tối đa 100 ký tự, rỗng = null; "
        "không dùng danh mục",
    )
    show_on_records: bool
    version: int


class AvatarOut(BaseModel):
    avatar_url: str

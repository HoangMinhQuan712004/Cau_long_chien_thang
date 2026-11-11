import datetime as dt
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field

Period = Literal["week", "month", "year"]


class VideoOut(BaseModel):
    kind: Literal["youtube", "file"]
    url: str = Field(description="Link Admin đã dán")
    embed_url: str | None = Field(description="YouTube: youtube-nocookie.com/embed/{id}")
    thumbnail_url: str | None = Field(description="YouTube: ảnh xem trước i.ytimg.com")


class SpeedRankingRow(BaseModel):
    rank: int
    display_name: str = Field(description="'Hội viên ẩn danh' khi người đó tắt Hiện trên kỷ lục")
    avatar_url: str | None = Field(description="null với người ẩn danh (FE dùng avatar chung)")
    speed_kmh: int
    measured_at: dt.datetime = Field(description="Lúc đo của đúng cú đập này")
    resource_name: str | None = Field(default=None, description="Sân của đúng cú đập này (T-053)")
    is_me: bool
    video: VideoOut | None = Field(
        description="Video của đúng số đo xếp hạng; số đo đó không có thì null, không lấy số đo "
        "khác. Ẩn danh vẫn phát"
    )


class SpeedMe(BaseModel):
    rank: int = Field(description="Hạng cú tốt nhất của mình trong kỳ (T-053)")
    display_name: str = Field(description="Cùng tên với bục và danh sách: biệt danh trước")
    avatar_url: str | None
    speed_kmh: int = Field(description="Số đo cao nhất của mình trong kỳ")
    measured_at: dt.datetime
    gap_to_top10: int | None = Field(
        description="km/h hạng 10 − của mình; null khi mình đã trong top 10"
    )
    video: VideoOut | None = Field(description="Video của đúng số đo xếp hạng của mình")


class SpeedRanking(BaseModel):
    period: Period
    start: dt.date = Field(description="Ngày đầu kỳ (giờ VN)")
    end: dt.date = Field(description="Ngày cuối kỳ, tính cả ngày này (giờ VN)")
    total_members: int = Field(description="Số hội viên có số đo trong kỳ")
    total_records: int = Field(description="Số cú đập trong kỳ – mẫu của “#n / m” (T-053)")
    top: list[SpeedRankingRow] = Field(
        description="Tối đa 10 **cú đập**, hạng 1 trước; một người có thể chiếm nhiều bậc"
    )
    me: SpeedMe | None = Field(description="null: mình chưa có số đo trong kỳ")
    bar_floor_kmh: int = Field(description="Mốc đầu thanh tốc độ (FE)")


# ------------------------------------------------------------------ video kỷ lục (T-046)


class VideoIn(BaseModel):
    url: str = Field(max_length=1000, description="https YouTube hoặc file .mp4 / .webm")


Source = Literal["device", "admin", "member"]
Status = Literal["approved", "pending", "rejected"]


class AdminSpeedRecordRow(BaseModel):
    id: int
    speed_kmh: int
    measured_at: dt.datetime
    member_code: str | None
    member_name: str
    resource_code: str | None = Field(description="Mã sân (T-047) – null: không ghi sân")
    resource_name: str | None
    video: VideoOut | None
    source: Source = Field(description="device: Máy đo · admin: Admin nhập · member: Hội viên gửi")
    status: Status = Field(description="approved: tính hạng · pending: chờ duyệt · rejected")
    reject_reason: str | None
    wins: int | None = Field(description="Số trận thắng trong buổi; null = không ghi")
    losses: int | None
    editable: bool = Field(description="false với số đo máy đo (không sửa / xóa được, E-REC-2)")
    submitted_at: dt.datetime = Field(description="Lúc nhập / gửi")
    version: int = Field(description="Gửi kèm khi sửa (PATCH); lệch -> 409 E-REC-3")


class AdminSpeedRecordList(BaseModel):
    items: list[AdminSpeedRecordRow]
    page: int
    size: int
    total: int
    pending_count: int = Field(description="Số bản chờ duyệt (tab “Chờ duyệt (n)”), không theo lọc")


# ------------------------------------------------------------------ nhập tay / gửi (T-047)

Kmh = Annotated[int, Field(ge=50, le=500, description="km/h, số nguyên 50–500")]
MeasuredAt = Annotated[
    AwareDatetime, Field(description="Có múi giờ; không ở tương lai, không quá 365 ngày trước")
]
ResourceCode = Annotated[str | None, Field(max_length=20, description="Mã sân đang có")]
VideoUrl = Annotated[
    str | None, Field(max_length=1000, description="YouTube / .mp4 / .webm (https), E-REC-1")
]


class SpeedRecordCreateIn(BaseModel):
    """Admin nhập số đo -> duyệt ngay (``source=admin``)."""

    member_code: str = Field(min_length=1, max_length=20, description="Mã HV (hội viên Hoạt động)")
    speed_kmh: Kmh
    measured_at: MeasuredAt
    resource_code: ResourceCode = None
    video_url: VideoUrl = None
    wins: int = Field(ge=0, le=99, description="Số trận thắng trong buổi (bắt buộc)")
    losses: int = Field(
        ge=0, le=99, description="Số trận thua (bắt buộc); tổng thắng + thua = 0 -> 422 E-REC-9"
    )


class SpeedRecordPatchIn(BaseModel):
    """Chỉ gửi ô muốn đổi; ``resource_code`` / ``video_url`` = null -> bỏ sân / gỡ video;
    ``wins`` / ``losses`` đổi thì gửi đủ cả hai (không xóa được)."""

    version: int = Field(ge=1)
    speed_kmh: Kmh | None = None
    measured_at: MeasuredAt | None = None
    resource_code: ResourceCode = None
    video_url: VideoUrl = None
    wins: int | None = Field(
        default=None, ge=0, le=99, description="Số trận thắng trong buổi; gửi cùng ``losses``"
    )
    losses: int | None = Field(
        default=None,
        ge=0,
        le=99,
        description="Số trận thua; đổi thì gửi đủ cả hai (thiếu / null / tổng 0 -> 422 E-REC-9)",
    )


class RejectIn(BaseModel):
    reason: str = Field(max_length=500, description="Bắt buộc, tối đa 200 ký tự sau khi cắt trống")


class SpeedSubmitIn(BaseModel):
    """Hội viên gửi cú đập của chính mình -> chờ Admin duyệt."""

    speed_kmh: Kmh
    measured_at: MeasuredAt
    resource_code: ResourceCode = None
    video_url: VideoUrl = None
    wins: int = Field(ge=0, le=99, description="Số trận thắng trong buổi đập cú này (bắt buộc)")
    losses: int = Field(
        ge=0, le=99, description="Số trận thua (bắt buộc); tổng thắng + thua = 0 -> 422 E-REC-9"
    )


class MySpeedRecord(BaseModel):
    id: int
    speed_kmh: int
    measured_at: dt.datetime
    resource_code: str | None
    resource_name: str | None
    status: Status = Field(description="pending: “Chờ duyệt” · rejected: “Bị từ chối: {lý do}”")
    reject_reason: str | None
    video: VideoOut | None
    submitted_at: dt.datetime
    can_withdraw: bool = Field(description="true khi đang chờ duyệt (nút “Rút lại”)")


class ResourceOption(BaseModel):
    code: str
    name: str


class MySpeedRecordList(BaseModel):
    items: list[MySpeedRecord] = Field(description="Bản tôi đã gửi, mới gửi trước (tối đa 50)")
    resources: list[ResourceOption] = Field(description="Sân đang hoạt động (hộp “Gửi cú đập”)")
    daily_limit: int = Field(description="Số lượt gửi tối đa / ngày")


VideoPeriod = Literal["week", "month", "year", "all"]


class RecordVideoCard(BaseModel):
    """Thẻ Video & kỷ lục (T-046) – ẩn danh như T-030 (mình luôn thấy tên mình)."""

    speed_kmh: int
    measured_at: dt.datetime
    display_name: str
    avatar_url: str | None
    resource_name: str | None
    is_me: bool
    video: VideoOut


class RecordVideoList(BaseModel):
    period: VideoPeriod
    start: dt.date | None = Field(description="null khi period = all")
    end: dt.date | None
    items: list[RecordVideoCard] = Field(description="Mới nhất trước, tối đa 60")


# ------------------------------------------------------------------ dòng thời gian (T-048)


class PlayStats(BaseModel):
    """Thắng / thua trong buổi phá kỷ lục: số hội viên tự nhập khi gửi (ưu tiên), không có thì tự
    tính từ phòng chơi cùng sân, khung giờ chứa lúc đo."""

    start_at: dt.datetime | None = Field(description="Khung giờ buổi chơi; null khi là số tự nhập")
    end_at: dt.datetime | None
    matches: int = Field(description="Số trận đã lưu kết quả mà người này ở đội A/B (≥ 1)")
    wins: int = Field(description="2 vs 2: cả 2 người đội thắng đều được tính")
    losses: int


class RecordBreakItem(BaseModel):
    """Một lần phá kỷ lục cụm. Ẩn danh như T-030: chỉ còn số đo, sân, thời điểm và video."""

    id: int
    speed_kmh: int
    delta_kmh: int | None = Field(description="Hơn kỷ lục trước bao nhiêu km/h; null = mốc đầu")
    previous_kmh: int | None = Field(description="Kỷ lục ngay trước; null = mốc đầu")
    is_current: bool = Field(description="Đang giữ kỷ lục của cả cụm")
    is_baseline: bool = Field(description="Số đo đầu tiên của chuỗi; chỉ có khi period = all")
    held_days: int = Field(
        description="Số ngày giữ kỷ lục theo ngày giờ VN: lần sau − lần này; đang giữ: hôm nay − "
        "lần này. 0 = dưới 1 ngày"
    )
    measured_at: dt.datetime
    label_date: dt.date = Field(
        description="Ngày trên nhãn “Kỷ lục ngày dd/mm” (giờ VN): lần dán link video mới nhất; "
        "chưa có video thì ngày đo"
    )
    display_name: str = Field(
        description="Họ tên thật (khác các API khác, nơi đây là biệt danh nếu có); 'Hội viên ẩn "
        "danh' khi người đó tắt Hiện trên kỷ lục"
    )
    nickname: str | None = Field(description="null khi không đặt biệt danh hoặc ẩn danh")
    tier: str | None
    avatar_url: str | None
    racket: str | None = Field(description="Vợt hiện tại trong hồ sơ, không phải vợt lúc đo")
    resource_name: str | None
    is_me: bool
    video: VideoOut | None = Field(description="null: “Chưa có video”")
    play_stats: PlayStats | None = Field(
        description="Thắng / thua trong buổi phá kỷ lục; null: ẩn danh, không có sân, không thuộc "
        "phòng chơi nào hoặc buổi đó chưa lưu trận nào của người này"
    )


class RecordBreakList(BaseModel):
    period: VideoPeriod
    start: dt.date | None = Field(description="null khi period = all")
    end: dt.date | None = Field(description="Ngày cuối kỳ, tính cả ngày này; null khi period = all")
    items: list[RecordBreakItem] = Field(description="Mới nhất trước, không phân trang")

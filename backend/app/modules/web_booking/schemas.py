import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import StrictIn
from app.modules.booking_engine.dto import (
    CheckoutEvent,
    EventInfo,
    LookupEvent,
    OnlineSlotIn,
    PublicCalendarResource,
)
from app.modules.members.api import Tier
from app.modules.payments.api import BankInfo


class WebCalendarOut(BaseModel):
    date: dt.date
    server_now: dt.datetime
    online_enabled: bool
    hold_minutes: int
    columns: list[int]
    resources: list[PublicCalendarResource]


class CheckoutIn(StrictIn):
    date: dt.date
    slots: list[OnlineSlotIn] = Field(default_factory=list, max_length=200)
    # Độ dài / định dạng kiểm ở server để trả E-WEB-1 với câu chữ theo trường
    full_name: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=50)
    note: str | None = Field(default=None, max_length=1000)
    # Token từ /web/booking/phone/verify (T-013 AC26); khách đăng nhập có SĐT đã xác minh trùng
    # ``phone`` thì không cần
    phone_token: str | None = Field(default=None, max_length=128)
    as_member: bool = Field(
        default=False,
        description="Đặt trong khu hội viên (/hoi-vien/dat-san): Họ tên + SĐT lấy từ hồ sơ, "
        "bỏ qua full_name/phone gửi lên, không cần phone_token (T-018 AC4)",
    )
    # T-031: khoảng hạng phòng chơi của đơn – chỉ khi ``as_member`` (đặt công khai gửi -> E-ROOM-14)
    min_tier: Tier | None = Field(
        default=None,
        description="Chỉ với as_member (đặt công khai gửi -> 422 E-ROOM-14). Hạng thấp nhất được "
        "vào phòng (null = không giới hạn dưới)",
    )
    max_tier: Tier | None = Field(
        default=None,
        description="Hạng cao nhất (null = không giới hạn trên); min ≤ max (E-ROOM-14)",
    )


class PhoneCodeIn(StrictIn):
    phone: str = Field(max_length=50)


class PhoneCodeSentOut(BaseModel):
    resend_after: int = Field(description="Giây tới lúc được gửi lại mã")
    test_otp: str | None = Field(default=None, description="Chỉ khi OTP_TEST_MODE (link dev)")


class PhoneVerifyIn(StrictIn):
    phone: str = Field(max_length=50)
    otp: str = Field(pattern=r"^\d{6}$")


class PhoneTokenOut(BaseModel):
    phone_token: str
    expires_at: dt.datetime
    account_verified: bool = Field(
        default=False,
        description="Khách đang đăng nhập có SĐT trùng SĐT vừa xác minh -> tài khoản đã xác minh, "
        "lần đặt sau không cần OTP (cả khi đã xác minh từ trước)",
    )
    became_member: bool = Field(
        default=False,
        description="T-021: tài khoản đang đăng nhập vừa thành hội viên nhờ lần xác minh này",
    )
    member_code: str | None = Field(
        default=None, description="Mã HV của tài khoản đang đăng nhập (đã là / vừa thành hội viên)"
    )
    reason: str | None = Field(
        default=None,
        description="Khách đang đăng nhập nhưng tài khoản không được gắn SĐT / thành hội viên: "
        "E-AUTH-17 (tài khoản có SĐT khác), E-AUTH-18 (SĐT không dùng được), E-AUTH-31 (hội viên "
        "Ngừng – tài khoản bị khóa). ``phone_token`` vẫn dùng được để đặt",
    )
    account_merged: bool = Field(
        default=False,
        description="Tài khoản Google vừa được gộp vào tài khoản chủ SĐT – cookie đã đổi, FE tải "
        "lại thông tin tài khoản",
    )


class WebCustomer(BaseModel):
    full_name: str
    phone_masked: str | None


class WebCheckoutItem(BaseModel):
    code: str = Field(description="Mã con {mã đơn}-NN – FE không hiện cho khách (ADR-010)")
    resource_code: str
    resource_name: str
    play_date: dt.date
    start_time: str
    end_time: str
    start_hour: int
    hours: int
    amount: int


class CheckoutOut(BaseModel):
    kind: Literal["court", "ticket"] = Field(description="court: đặt sân · ticket: mua vé (T-023)")
    status: Literal["pending", "paid", "expired"]
    expires_at: dt.datetime
    server_now: dt.datetime
    amount: int
    paid_amount: int
    paid_at: dt.datetime | None
    order_code: str = Field(description="Mã đơn – khách chỉ thấy mã này")
    pay_ref: str = Field(description="Nội dung chuyển khoản = mã đơn bỏ dấu gạch")
    bank: BankInfo | None = Field(description="Chỉ có khi đang chờ thanh toán")
    customer: WebCustomer
    items: list[WebCheckoutItem] = Field(description="Khung sân – rỗng khi kind = ticket")
    event: CheckoutEvent | None = Field(
        description="Chỉ khi kind = ticket: sự kiện, số vé, mã vé (có khi đã thanh toán)"
    )


class CheckoutCreatedOut(CheckoutOut):
    token: str = Field(description="Chìa khóa trang /thanh-toan/{token} – chỉ trả ở lần tạo")


class LookupIn(StrictIn):
    code: str = Field(default="", max_length=60)
    phone: str = Field(default="", max_length=50)


class LookupPendingOut(BaseModel):
    expires_at: dt.datetime
    server_now: dt.datetime
    pay_ref: str
    amount: int
    bank: BankInfo | None


class LookupItemOut(BaseModel):
    code: str = Field(description="Mã con – FE không hiện cho khách")
    resource_name: str
    start_time: str
    end_time: str
    hours: int
    amount: int
    status: Literal["paid", "unpaid", "uncollectible", "pending", "expired"]


class LookupOut(BaseModel):
    """Tra cứu bằng mã đơn **hoặc** mã con + SĐT -> cả đơn (T-019 AC3). Đơn vé (T-023 AC21): mã
    đơn vé hoặc mã vé ``{mã sự kiện}-Vnn`` -> ``kind = ticket`` + khối ``event``."""

    kind: Literal["court", "ticket"]
    order_code: str = Field(description="Mã đơn; vé đăng ký tại quầy tra theo mã vé -> mã vé")
    status: Literal["paid", "unpaid", "uncollectible", "pending", "expired"]
    play_date: dt.date
    hours: int = Field(description="Tổng giờ của đơn")
    customer_name: str
    phone_masked: str | None
    amount: int = Field(description="Tổng tiền của đơn")
    payment_method_label: str | None
    paid_at: dt.datetime | None
    items: list[LookupItemOut] = Field(description="Khối sân – rỗng khi kind = ticket")
    pending: LookupPendingOut | None = None
    event: LookupEvent | None = Field(
        default=None, description="Chỉ khi kind = ticket: sự kiện, số vé, mã vé + trạng thái"
    )


# ------------------------------------------------------------------ vé sự kiện online (T-023)


class WebEventOut(EventInfo):
    """Chi tiết sự kiện công khai – không tên / SĐT người mua. ``my_tickets`` chỉ khi có cookie
    hội viên liên kết (null với khách)."""

    reason: Literal["started", "full", "free", "deleted", "online_off"] | None = Field(
        description="Lý do can_buy = false: started (đã bắt đầu), full (hết chỗ), free (giá 0 – "
        "đăng ký tại quầy), deleted (đã hủy), online_off (đặt online tạm ngưng)"
    )
    hold_minutes: int


class EventCheckoutIn(StrictIn):
    event_code: str = Field(max_length=40)
    seats: int = Field(description="1..min(còn lại, 10) – sai -> 422 E-WEB-1")
    full_name: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=50)
    phone_token: str | None = Field(default=None, max_length=128)
    as_member: bool = Field(
        default=False,
        description="Hội viên liên kết: Họ tên + SĐT lấy từ hồ sơ, không cần phone_token",
    )

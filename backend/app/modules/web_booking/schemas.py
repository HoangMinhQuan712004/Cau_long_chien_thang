import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import StrictIn
from app.modules.booking_engine.dto import OnlineSlotIn, PublicCalendarResource
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
    items: list[WebCheckoutItem]


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
    """Tra cứu bằng mã đơn **hoặc** mã con + SĐT -> cả đơn (T-019 AC3)."""

    order_code: str
    status: Literal["paid", "unpaid", "uncollectible", "pending", "expired"]
    play_date: dt.date
    hours: int = Field(description="Tổng giờ của đơn")
    customer_name: str
    phone_masked: str | None
    amount: int = Field(description="Tổng tiền của đơn")
    payment_method_label: str | None
    paid_at: dt.datetime | None
    items: list[LookupItemOut]
    pending: LookupPendingOut | None = None

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


class WebCustomer(BaseModel):
    full_name: str
    phone_masked: str | None


class WebCheckoutItem(BaseModel):
    code: str
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
    pay_ref: str
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


class LookupOut(BaseModel):
    code: str
    status: Literal["paid", "unpaid", "uncollectible", "pending", "expired"]
    resource_name: str
    play_date: dt.date
    start_time: str
    end_time: str
    hours: int
    customer_name: str
    phone_masked: str | None
    amount: int
    payment_method_label: str | None
    paid_at: dt.datetime | None
    pending: LookupPendingOut | None = None

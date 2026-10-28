from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import StrictIn

Outcome = Literal["applied", "partial", "refund_needed", "unmatched", "ignored"]


class BankInfo(BaseModel):
    """Thông tin chuyển khoản hiển thị cho khách (QR SePay)."""

    bank_name: str
    account_number: str
    account_name: str
    qr_url: str


class BankTransactionOut(BaseModel):
    id: int
    provider: str
    provider_txn_id: str
    received_at: datetime
    transaction_at: datetime
    amount: int
    content: str
    code: str | None
    outcome: Outcome
    refund_amount: int
    booking_codes: list[str]
    resolved_at: datetime | None
    resolved_by_label: str | None
    note: str | None


class ResolveIn(StrictIn):
    note: str = Field(default="", max_length=1000)


class SimulateIn(StrictIn):
    pay_ref: str = Field(max_length=20)
    amount: int = Field(gt=0, le=1_000_000_000)


class BankOut(BaseModel):
    code: str
    short_name: str
    name: str


class PaymentSettingsOut(BaseModel):
    bank_code: str | None
    bank_name: str | None
    account_number: str | None
    account_name: str | None
    online_toggle: bool
    online_enabled: bool
    missing: list[Literal["bank", "account_number", "account_name", "webhook_secret"]]
    secret_set: bool
    secret_last4: str | None
    webhook_url: str
    pay_code_hint: str
    last_webhook_at: datetime | None
    updated_at: datetime | None
    updated_by_label: str | None
    pending_checkouts: int
    simulate_enabled: bool


class PaymentSettingsIn(StrictIn):
    # Kiểm định dạng ở server để trả E-PAY-4 theo từng trường. Không tự cắt khoảng trắng:
    # mật khẩu và khóa phải giữ nguyên văn.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    bank_code: str = Field(max_length=50)
    account_number: str = Field(max_length=50)
    account_name: str = Field(max_length=200)
    online_toggle: bool
    webhook_secret: str | None = Field(
        default=None, max_length=1000, description="Bỏ qua / null = giữ khóa đang có"
    )
    current_password: str = Field(max_length=200)

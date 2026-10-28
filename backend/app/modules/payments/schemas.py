from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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

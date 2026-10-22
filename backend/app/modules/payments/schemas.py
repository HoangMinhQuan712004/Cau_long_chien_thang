from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.payments.models import PaymentMethod, PaymentStatus


class ManualPaymentIn(BaseModel):
    method: PaymentMethod = PaymentMethod.CASH
    amount: int | None = Field(default=None, gt=0)  # mặc định = tổng tiền đơn


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    method: PaymentMethod
    status: PaymentStatus
    amount: int
    provider_ref: str | None
    created_at: datetime
